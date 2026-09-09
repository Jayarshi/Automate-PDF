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


EXTRACTION_PROMPT = """You extract historical assertions from one PDF page chunk.

Rules:
1. Extract every externally checkable historical assertion, not opinions or pure rhetoric.
2. Make each fact atomic: one subject, one predicate, and one object/value.
3. Preserve uncertainty, attribution, negation, dates, quantities, and scope as qualifiers.
4. The claim must be self-contained. Resolve pronouns only when the page makes the referent clear.
5. evidence_quote MUST be copied verbatim from PAGE_TEXT and directly entail the claim.
6. Do not use outside knowledge. Do not infer facts that the text merely implies weakly.
7. If the page contains no factual historical assertion, return an empty facts list.

SOURCE: {source_title}
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
        SELECT c.id, c.source_id, c.page_number, c.text, s.title
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
                        page_number, extraction_confidence, extraction_model
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        fact_id,
                        chunk_id,
                        row["source_id"],
                        fact.claim,
                        fact.subject,
                        fact.predicate,
                        fact.object,
                        fact.time_expression,
                        fact.location,
                        json.dumps(fact.qualifiers, ensure_ascii=False),
                        exact_quote,
                        row["page_number"],
                        fact.confidence,
                        settings.llm_model,
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
