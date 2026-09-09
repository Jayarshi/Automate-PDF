"""Typed contracts used for every LLM response."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ExtractedFact(StrictModel):
    claim: str = Field(
        min_length=8,
        description="One self-contained atomic proposition, understandable out of context.",
    )
    subject: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    object: str | None = None
    time_expression: str | None = None
    location: str | None = None
    qualifiers: list[str] = Field(default_factory=list)
    evidence_quote: str = Field(
        min_length=8,
        description="A verbatim substring copied from the supplied page text.",
    )
    confidence: float = Field(ge=0.0, le=1.0)


class FactExtraction(StrictModel):
    facts: list[ExtractedFact] = Field(default_factory=list)


class CanonicalGroup(StrictModel):
    raw_fact_ids: list[str] = Field(min_length=1)
    canonical_claim: str = Field(min_length=8)
    subject: str = Field(min_length=1)
    time_expression: str | None = None
    location: str | None = None


class DeduplicationResult(StrictModel):
    groups: list[CanonicalGroup] = Field(min_length=1)


class Stance(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    MIXED = "mixed"
    SILENT = "silent"


class StanceDecision(StrictModel):
    stance: Stance
    support_evidence_ids: list[str] = Field(default_factory=list)
    contradiction_evidence_ids: list[str] = Field(default_factory=list)
    support_strength: float = Field(default=0.0, ge=0.0, le=1.0)
    contradiction_strength: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=3, max_length=1000)

    @model_validator(mode="after")
    def validate_stance_evidence(self) -> "StanceDecision":
        if self.stance == Stance.SILENT:
            if self.support_evidence_ids or self.contradiction_evidence_ids:
                raise ValueError("silent decisions cannot cite evidence")
            if self.support_strength or self.contradiction_strength:
                raise ValueError("silent decisions must have zero strengths")
        elif self.stance == Stance.SUPPORTS:
            if not self.support_evidence_ids or self.support_strength <= 0:
                raise ValueError("supports requires supporting evidence and strength")
            if self.contradiction_evidence_ids or self.contradiction_strength:
                raise ValueError("supports cannot contain contradictory evidence")
        elif self.stance == Stance.CONTRADICTS:
            if not self.contradiction_evidence_ids or self.contradiction_strength <= 0:
                raise ValueError("contradicts requires contradictory evidence and strength")
            if self.support_evidence_ids or self.support_strength:
                raise ValueError("contradicts cannot contain supporting evidence")
        elif self.stance == Stance.MIXED:
            if not self.support_evidence_ids or not self.contradiction_evidence_ids:
                raise ValueError("mixed requires both kinds of evidence")
            if self.support_strength <= 0 or self.contradiction_strength <= 0:
                raise ValueError("mixed requires both strengths")
        return self
