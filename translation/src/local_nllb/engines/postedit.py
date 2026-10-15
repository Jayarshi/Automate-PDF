from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Protocol

from ..config import PostEditConfig


class PostEditor(Protocol):
    def edit(
        self,
        source: str,
        translation: str,
        source_lang: str,
        target_lang: str,
        tone: str,
        glossary: dict[str, str],
        issues: list[str] | None = None,
    ) -> str: ...


class NoOpPostEditor:
    def edit(
        self,
        source: str,
        translation: str,
        source_lang: str,
        target_lang: str,
        tone: str,
        glossary: dict[str, str],
        issues: list[str] | None = None,
    ) -> str:
        return translation


class LocalLLMPostEditor:
    def __init__(self, config: PostEditConfig) -> None:
        self.config = config

    def edit(
        self,
        source: str,
        translation: str,
        source_lang: str,
        target_lang: str,
        tone: str,
        glossary: dict[str, str],
        issues: list[str] | None = None,
    ) -> str:
        prompt = _prompt(source, translation, source_lang, target_lang, tone, glossary, issues)
        provider = self.config.provider.lower()
        if provider == "ollama":
            payload = {
                "model": self.config.model,
                "stream": False,
                "format": "json",
                "options": {"temperature": self.config.temperature},
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            }
            response = self._post(self.config.base_url.rstrip("/") + "/api/chat", payload)
            content = response["message"]["content"]
        elif provider == "vllm":
            root = self.config.base_url.rstrip("/")
            url = (
                root + "/chat/completions"
                if root.endswith("/v1")
                else root + "/v1/chat/completions"
            )
            payload = {
                "model": self.config.model,
                "temperature": self.config.temperature,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            }
            response = self._post(url, payload)
            content = response["choices"][0]["message"]["content"]
        else:
            raise ValueError(f"Unknown post-edit provider: {self.config.provider}")
        try:
            edited = json.loads(content)["translation"]
        except (TypeError, KeyError, json.JSONDecodeError) as exc:
            raise RuntimeError("Local LLM returned an invalid JSON response") from exc
        if not isinstance(edited, str) or not edited.strip():
            raise RuntimeError("Local LLM returned an empty translation")
        return edited.strip()

    def _post(self, url: str, payload: dict[str, object]) -> dict[str, object]:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Local LLM request failed at {url}: {exc}") from exc


_SYSTEM_PROMPT = """You are a conservative translation post-editor. Preserve meaning, facts,
numbers, named entities, markup, and every placeholder such as <x0> exactly. Enforce the requested
glossary and tone without adding information. Never add explanations. Return only valid JSON in the
form {\"translation\": \"...\"}."""


def _prompt(
    source: str,
    translation: str,
    source_lang: str,
    target_lang: str,
    tone: str,
    glossary: dict[str, str],
    issues: list[str] | None,
) -> str:
    return json.dumps(
        {
            "task": "Polish the machine translation without changing its meaning.",
            "source_language": source_lang,
            "target_language": target_lang,
            "required_tone": tone,
            "source": source,
            "machine_translation": translation,
            "required_glossary": glossary,
            "quality_issues_to_fix": issues or [],
        },
        ensure_ascii=False,
    )
