"""Configuration, source-manifest parsing, and SQLite lifecycle helpers."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


SCHEMA_VERSION = "1"


class SourceMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    filename: str
    title: str = Field(min_length=1)
    author: str | None = None
    role: Literal["primary", "secondary", "tertiary", "other"]
    credibility_weight: float = Field(gt=0.0, le=1.0)
    independence_factor: float = Field(default=1.0, gt=0.0, le=1.0)
    description: str = ""
    bias_notes: str = ""

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        path = Path(value)
        if path.name != value or path.suffix.lower() != ".pdf":
            raise ValueError("filename must be a PDF basename, not a path")
        return value

    @property
    def effective_weight(self) -> float:
        return self.credibility_weight * self.independence_factor


class SourceManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
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


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
    )

    project_root: Path
    openai_api_key: str | None = None
    llm_model: str = "gpt-5.4-mini"
    llm_max_retries: int = Field(default=3, ge=0, le=10)
    llm_workers: int = Field(default=4, ge=1, le=32)
    embedding_model: str = "text-embedding-3-small"
    embedding_batch_size: int = Field(default=128, ge=1, le=2048)
    dedup_similarity_threshold: float = Field(default=0.82, ge=0.0, le=1.0)
    alignment_retrieval_threshold: float = Field(default=0.68, ge=0.0, le=1.0)
    alignment_top_k: int = Field(default=12, ge=1, le=100)
    chunk_size_chars: int = Field(default=9000, ge=1000)
    chunk_overlap_chars: int = Field(default=700, ge=0)
    enable_ocr: bool = False
    ocr_language: str = "eng"
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
                "OPENAI_API_KEY is required for this stage. Copy .env.example to .env "
                "and set the key."
            )


def load_sources(path: Path) -> SourceManifest:
    """Parse exactly one fenced YAML block from sources.md."""
    if not path.exists():
        raise FileNotFoundError(f"Source manifest not found: {path}")
    markdown = path.read_text(encoding="utf-8")
    blocks = re.findall(r"```(?:yaml|yml)\s*\n(.*?)```", markdown, flags=re.DOTALL | re.I)
    if len(blocks) != 1:
        raise ValueError(f"{path} must contain exactly one fenced YAML block")
    data = yaml.safe_load(blocks[0])
    if not isinstance(data, dict):
        raise ValueError("The sources.md YAML block must be a mapping")
    return SourceManifest.model_validate(data)


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS pipeline_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    author TEXT,
    role TEXT NOT NULL,
    credibility_weight REAL NOT NULL,
    independence_factor REAL NOT NULL,
    description TEXT NOT NULL,
    bias_notes TEXT NOT NULL,
    file_sha256 TEXT,
    page_count INTEGER,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    page_label TEXT,
    text TEXT NOT NULL,
    text_sha256 TEXT NOT NULL,
    used_ocr INTEGER NOT NULL DEFAULT 0,
    UNIQUE(source_id, page_number)
);

CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY,
    page_id INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    start_char INTEGER NOT NULL,
    end_char INTEGER NOT NULL,
    text TEXT NOT NULL,
    token_estimate INTEGER NOT NULL,
    parser_version TEXT NOT NULL,
    extracted_at TEXT,
    extraction_error TEXT
);

CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_id);

CREATE TABLE IF NOT EXISTS raw_facts (
    id TEXT PRIMARY KEY,
    chunk_id TEXT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    claim TEXT NOT NULL,
    subject TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object_text TEXT,
    time_expression TEXT,
    location TEXT,
    qualifiers_json TEXT NOT NULL,
    evidence_quote TEXT NOT NULL,
    page_number INTEGER NOT NULL,
    extraction_confidence REAL NOT NULL,
    extraction_model TEXT NOT NULL,
    embedding_json TEXT,
    embedding_model TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_raw_facts_source ON raw_facts(source_id);

CREATE TABLE IF NOT EXISTS canonical_facts (
    id TEXT PRIMARY KEY,
    canonical_claim TEXT NOT NULL,
    subject TEXT NOT NULL,
    time_expression TEXT,
    location TEXT,
    embedding_json TEXT,
    embedding_model TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fact_members (
    canonical_id TEXT NOT NULL REFERENCES canonical_facts(id) ON DELETE CASCADE,
    raw_fact_id TEXT NOT NULL REFERENCES raw_facts(id) ON DELETE CASCADE,
    similarity REAL NOT NULL,
    PRIMARY KEY(canonical_id, raw_fact_id),
    UNIQUE(raw_fact_id)
);

CREATE TABLE IF NOT EXISTS stances (
    canonical_id TEXT NOT NULL REFERENCES canonical_facts(id) ON DELETE CASCADE,
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    stance TEXT NOT NULL,
    support_strength REAL NOT NULL,
    contradiction_strength REAL NOT NULL,
    confidence REAL NOT NULL,
    support_evidence_ids_json TEXT NOT NULL,
    contradiction_evidence_ids_json TEXT NOT NULL,
    rationale TEXT NOT NULL,
    alignment_model TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(canonical_id, source_id)
);

CREATE TABLE IF NOT EXISTS scores (
    canonical_id TEXT PRIMARY KEY REFERENCES canonical_facts(id) ON DELETE CASCADE,
    believability_score REAL NOT NULL,
    support_mass REAL NOT NULL,
    contradiction_mass REAL NOT NULL,
    total_source_weight REAL NOT NULL,
    evidence_coverage REAL NOT NULL,
    conflict_index REAL NOT NULL,
    grade TEXT NOT NULL,
    formula_version TEXT NOT NULL,
    scored_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def connect_db(settings: Settings) -> sqlite3.Connection:
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_path, timeout=60.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def initialize_database(settings: Settings) -> None:
    settings.books_dir.mkdir(parents=True, exist_ok=True)
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    with connect_db(settings) as conn:
        conn.executescript(SCHEMA_SQL)
        version = conn.execute(
            "SELECT value FROM pipeline_meta WHERE key = 'schema_version'"
        ).fetchone()
        if version and version["value"] != SCHEMA_VERSION:
            raise RuntimeError(
                f"Database schema is {version['value']}, but code expects {SCHEMA_VERSION}."
            )
        conn.execute(
            "INSERT OR REPLACE INTO pipeline_meta(key, value) VALUES('schema_version', ?)",
            (SCHEMA_VERSION,),
        )


def sync_manifest(conn: sqlite3.Connection, manifest: SourceManifest) -> None:
    expected_ids = {source.id for source in manifest.sources}
    existing_ids = {row["id"] for row in conn.execute("SELECT id FROM sources")}
    removed = existing_ids - expected_ids
    if removed:
        placeholders = ",".join("?" for _ in removed)
        conn.execute("DELETE FROM canonical_facts")
        conn.execute(f"DELETE FROM sources WHERE id IN ({placeholders})", tuple(removed))
    for source in manifest.sources:
        conn.execute(
            """
            INSERT INTO sources(
                id, filename, title, author, role, credibility_weight,
                independence_factor, description, bias_notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                filename=excluded.filename, title=excluded.title, author=excluded.author,
                role=excluded.role, credibility_weight=excluded.credibility_weight,
                independence_factor=excluded.independence_factor,
                description=excluded.description, bias_notes=excluded.bias_notes,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                source.id,
                source.filename,
                source.title,
                source.author,
                source.role,
                source.credibility_weight,
                source.independence_factor,
                source.description,
                source.bias_notes,
            ),
        )


def clear_from_stage(conn: sqlite3.Connection, stage: str) -> None:
    """Clear a stage and all dependent products while retaining earlier work."""
    if stage == "parse":
        conn.execute("DELETE FROM canonical_facts")
        conn.execute("DELETE FROM pages")
        conn.execute("UPDATE sources SET file_sha256=NULL, page_count=NULL")
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
