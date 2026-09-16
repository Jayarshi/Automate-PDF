"""Atomic, quote-grounded fact extraction over individual page chunks."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import instructor

from .config import Settings, clear_from_stage
from .schemas import FactExtraction


EXTRACTION_PROMPT = """You extract auditable historical assertions from one PDF page chunk.

Rules:
1. Extract facts, source reports, and interpretations separately. Never convert an
   author's argument, reported speech, or inferred motive into an observed fact.
2. Make each assertion atomic but retain chronology, scope, attribution, and negation.
3. Classify claim_type and firsthand_status from this passage, not from author prestige.
4. Evidence classes: E1 direct document; E2 contemporary direct observation; E3
   participant retrospective; E4 scholarly reconstruction; E5 derivative interpretation;
   E6 reported speech/hearsay; E7 genuinely unknown. The source default is guidance only.
5. Preserve the source's date exactly in date_source. Normalize separately only when the
   calendar conversion is justified. Never silently replace Old Style with Gregorian.
6. For numerical claims retain value, unit, date, and scope. Do not average values.
7. A negative or motive claim must be explicitly marked and conservatively worded.
8. evidence_quote MUST be copied verbatim from PAGE_TEXT and directly ground the claim.
9. Do not use outside knowledge. If taxonomy placement is uncertain, return null.
10. If there is no historical assertion, return an empty facts list.

SOURCE: {source_title}
SOURCE_ID: {source_id}
DEFAULT_EVIDENCE_CLASS: {default_evidence_class}
TAXONOMY_ROOT: CH2_1917
PDF_PAGE: {page_number}
PAGE_TEXT:
---
{text}
---
"""


@dataclass(slots=True)
class ExtractionStats:
    processed_chunks: int = 0
    skipped_chunks: int = 0
    facts_inserted: int = 0
    rejected_quotes: int = 0
    failed_chunks: int = 0


_thread_state = threading.local()


def _client(settings: Settings):
    client = getattr(_thread_state, "instructor_client", None)
    if client is None:
        client = instructor.from_provider(
            f"openai/{settings.llm_model}",
            mode=instructor.Mode.RESPONSES_TOOLS,
            api_key=settings.openai_api_key,
        )
        _thread_state.instructor_client = client
    return client


def _normalized_with_map(text: str) -> tuple[str, list[int]]:
    """Normalize PDF whitespace while retaining offsets into the original string."""
    normalized: list[str] = []
    positions: list[int] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\u00ad":
            index += 1
            continue
        if (
            char == "-"
            and index + 1 < len(text)
            and text[index + 1] in "\r\n"
            and index > 0
            and text[index - 1].isalpha()
        ):
            lookahead = index + 1
            while lookahead < len(text) and text[lookahead].isspace():
                lookahead += 1
            if lookahead < len(text) and text[lookahead].isalpha():
                index = lookahead
                continue
        if char.isspace():
            if normalized and normalized[-1] != " ":
                normalized.append(" ")
                positions.append(index)
        else:
            normalized.append(char)
            positions.append(index)
        index += 1
    return "".join(normalized).strip(), positions


def resolve_exact_quote(quote: str, page_text: str) -> str | None:
    """Return the exact page substring corresponding to an LLM-provided quotation."""
    quote = quote.strip()
    if quote in page_text:
        return quote
    normalized_page, offsets = _normalized_with_map(page_text)
    normalized_quote, _ = _normalized_with_map(quote)
    start = normalized_page.find(normalized_quote)
    if start < 0 or not normalized_quote:
        return None
    end = start + len(normalized_quote) - 1
    if start >= len(offsets) or end >= len(offsets):
        return None
    return page_text[offsets[start] : offsets[end] + 1].strip()


def _extract_one(row: sqlite3.Row, settings: Settings) -> tuple[str, FactExtraction | None, str | None]:
    try:
        response = _client(settings).responses.create(
            input=EXTRACTION_PROMPT.format(
                source_title=row["title"],
                source_id=row["source_id"],
                default_evidence_class=row["evidence_class_default"],
                page_number=row["page_number"],
                text=row["text"],
            ),
            response_model=FactExtraction,
            max_retries=settings.llm_max_retries,
        )
        return row["id"], response, None
    except Exception as exc:  # surfaced in DB for resumability
        return row["id"], None, f"{type(exc).__name__}: {exc}"[:4000]


def _fact_id(source_id: str, page_number: int, claim: str, quote: str) -> str:
    stable_claim = re.sub(r"\s+", " ", claim).strip().casefold()
    stable_quote = re.sub(r"\s+", " ", quote).strip()
    material = f"{source_id}\0{page_number}\0{stable_claim}\0{stable_quote}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def extract_facts(
    conn: sqlite3.Connection,
    settings: Settings,
    *,
    force: bool = False,
) -> ExtractionStats:
    settings.require_api_key()
    if force:
        clear_from_stage(conn, "extract")
        conn.commit()
    rows = conn.execute(
        """
        SELECT c.id, c.source_id, c.page_number, c.text, s.title,
               s.evidence_class_default
        FROM chunks c JOIN sources s ON s.id = c.source_id
        WHERE c.extracted_at IS NULL
        ORDER BY c.source_id, c.page_number, c.start_char
        """
    ).fetchall()
    stats = ExtractionStats()
    stats.skipped_chunks = conn.execute(
        "SELECT COUNT(*) AS n FROM chunks WHERE extracted_at IS NOT NULL"
    ).fetchone()["n"]
    if not rows:
        return stats

    row_by_id = {row["id"]: row for row in rows}
    with ThreadPoolExecutor(max_workers=settings.llm_workers) as pool:
        futures = [pool.submit(_extract_one, row, settings) for row in rows]
        for future in as_completed(futures):
            chunk_id, extraction, error = future.result()
            row = row_by_id[chunk_id]
            if error:
                conn.execute(
                    "UPDATE chunks SET extraction_error = ? WHERE id = ?", (error, chunk_id)
                )
                conn.commit()
                stats.failed_chunks += 1
                if settings.fail_fast:
                    raise RuntimeError(f"Fact extraction failed for chunk {chunk_id}: {error}")
                continue

            assert extraction is not None
            for fact in extraction.facts:
                exact_quote = resolve_exact_quote(fact.evidence_quote, row["text"])
                if exact_quote is None:
                    stats.rejected_quotes += 1
                    continue
                fact_id = _fact_id(
                    row["source_id"], row["page_number"], fact.claim, exact_quote
                )
                before = conn.total_changes
                conn.execute(
                    """
                    INSERT OR IGNORE INTO raw_facts(
                        id, chunk_id, source_id, claim, subject, predicate, object_text,
                        time_expression, location, qualifiers_json, evidence_quote,
                        page_number, extraction_confidence, extraction_model, event,
                        taxonomy_path, claim_type, evidence_class, firsthand_status,
                        date_source, date_normalized, calendar, chapter_section,
                        reported_value, unit, scope, is_negative_claim,
                        translation_status, quote_verified
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                              ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        fact_id,
                        chunk_id,
                        row["source_id"],
                        fact.claim,
                        fact.subject,
                        fact.predicate,
                        fact.object,
                        fact.date_source,
                        fact.location,
                        json.dumps(fact.qualifiers, ensure_ascii=False),
                        exact_quote,
                        row["page_number"],
                        fact.confidence,
                        settings.llm_model,
                        fact.event,
                        fact.taxonomy_path,
                        fact.claim_type.value,
                        fact.evidence_class.value,
                        fact.firsthand_status.value,
                        fact.date_source,
                        fact.date_normalized,
                        fact.calendar,
                        fact.chapter_section,
                        fact.reported_value,
                        fact.unit,
                        fact.scope,
                        int(fact.is_negative_claim),
                        fact.translation_status,
                        1,
                    ),
                )
                stats.facts_inserted += int(conn.total_changes > before)
            conn.execute(
                """
                UPDATE chunks
                SET extracted_at=CURRENT_TIMESTAMP, extraction_error=NULL
                WHERE id=?
                """,
                (chunk_id,),
            )
            conn.commit()
            stats.processed_chunks += 1
    return stats
