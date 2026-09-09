"""Cross-book retrieval and structured support/contradiction adjudication."""

from __future__ import annotations

import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import instructor
import numpy as np

from .config import Settings, clear_from_stage
from .schemas import Stance, StanceDecision


@dataclass(slots=True)
class AlignmentStats:
    decisions: int = 0
    supports: int = 0
    contradicts: int = 0
    mixed: int = 0
    silent: int = 0
    failed: int = 0


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


def _judge(
    canonical: sqlite3.Row,
    source: sqlite3.Row,
    candidates: list[dict],
    settings: Settings,
) -> StanceDecision:
    prompt = f"""Determine one book's stance toward one canonical historical claim.

Use only the candidate assertions below. A candidate supports when it entails the
canonical claim, contradicts when both cannot be true in the same scope, and is merely
related when it does neither. Different detail is not automatically contradiction.
If support and contradiction both occur in the book, return mixed. If no candidate
directly supports or contradicts, return silent. Cite only candidate ids. Strength is
semantic/evidentiary directness from 0 to 1, not source credibility. Do not use outside
knowledge or the source's reputation.

CANONICAL CLAIM: {canonical['canonical_claim']}
BOOK: {source['title']}
CANDIDATES:
{json.dumps(candidates, ensure_ascii=False, indent=2)}
"""
    return _client(settings).responses.create(
        input=prompt,
        response_model=StanceDecision,
        max_retries=settings.llm_max_retries,
    )


def _safe_decision(
    canonical: sqlite3.Row,
    source: sqlite3.Row,
    candidates: list[dict],
    settings: Settings,
) -> tuple[str, str, StanceDecision | None, str | None]:
    try:
        return canonical["id"], source["id"], _judge(canonical, source, candidates, settings), None
    except Exception as exc:
        return canonical["id"], source["id"], None, f"{type(exc).__name__}: {exc}"[:1000]


def align_sources(
    conn: sqlite3.Connection,
    settings: Settings,
    *,
    force: bool = False,
) -> AlignmentStats:
    settings.require_api_key()
    if force:
        clear_from_stage(conn, "align")
        conn.commit()
    canonical_facts = conn.execute(
        "SELECT * FROM canonical_facts ORDER BY id"
    ).fetchall()
    sources = conn.execute("SELECT * FROM sources ORDER BY id").fetchall()
    if not canonical_facts:
        raise RuntimeError("No canonical facts found. Run the deduplicate stage first.")

    raw_rows = conn.execute(
        """
        SELECT rf.*, p.page_label
        FROM raw_facts rf
        JOIN chunks c ON c.id = rf.chunk_id
        JOIN pages p ON p.id = c.page_id
        WHERE rf.embedding_json IS NOT NULL
        ORDER BY rf.id
        """
    ).fetchall()
    rows_by_source: dict[str, list[sqlite3.Row]] = {source["id"]: [] for source in sources}
    for row in raw_rows:
        rows_by_source[row["source_id"]].append(row)
    member_map: dict[str, set[str]] = {}
    for row in conn.execute("SELECT canonical_id, raw_fact_id FROM fact_members"):
        member_map.setdefault(row["canonical_id"], set()).add(row["raw_fact_id"])

    existing = {
        (row["canonical_id"], row["source_id"])
        for row in conn.execute("SELECT canonical_id, source_id FROM stances")
    }
    jobs: list[tuple[sqlite3.Row, sqlite3.Row, list[dict]]] = []
    silent_rows: list[tuple[sqlite3.Row, sqlite3.Row]] = []
    for canonical in canonical_facts:
        canonical_vector = np.asarray(json.loads(canonical["embedding_json"]), dtype=np.float32)
        canonical_vector /= max(float(np.linalg.norm(canonical_vector)), 1e-12)
        direct_members = member_map.get(canonical["id"], set())
        for source in sources:
            if (canonical["id"], source["id"]) in existing:
                continue
            source_rows = rows_by_source[source["id"]]
            scored: list[tuple[float, sqlite3.Row]] = []
            for row in source_rows:
                vector = np.asarray(json.loads(row["embedding_json"]), dtype=np.float32)
                vector /= max(float(np.linalg.norm(vector)), 1e-12)
                similarity = float(canonical_vector @ vector)
                if similarity >= settings.alignment_retrieval_threshold or row["id"] in direct_members:
                    scored.append((similarity, row))
            scored.sort(key=lambda pair: pair[0], reverse=True)
            selected = scored[: settings.alignment_top_k]
            if not selected:
                silent_rows.append((canonical, source))
                continue
            candidates = [
                {
                    "id": row["id"],
                    "claim": row["claim"],
                    "quote": row["evidence_quote"],
                    "pdf_page": row["page_number"],
                    "printed_page_label": row["page_label"],
                    "retrieval_similarity": round(similarity, 4),
                }
                for similarity, row in selected
            ]
            jobs.append((canonical, source, candidates))

    stats = AlignmentStats()
    for canonical, source in silent_rows:
        conn.execute(
            """
            INSERT INTO stances(
                canonical_id, source_id, stance, support_strength,
                contradiction_strength, confidence, support_evidence_ids_json,
                contradiction_evidence_ids_json, rationale, alignment_model
            ) VALUES (?, ?, 'silent', 0, 0, 0.8, '[]', '[]', ?, ?)
            """,
            (
                canonical["id"],
                source["id"],
                "No extracted assertion in this book passed semantic retrieval for the claim.",
                settings.llm_model,
            ),
        )
        stats.decisions += 1
        stats.silent += 1
    conn.commit()

    candidate_ids = {
        (canonical["id"], source["id"]): {item["id"] for item in candidates}
        for canonical, source, candidates in jobs
    }
    with ThreadPoolExecutor(max_workers=settings.llm_workers) as pool:
        futures = [
            pool.submit(_safe_decision, canonical, source, candidates, settings)
            for canonical, source, candidates in jobs
        ]
        for future in as_completed(futures):
            canonical_id, source_id, decision, error = future.result()
            if error:
                stats.failed += 1
                if settings.fail_fast:
                    raise RuntimeError(
                        f"Alignment failed for {canonical_id}/{source_id}: {error}"
                    )
                continue
            assert decision is not None
            allowed = candidate_ids[(canonical_id, source_id)]
            support_ids = [item for item in decision.support_evidence_ids if item in allowed]
            contradiction_ids = [
                item for item in decision.contradiction_evidence_ids if item in allowed
            ]
            stance = decision.stance
            support_strength = decision.support_strength
            contradiction_strength = decision.contradiction_strength
            if not support_ids and not contradiction_ids:
                stance = Stance.SILENT
                support_strength = contradiction_strength = 0.0
            elif support_ids and contradiction_ids:
                stance = Stance.MIXED
            elif support_ids:
                stance = Stance.SUPPORTS
                contradiction_strength = 0.0
            else:
                stance = Stance.CONTRADICTS
                support_strength = 0.0
            conn.execute(
                """
                INSERT INTO stances(
                    canonical_id, source_id, stance, support_strength,
                    contradiction_strength, confidence, support_evidence_ids_json,
                    contradiction_evidence_ids_json, rationale, alignment_model
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    canonical_id,
                    source_id,
                    stance.value,
                    support_strength,
                    contradiction_strength,
                    decision.confidence,
                    json.dumps(support_ids),
                    json.dumps(contradiction_ids),
                    decision.rationale,
                    settings.llm_model,
                ),
            )
            conn.commit()
            stats.decisions += 1
            if stance == Stance.SUPPORTS:
                stats.supports += 1
            elif stance == Stance.CONTRADICTS:
                stats.contradicts += 1
            elif stance == Stance.MIXED:
                stats.mixed += 1
            else:
                stats.silent += 1
    return stats
