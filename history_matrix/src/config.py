"""Typed research policy, source registry, and SQLite lifecycle helpers."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .schemas import ContradictionType, EvidenceClass, Stance


SCHEMA_VERSION = "2"
POLICY_START = "<!-- HISTORY_MATRIX_CONFIG_START -->"
POLICY_END = "<!-- HISTORY_MATRIX_CONFIG_END -->"


class DimensionWeights(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_authority: float = Field(ge=0, le=1)
    firsthand_access: float = Field(ge=0, le=1)
    temporal_proximity: float = Field(ge=0, le=1)
    documentary_basis: float = Field(ge=0, le=1)
    independence: float = Field(ge=0, le=1)
    specialist_expertise: float = Field(ge=0, le=1)
    bias_safety: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> "DimensionWeights":
        if not math.isclose(sum(self.model_dump().values()), 1.0, abs_tol=1e-8):
            raise ValueError("scoring.dimension_weights must sum to 1.0")
        return self


class TierThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meaningful_contribution: float = Field(gt=0)
    serious_contradiction: float = Field(gt=0)
    established_support_mass: float = Field(gt=0)
    established_independent_clusters: int = Field(ge=1)
    probable_support_mass: float = Field(gt=0)
    probable_independent_clusters: int = Field(ge=1)
    plausible_support_mass: float = Field(gt=0)

    @model_validator(mode="after")
    def validate_tier_order(self) -> "TierThresholds":
        if not (
            self.established_support_mass
            >= self.probable_support_mass
            >= self.plausible_support_mass
        ):
            raise ValueError(
                "support thresholds must descend: established >= probable >= plausible"
            )
        if self.established_independent_clusters < self.probable_independent_clusters:
            raise ValueError(
                "established_independent_clusters cannot be lower than probable"
            )
        return self


class ScoringPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimension_weights: DimensionWeights
    evidence_class_multipliers: dict[EvidenceClass, float]
    stance_values: dict[Stance, float]
    contradiction_penalty_types: list[ContradictionType]
    tier_thresholds: TierThresholds

    @model_validator(mode="after")
    def validate_complete_maps(self) -> "ScoringPolicy":
        if set(self.evidence_class_multipliers) != set(EvidenceClass):
            raise ValueError("Every evidence class needs a multiplier")
        if set(self.stance_values) != set(Stance):
            raise ValueError("Every stance needs a numerical value")
        if any(not 0 <= value <= 1 for value in self.evidence_class_multipliers.values()):
            raise ValueError("Evidence-class multipliers must be between 0 and 1")
        if self.stance_values[Stance.SILENT] != 0:
            raise ValueError("Silence must have a stance value of zero")
        if self.stance_values[Stance.MIXED] != 0:
            raise ValueError("Mixed must remain categorical and have a stored value of zero")
        explicit = self.stance_values[Stance.EXPLICIT_SUPPORT]
        implicit = self.stance_values[Stance.IMPLICIT_SUPPORT]
        contradiction = self.stance_values[Stance.EXPLICIT_CONTRADICTION]
        if explicit <= 0 or not 0 <= implicit <= explicit or contradiction >= 0:
            raise ValueError(
                "Stances require explicit>0, 0<=implicit<=explicit, and contradiction<0"
            )
        if set(self.contradiction_penalty_types) - {ContradictionType.D1}:
            raise ValueError("Only D1 factual incompatibility may receive an automatic penalty")
        return self


class ProjectPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1)
    taxonomy_root: str = Field(min_length=1)


class SourceMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    filename: str
    title: str = Field(min_length=1)
    author: str | None = None
    role: Literal[
        "primary", "participant", "eyewitness", "documentary_collection",
        "secondary", "tertiary", "other",
    ]
    evidence_class_default: EvidenceClass
    independence_cluster_id: str = Field(min_length=1)
    source_authority: float = Field(ge=0, le=1)
    firsthand_access: float = Field(ge=0, le=1)
    temporal_proximity: float = Field(ge=0, le=1)
    documentary_basis: float = Field(ge=0, le=1)
    independence: float = Field(ge=0, le=1)
    specialist_expertise: float = Field(ge=0, le=1)
    political_bias_risk: float = Field(ge=0, le=1)
    description: str = ""
    bias_notes: str = ""

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        path = Path(value)
        if path.name != value or path.suffix.lower() != ".pdf":
            raise ValueError("filename must be a PDF basename, not a path")
        return value

    def quality(self, weights: DimensionWeights) -> float:
        """Weighted geometric quality; bias enters as safety=(1-risk)."""
        dimensions = {
            "source_authority": self.source_authority,
            "firsthand_access": self.firsthand_access,
            "temporal_proximity": self.temporal_proximity,
            "documentary_basis": self.documentary_basis,
            "independence": self.independence,
            "specialist_expertise": self.specialist_expertise,
            "bias_safety": 1.0 - self.political_bias_risk,
        }
        weighted_logs = 0.0
        for name, value in dimensions.items():
            weight = getattr(weights, name)
            if weight == 0:
                continue
            if value == 0:
                return 0.0
            weighted_logs += weight * math.log(value)
        return math.exp(weighted_logs)


class SourceManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[2]
    project: ProjectPolicy
    scoring: ScoringPolicy
    presets: dict[str, object] = Field(default_factory=dict, exclude=True)
    sources: list[SourceMetadata] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_values(self) -> "SourceManifest":
        ids = [item.id.casefold() for item in self.sources]
        files = [item.filename.casefold() for item in self.sources]
        if len(ids) != len(set(ids)):
            raise ValueError("source ids must be unique")
        if len(files) != len(set(files)):
            raise ValueError("source filenames must be unique")
        return self

    def stable_hash(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", case_sensitive=False, extra="ignore")

    project_root: Path
    openai_api_key: str | None = None
    llm_model: str = "gpt-5.4-mini"
    llm_max_retries: int = Field(default=3, ge=0, le=10)
    llm_workers: int = Field(default=4, ge=1, le=32)
    embedding_model: str = "text-embedding-3-small"
    embedding_batch_size: int = Field(default=128, ge=1, le=2048)
    dedup_similarity_threshold: float = Field(default=0.82, ge=0, le=1)
    alignment_retrieval_threshold: float = Field(default=0.62, ge=0, le=1)
    alignment_top_k: int = Field(default=16, ge=1, le=100)
    chunk_size_chars: int = Field(default=9000, ge=1000)
    chunk_overlap_chars: int = Field(default=700, ge=0)
    enable_ocr: bool = True
    ocr_language: str = "eng"
    tessdata_prefix: Path | None = None
    min_page_text_chars: int = Field(default=40, ge=0)
    fail_fast: bool = False

    @model_validator(mode="after")
    def validate_chunk_overlap(self) -> "Settings":
        if self.chunk_overlap_chars >= self.chunk_size_chars:
            raise ValueError("CHUNK_OVERLAP_CHARS must be smaller than CHUNK_SIZE_CHARS")
        return self

    @property
    def books_dir(self) -> Path:
        return self.project_root / "books"

    @property
    def output_dir(self) -> Path:
        return self.project_root / "output"

    @property
    def db_path(self) -> Path:
        return self.project_root / "data" / "facts.db"

    @property
    def sources_path(self) -> Path:
        return self.project_root / "sources.md"

    @classmethod
    def load(cls, project_root: Path | None = None) -> "Settings":
        root = (project_root or Path(__file__).resolve().parents[1]).resolve()
        load_dotenv(root / ".env", override=False)
        return cls(project_root=root)

    def require_api_key(self) -> None:
        if not self.openai_api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is blank. Set it in "
                f"{self.project_root / '.env'} and run `python main.py doctor` again."
            )


def load_sources(path: Path) -> SourceManifest:
    """Parse the one explicitly marked executable YAML policy from sources.md."""
    if not path.exists():
        raise FileNotFoundError(f"Source protocol not found: {path}")
    markdown = path.read_text(encoding="utf-8")
    pattern = re.escape(POLICY_START) + r"\s*```ya?ml\s*\n(.*?)```\s*" + re.escape(POLICY_END)
    match = re.search(pattern, markdown, flags=re.DOTALL | re.I)
    if not match:
        raise ValueError(
            f"{path} must contain one YAML block between {POLICY_START} and {POLICY_END}"
        )
    data = yaml.safe_load(match.group(1))
    if not isinstance(data, dict):
        raise ValueError("The machine-readable sources.md policy must be a mapping")
    return SourceManifest.model_validate(data)


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS pipeline_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY, filename TEXT NOT NULL UNIQUE, title TEXT NOT NULL, author TEXT,
    role TEXT NOT NULL, credibility_weight REAL NOT NULL, independence_factor REAL NOT NULL,
    description TEXT NOT NULL, bias_notes TEXT NOT NULL, file_sha256 TEXT, page_count INTEGER,
    source_authority REAL NOT NULL DEFAULT 0.5, firsthand_access REAL NOT NULL DEFAULT 0.5,
    temporal_proximity REAL NOT NULL DEFAULT 0.5, documentary_basis REAL NOT NULL DEFAULT 0.5,
    independence REAL NOT NULL DEFAULT 0.5, specialist_expertise REAL NOT NULL DEFAULT 0.5,
    political_bias_risk REAL NOT NULL DEFAULT 0.5,
    evidence_class_default TEXT NOT NULL DEFAULT 'E7_UNKNOWN',
    independence_cluster_id TEXT NOT NULL DEFAULT 'UNKNOWN', pdf_metadata_json TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL, page_label TEXT, text TEXT NOT NULL,
    text_sha256 TEXT NOT NULL, used_ocr INTEGER NOT NULL DEFAULT 0,
    UNIQUE(source_id, page_number)
);

CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY, page_id INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL, start_char INTEGER NOT NULL, end_char INTEGER NOT NULL,
    text TEXT NOT NULL, token_estimate INTEGER NOT NULL, parser_version TEXT NOT NULL,
    extracted_at TEXT, extraction_error TEXT
);
CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_id);

CREATE TABLE IF NOT EXISTS raw_facts (
    id TEXT PRIMARY KEY, chunk_id TEXT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    claim TEXT NOT NULL, subject TEXT NOT NULL, predicate TEXT NOT NULL, object_text TEXT,
    time_expression TEXT, location TEXT, qualifiers_json TEXT NOT NULL,
    evidence_quote TEXT NOT NULL, page_number INTEGER NOT NULL,
    extraction_confidence REAL NOT NULL, extraction_model TEXT NOT NULL,
    embedding_json TEXT, embedding_model TEXT,
    event TEXT, taxonomy_path TEXT, claim_type TEXT NOT NULL DEFAULT 'other',
    evidence_class TEXT NOT NULL DEFAULT 'E7_UNKNOWN',
    firsthand_status TEXT NOT NULL DEFAULT 'unknown', date_source TEXT,
    date_normalized TEXT, calendar TEXT, chapter_section TEXT, reported_value TEXT,
    unit TEXT, scope TEXT, is_negative_claim INTEGER NOT NULL DEFAULT 0,
    translation_status TEXT, quote_verified INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_raw_facts_source ON raw_facts(source_id);

CREATE TABLE IF NOT EXISTS canonical_facts (
    id TEXT PRIMARY KEY, canonical_claim TEXT NOT NULL, subject TEXT NOT NULL,
    time_expression TEXT, location TEXT, embedding_json TEXT, embedding_model TEXT,
    event TEXT, taxonomy_path TEXT, claim_type TEXT NOT NULL DEFAULT 'other',
    date_source TEXT, date_normalized TEXT, calendar TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fact_members (
    canonical_id TEXT NOT NULL REFERENCES canonical_facts(id) ON DELETE CASCADE,
    raw_fact_id TEXT NOT NULL REFERENCES raw_facts(id) ON DELETE CASCADE,
    similarity REAL NOT NULL, PRIMARY KEY(canonical_id, raw_fact_id), UNIQUE(raw_fact_id)
);

CREATE TABLE IF NOT EXISTS stances (
    canonical_id TEXT NOT NULL REFERENCES canonical_facts(id) ON DELETE CASCADE,
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    stance TEXT NOT NULL, support_strength REAL NOT NULL, contradiction_strength REAL NOT NULL,
    confidence REAL NOT NULL, support_evidence_ids_json TEXT NOT NULL,
    contradiction_evidence_ids_json TEXT NOT NULL, rationale TEXT NOT NULL,
    alignment_model TEXT NOT NULL, coverage TEXT NOT NULL DEFAULT 'not_covered',
    contradiction_type TEXT, chronology_notes TEXT, scope_notes TEXT,
    stance_value REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(canonical_id, source_id)
);

CREATE TABLE IF NOT EXISTS scores (
    canonical_id TEXT PRIMARY KEY REFERENCES canonical_facts(id) ON DELETE CASCADE,
    believability_score REAL NOT NULL, support_mass REAL NOT NULL,
    contradiction_mass REAL NOT NULL, total_source_weight REAL NOT NULL,
    evidence_coverage REAL NOT NULL, conflict_index REAL NOT NULL, grade TEXT NOT NULL,
    formula_version TEXT NOT NULL, research_index REAL NOT NULL DEFAULT 0,
    evidence_strength REAL NOT NULL DEFAULT 0,
    independent_support_count INTEGER NOT NULL DEFAULT 0,
    dependent_support_count INTEGER NOT NULL DEFAULT 0,
    primary_document_count INTEGER NOT NULL DEFAULT 0,
    eyewitness_count INTEGER NOT NULL DEFAULT 0,
    scholarly_reconstruction_count INTEGER NOT NULL DEFAULT 0,
    serious_contradiction_count INTEGER NOT NULL DEFAULT 0,
    confidence_tier TEXT NOT NULL DEFAULT 'Tier 5 — Unsupported / speculative',
    scored_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


MIGRATION_COLUMNS: dict[str, dict[str, str]] = {
    "sources": {
        "source_authority": "REAL NOT NULL DEFAULT 0.5",
        "firsthand_access": "REAL NOT NULL DEFAULT 0.5",
        "temporal_proximity": "REAL NOT NULL DEFAULT 0.5",
        "documentary_basis": "REAL NOT NULL DEFAULT 0.5",
        "independence": "REAL NOT NULL DEFAULT 0.5",
        "specialist_expertise": "REAL NOT NULL DEFAULT 0.5",
        "political_bias_risk": "REAL NOT NULL DEFAULT 0.5",
        "evidence_class_default": "TEXT NOT NULL DEFAULT 'E7_UNKNOWN'",
        "independence_cluster_id": "TEXT NOT NULL DEFAULT 'UNKNOWN'",
        "pdf_metadata_json": "TEXT",
    },
    "raw_facts": {
        "event": "TEXT", "taxonomy_path": "TEXT", "claim_type": "TEXT NOT NULL DEFAULT 'other'",
        "evidence_class": "TEXT NOT NULL DEFAULT 'E7_UNKNOWN'",
        "firsthand_status": "TEXT NOT NULL DEFAULT 'unknown'", "date_source": "TEXT",
        "date_normalized": "TEXT", "calendar": "TEXT", "chapter_section": "TEXT",
        "reported_value": "TEXT", "unit": "TEXT", "scope": "TEXT",
        "is_negative_claim": "INTEGER NOT NULL DEFAULT 0", "translation_status": "TEXT",
        "quote_verified": "INTEGER NOT NULL DEFAULT 1",
    },
    "canonical_facts": {
        "event": "TEXT", "taxonomy_path": "TEXT", "claim_type": "TEXT NOT NULL DEFAULT 'other'",
        "date_source": "TEXT", "date_normalized": "TEXT", "calendar": "TEXT",
    },
    "stances": {
        "coverage": "TEXT NOT NULL DEFAULT 'not_covered'", "contradiction_type": "TEXT",
        "chronology_notes": "TEXT", "scope_notes": "TEXT",
        "stance_value": "REAL NOT NULL DEFAULT 0",
    },
    "scores": {
        "research_index": "REAL NOT NULL DEFAULT 0", "evidence_strength": "REAL NOT NULL DEFAULT 0",
        "independent_support_count": "INTEGER NOT NULL DEFAULT 0",
        "dependent_support_count": "INTEGER NOT NULL DEFAULT 0",
        "primary_document_count": "INTEGER NOT NULL DEFAULT 0",
        "eyewitness_count": "INTEGER NOT NULL DEFAULT 0",
        "scholarly_reconstruction_count": "INTEGER NOT NULL DEFAULT 0",
        "serious_contradiction_count": "INTEGER NOT NULL DEFAULT 0",
        "confidence_tier": "TEXT NOT NULL DEFAULT 'Tier 5 — Unsupported / speculative'",
    },
}


def connect_db(settings: Settings) -> sqlite3.Connection:
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_path, timeout=60.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def _migrate_columns(conn: sqlite3.Connection) -> None:
    for table, columns in MIGRATION_COLUMNS.items():
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        for name, definition in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def initialize_database(settings: Settings) -> None:
    settings.books_dir.mkdir(parents=True, exist_ok=True)
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    with connect_db(settings) as conn:
        conn.executescript(SCHEMA_SQL)
        _migrate_columns(conn)
        conn.execute(
            "INSERT OR REPLACE INTO pipeline_meta(key, value) VALUES('schema_version', ?)",
            (SCHEMA_VERSION,),
        )


def sync_manifest(conn: sqlite3.Connection, manifest: SourceManifest) -> None:
    old_hash_row = conn.execute(
        "SELECT value FROM pipeline_meta WHERE key='source_policy_hash'"
    ).fetchone()
    new_hash = manifest.stable_hash()
    policy_changed = old_hash_row is None or old_hash_row["value"] != new_hash

    expected_ids = {source.id for source in manifest.sources}
    existing_ids = {row["id"] for row in conn.execute("SELECT id FROM sources")}
    removed = existing_ids - expected_ids
    if removed:
        placeholders = ",".join("?" for _ in removed)
        conn.execute("DELETE FROM canonical_facts")
        conn.execute(f"DELETE FROM sources WHERE id IN ({placeholders})", tuple(removed))

    for source in manifest.sources:
        quality = source.quality(manifest.scoring.dimension_weights)
        conn.execute(
            """
            INSERT INTO sources(
                id, filename, title, author, role, credibility_weight, independence_factor,
                description, bias_notes, source_authority, firsthand_access,
                temporal_proximity, documentary_basis, independence, specialist_expertise,
                political_bias_risk, evidence_class_default, independence_cluster_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                filename=excluded.filename, title=excluded.title, author=excluded.author,
                role=excluded.role, credibility_weight=excluded.credibility_weight,
                independence_factor=excluded.independence_factor,
                description=excluded.description, bias_notes=excluded.bias_notes,
                source_authority=excluded.source_authority,
                firsthand_access=excluded.firsthand_access,
                temporal_proximity=excluded.temporal_proximity,
                documentary_basis=excluded.documentary_basis,
                independence=excluded.independence,
                specialist_expertise=excluded.specialist_expertise,
                political_bias_risk=excluded.political_bias_risk,
                evidence_class_default=excluded.evidence_class_default,
                independence_cluster_id=excluded.independence_cluster_id,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                source.id, source.filename, source.title, source.author, source.role,
                quality, source.independence, source.description, source.bias_notes,
                source.source_authority, source.firsthand_access, source.temporal_proximity,
                source.documentary_basis, source.independence, source.specialist_expertise,
                source.political_bias_risk, source.evidence_class_default.value,
                source.independence_cluster_id,
            ),
        )
    # Policy/source-weight changes only invalidate deterministic scoring. Parsed
    # pages and costly LLM extraction remain valid; callers can use extract
    # --force when changing the extraction ontology itself.
    if policy_changed or removed or expected_ids != existing_ids:
        conn.execute("DELETE FROM scores")
    conn.execute(
        "INSERT OR REPLACE INTO pipeline_meta(key, value) VALUES('source_policy_hash', ?)",
        (new_hash,),
    )


def clear_from_stage(conn: sqlite3.Connection, stage: str) -> None:
    """Clear a stage and every dependent product while retaining earlier work."""
    if stage == "parse":
        conn.execute("DELETE FROM canonical_facts")
        conn.execute("DELETE FROM pages")
        conn.execute("UPDATE sources SET file_sha256=NULL, page_count=NULL, pdf_metadata_json=NULL")
    elif stage == "extract":
        conn.execute("DELETE FROM canonical_facts")
        conn.execute("DELETE FROM raw_facts")
        conn.execute("UPDATE chunks SET extracted_at=NULL, extraction_error=NULL")
    elif stage == "deduplicate":
        conn.execute("DELETE FROM canonical_facts")
    elif stage == "align":
        conn.execute("DELETE FROM stances")
        conn.execute("DELETE FROM scores")
    elif stage == "score":
        conn.execute("DELETE FROM scores")
    else:
        raise ValueError(f"Unknown pipeline stage: {stage}")
