from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(slots=True)
class SegmentConfig:
    backend: str = "regex"
    max_source_tokens: int = 384
    batch_size: int = 8
    spacy_model: str | None = None


@dataclass(slots=True)
class NLLBConfig:
    model_path: str = "models/nllb-200-distilled-600M-ct2-int8"
    tokenizer: str = "models/nllb-200-distilled-600M-hf"
    device: str = "auto"
    compute_type: str = "int8"
    beam_size: int = 4
    max_decoding_length: int = 512
    cpu_threads: int = 0


@dataclass(slots=True)
class PostEditConfig:
    enabled: bool = False
    provider: str = "ollama"
    model: str = "qwen2.5:7b-instruct"
    base_url: str = "http://127.0.0.1:11434"
    timeout_seconds: int = 120
    temperature: float = 0.1


@dataclass(slots=True)
class QualityConfig:
    threshold: float = 0.72
    retry_threshold: float = 0.72
    max_retries: int = 1
    comet_enabled: bool = False
    comet_model: str = "Unbabel/wmt22-cometkiwi-da"
    min_length_ratio: float = 0.35
    max_length_ratio: float = 3.0
    max_copy_ratio: float = 0.85
    review_path: str = "data/review/flagged.jsonl"


@dataclass(slots=True)
class AppConfig:
    segmentation: SegmentConfig = field(default_factory=SegmentConfig)
    nllb: NLLBConfig = field(default_factory=NLLBConfig)
    post_edit: PostEditConfig = field(default_factory=PostEditConfig)
    quality: QualityConfig = field(default_factory=QualityConfig)

    @classmethod
    def from_file(cls, path: str | Path) -> AppConfig:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Configuration not found: {path}")
        with path.open(encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
        if not isinstance(raw, dict):
            raise TypeError("Configuration root must be a mapping")
        post_value = raw.get("post_edit", {})
        if not isinstance(post_value, dict):
            raise TypeError("Configuration section 'post_edit' must be a mapping")
        post = dict(post_value)
        provider = str(post.get("provider", "ollama"))
        env_url = os.getenv("OLLAMA_BASE_URL" if provider == "ollama" else "VLLM_BASE_URL")
        if env_url:
            post["base_url"] = env_url
        return cls(
            segmentation=_section(SegmentConfig, raw, "segmentation"),
            nllb=_section(NLLBConfig, raw, "nllb"),
            post_edit=PostEditConfig(**post),
            quality=_section(QualityConfig, raw, "quality"),
        )


def _section(kind: type[Any], raw: dict[str, Any], name: str) -> Any:
    value = raw.get(name, {})
    if not isinstance(value, dict):
        raise TypeError(f"Configuration section '{name}' must be a mapping")
    return kind(**value)
