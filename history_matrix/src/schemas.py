"""Strict typed contracts for extraction, canonicalization, and alignment."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ClaimType(StrEnum):
    EVENT = "event"
    OBSERVABLE_ACTION = "observable_action"
    DOCUMENTED_STATEMENT = "documented_statement"
    VOTE = "vote"
    APPOINTMENT = "appointment"
    INSTITUTIONAL_CHANGE = "institutional_change"
    NUMERICAL_CLAIM = "numerical_claim"
    REPORTED_SPEECH = "reported_speech"
    MOTIVE_CLAIM = "motive_claim"
    INTERPRETATION = "interpretation"
    CAUSAL_INTERPRETATION = "causal_interpretation"
    OTHER = "other"


class EvidenceClass(StrEnum):
    E1 = "E1_DIRECT_DOCUMENT"
    E2 = "E2_CONTEMPORARY_EYEWITNESS"
    E3 = "E3_PARTICIPANT_RETROSPECTIVE"
    E4 = "E4_SCHOLARLY_RECONSTRUCTION"
    E5 = "E5_DERIVATIVE_INTERPRETATION"
    E6 = "E6_REPORTED_SPEECH"
    E7 = "E7_UNKNOWN"


class FirsthandStatus(StrEnum):
    DIRECT_DOCUMENT = "direct_document"
    DIRECT_OBSERVATION = "direct_observation"
    PARTICIPANT_RETROSPECTIVE = "participant_retrospective"
    SCHOLARLY_RECONSTRUCTION = "scholarly_reconstruction"
    REPORTED_SPEECH = "reported_speech"
    SECONDARY_INTERPRETATION = "secondary_interpretation"
    UNKNOWN = "unknown"


class ExtractedFact(StrictModel):
    claim: str = Field(
        min_length=8,
        description="One self-contained atomic proposition preserving attribution and uncertainty.",
    )
    event: str | None = Field(default=None, description="Normalized event label when identifiable.")
    taxonomy_path: str | None = Field(
        default=None, description="Best CH2_1917 taxonomy path, or null when uncertain."
    )
    claim_type: ClaimType
    evidence_class: EvidenceClass
    firsthand_status: FirsthandStatus
    subject: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    object: str | None = None
    date_source: str | None = Field(
        default=None, description="Date exactly as represented by the source."
    )
    date_normalized: str | None = Field(
        default=None, description="ISO date or interval only when normalization is justified."
    )
    calendar: str | None = Field(
        default=None, description="Old Style, New Style/Gregorian, ambiguous, or null."
    )
    location: str | None = None
    chapter_section: str | None = None
    qualifiers: list[str] = Field(default_factory=list)
    reported_value: str | None = None
    unit: str | None = None
    scope: str | None = None
    is_negative_claim: bool = False
    evidence_quote: str = Field(
        min_length=8,
        description="A verbatim substring copied from the supplied page text.",
    )
    translation_status: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)


class FactExtraction(StrictModel):
    facts: list[ExtractedFact] = Field(default_factory=list)


class CanonicalGroup(StrictModel):
    raw_fact_ids: list[str] = Field(min_length=1)
    canonical_claim: str = Field(min_length=8)
    event: str | None = None
    taxonomy_path: str | None = None
    claim_type: ClaimType
    subject: str = Field(min_length=1)
    date_source: str | None = None
    date_normalized: str | None = None
    calendar: str | None = None
    location: str | None = None


class DeduplicationResult(StrictModel):
    groups: list[CanonicalGroup] = Field(min_length=1)


class Coverage(StrEnum):
    NOT_COVERED = "not_covered"
    COVERED = "covered"
    COVERED_BUT_SILENT = "covered_but_silent"


class Stance(StrEnum):
    EXPLICIT_SUPPORT = "explicit_support"
    IMPLICIT_SUPPORT = "implicit_support"
    EXPLICIT_CONTRADICTION = "explicit_contradiction"
    MIXED = "mixed"
    SILENT = "silent"


class ContradictionType(StrEnum):
    D1 = "D1_FACTUAL"
    D2 = "D2_CHRONOLOGY"
    D3 = "D3_SCOPE"
    D4 = "D4_TERMINOLOGY"
    D5 = "D5_PERSPECTIVE"
    D6 = "D6_INTERPRETATION"
    D7 = "D7_NUMERICAL"
    D8 = "D8_ACCESS_LIMITATION"
    D9 = "D9_TRANSLATION_EDITION"


class StanceDecision(StrictModel):
    coverage: Coverage
    stance: Stance
    support_evidence_ids: list[str] = Field(default_factory=list)
    contradiction_evidence_ids: list[str] = Field(default_factory=list)
    contradiction_type: ContradictionType | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=3, max_length=1500)
    chronology_notes: str | None = None
    scope_notes: str | None = None

    @model_validator(mode="after")
    def validate_stance_evidence(self) -> "StanceDecision":
        if self.stance == Stance.SILENT:
            if self.support_evidence_ids or self.contradiction_evidence_ids:
                raise ValueError("silent decisions cannot cite stance evidence")
            if self.contradiction_type is not None:
                raise ValueError("silent decisions cannot have a contradiction type")
            if self.coverage == Coverage.COVERED:
                self.coverage = Coverage.COVERED_BUT_SILENT
        elif self.stance in {Stance.EXPLICIT_SUPPORT, Stance.IMPLICIT_SUPPORT}:
            if not self.support_evidence_ids:
                raise ValueError("support requires supporting evidence")
            if self.contradiction_evidence_ids or self.contradiction_type is not None:
                raise ValueError("support cannot contain contradiction evidence")
            self.coverage = Coverage.COVERED
        elif self.stance == Stance.EXPLICIT_CONTRADICTION:
            if not self.contradiction_evidence_ids or self.contradiction_type is None:
                raise ValueError("contradiction requires evidence and a disagreement type")
            if self.support_evidence_ids:
                raise ValueError("contradiction cannot contain support evidence")
            self.coverage = Coverage.COVERED
        elif self.stance == Stance.MIXED:
            if not self.support_evidence_ids or not self.contradiction_evidence_ids:
                raise ValueError("mixed requires support and contradiction evidence")
            if self.contradiction_type is None:
                raise ValueError("mixed requires a contradiction type")
            self.coverage = Coverage.COVERED
        return self
