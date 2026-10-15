from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Tone = Literal["faithful", "formal", "literary", "academic", "colloquial"]


@dataclass(slots=True)
class TranslationRequest:
    text: str
    source_lang: str
    target_lang: str
    tone: Tone = "faithful"
    glossary: dict[str, str] = field(default_factory=dict)
    reference: str | None = None
    document_id: str | None = None


@dataclass(slots=True)
class SegmentResult:
    source: str
    raw_translation: str
    translation: str
    score: float
    passed: bool
    attempts: int = 1
    metrics: dict[str, float | None] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TranslationResult:
    text: str
    raw_text: str
    score: float
    passed: bool
    needs_review: bool
    source_lang: str
    target_lang: str
    tone: str
    segments: list[SegmentResult] = field(default_factory=list)
    metrics: dict[str, float | None] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)
    review_file: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
