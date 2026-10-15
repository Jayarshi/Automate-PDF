from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

try:
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel, Field
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("API dependencies are missing. Run: pip install -e '.[api]'") from exc

from .pipeline import TranslationPipeline
from .types import TranslationRequest


class TranslateBody(BaseModel):
    text: str = Field(min_length=1)
    source_lang: str
    target_lang: str
    tone: Literal["faithful", "formal", "literary", "academic", "colloquial"] = "faithful"
    glossary: dict[str, str] = Field(default_factory=dict)
    reference: str | None = None
    document_id: str | None = None


@lru_cache(maxsize=1)
def _pipeline() -> TranslationPipeline:
    path = os.getenv("TRANSLATION_CONFIG", "config/default.yaml")
    return TranslationPipeline.from_file(path)


app = FastAPI(title="Local NLLB Translation", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/translate")
def translate(body: TranslateBody) -> dict[str, object]:
    try:
        result = _pipeline().translate(
            TranslationRequest(
                text=body.text,
                source_lang=body.source_lang,
                target_lang=body.target_lang,
                tone=body.tone,  # type: ignore[arg-type]
                glossary=body.glossary,
                reference=body.reference,
                document_id=body.document_id,
            )
        )
        return result.to_dict()
    except (TypeError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def main() -> None:
    import uvicorn

    uvicorn.run("local_nllb.api:app", host="0.0.0.0", port=8080)
