"""Provider-neutral structured generation and embedding helpers.

Ollama is the default backend so the pipeline can run locally without per-request
fees. OpenAI remains available as an opt-in backend for users who need hosted-model
quality or throughput.
"""

from __future__ import annotations

import threading
from typing import TypeVar

from pydantic import BaseModel

from .config import Settings


StructuredModel = TypeVar("StructuredModel", bound=BaseModel)
_thread_state = threading.local()


def _ollama_client(settings: Settings):
    try:
        from ollama import Client
    except ImportError as exc:  # pragma: no cover - exercised by installation failures
        raise RuntimeError(
            "The Ollama Python package is missing. Run `pip install -r requirements.txt`."
        ) from exc

    cache_key = (settings.ollama_base_url, settings.llm_timeout_seconds)
    client = getattr(_thread_state, "ollama_client", None)
    if client is None or getattr(_thread_state, "ollama_cache_key", None) != cache_key:
        client = Client(
            host=settings.ollama_base_url,
            timeout=settings.llm_timeout_seconds,
        )
        _thread_state.ollama_client = client
        _thread_state.ollama_cache_key = cache_key
    return client


def _openai_client(settings: Settings):
    try:
        import instructor
    except ImportError as exc:  # pragma: no cover - exercised by installation failures
        raise RuntimeError(
            "OpenAI support dependencies are missing. Run `pip install -r requirements.txt`."
        ) from exc

    cache_key = (settings.llm_model, settings.openai_api_key)
    client = getattr(_thread_state, "openai_instructor_client", None)
    if client is None or getattr(_thread_state, "openai_cache_key", None) != cache_key:
        client = instructor.from_provider(
            f"openai/{settings.llm_model}",
            mode=instructor.Mode.RESPONSES_TOOLS,
            api_key=settings.openai_api_key,
        )
        _thread_state.openai_instructor_client = client
        _thread_state.openai_cache_key = cache_key
    return client


def structured_response(
    settings: Settings,
    prompt: str,
    response_model: type[StructuredModel],
) -> StructuredModel:
    """Generate and validate one schema-constrained model response."""
    if settings.llm_provider == "openai":
        return _openai_client(settings).responses.create(
            input=prompt,
            response_model=response_model,
            max_output_tokens=settings.llm_max_output_tokens,
            max_retries=settings.llm_max_retries,
        )

    client = _ollama_client(settings)
    schema = response_model.model_json_schema()
    grounded_prompt = (
        f"{prompt}\n\nReturn only one JSON object matching the required response schema. "
        "Do not add markdown or explanatory prose."
    )
    last_error: Exception | None = None
    for attempt in range(settings.llm_max_retries + 1):
        try:
            response = client.chat(
                model=settings.llm_model,
                messages=[{"role": "user", "content": grounded_prompt}],
                format=schema,
                stream=False,
                think=False,
                options={
                    "temperature": 0,
                    "seed": 0,
                    "num_ctx": settings.llm_context_tokens,
                    "num_predict": settings.llm_max_output_tokens,
                },
                keep_alive=settings.ollama_keep_alive,
            )
            content = response.message.content
            return response_model.model_validate_json(content)
        except Exception as exc:  # retry schema/transport failures with the same contract
            last_error = exc
            if attempt >= settings.llm_max_retries:
                break
    assert last_error is not None
    raise last_error


def embed_texts(texts: list[str], settings: Settings) -> list[list[float]]:
    """Embed text in bounded batches using the configured provider."""
    if not texts:
        return []
    vectors: list[list[float]] = []
    if settings.llm_provider == "openai":
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
        for start in range(0, len(texts), settings.embedding_batch_size):
            batch = texts[start : start + settings.embedding_batch_size]
            response = client.embeddings.create(
                model=settings.embedding_model,
                input=batch,
            )
            vectors.extend(
                item.embedding for item in sorted(response.data, key=lambda item: item.index)
            )
        return vectors

    client = _ollama_client(settings)
    for start in range(0, len(texts), settings.embedding_batch_size):
        batch = texts[start : start + settings.embedding_batch_size]
        response = client.embed(
            model=settings.embedding_model,
            input=batch,
            keep_alive=settings.ollama_keep_alive,
        )
        vectors.extend(response.embeddings)
    return vectors


def _available_ollama_models(settings: Settings) -> set[str]:
    response = _ollama_client(settings).list()
    names: set[str] = set()
    for model in response.models:
        name = getattr(model, "model", None)
        if name:
            names.add(name)
    return names


def _model_is_available(required: str, available: set[str]) -> bool:
    if required in available:
        return True
    if ":" not in required and f"{required}:latest" in available:
        return True
    return False


def backend_health(settings: Settings) -> tuple[str, bool]:
    """Return a diagnostic description without issuing a paid generation call."""
    try:
        settings.require_llm()
    except RuntimeError as exc:
        return str(exc), False

    if settings.llm_provider == "openai":
        return f"OpenAI configured; model={settings.llm_model}", True

    try:
        available = _available_ollama_models(settings)
    except Exception as exc:
        return (
            f"cannot reach {settings.ollama_base_url}: {type(exc).__name__}: {exc}. "
            "Install/start Ollama first.",
            False,
        )
    missing = [
        model
        for model in (settings.llm_model, settings.embedding_model)
        if not _model_is_available(model, available)
    ]
    if missing:
        pulls = " && ".join(f"ollama pull {model}" for model in missing)
        return f"missing local model(s): {', '.join(missing)}; run `{pulls}`", False
    return (
        f"Ollama ready at {settings.ollama_base_url}; "
        f"LLM={settings.llm_model}; embeddings={settings.embedding_model}",
        True,
    )


def ensure_backend(settings: Settings) -> None:
    """Fail before bulk scheduling when the selected backend is unavailable."""
    detail, healthy = backend_health(settings)
    if not healthy:
        raise RuntimeError(detail)


def pull_local_models(settings: Settings) -> list[str]:
    """Download configured Ollama models, returning the model names pulled."""
    if settings.llm_provider != "ollama":
        raise RuntimeError("Model pulling is available only when LLM_PROVIDER=ollama.")
    client = _ollama_client(settings)
    models = list(dict.fromkeys((settings.llm_model, settings.embedding_model)))
    for model in models:
        client.pull(model=model, stream=False)
    return models
