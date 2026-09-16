"""Cross-book retrieval and evidence-preserving stance adjudication."""

from __future__ import annotations

import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import instructor
import numpy as np

from .config import Settings, SourceManifest, clear_from_stage
from .schemas import ContradictionType, Coverage, Stance, StanceDecision


@dataclass(slots=True)
class AlignmentStats:
    decisions: int = 0
    explicit_support: int = 0
    implicit_support: int = 0
    contradictions: int = 0
    mixed: int = 0
    covered_but_silent: int = 0
    not_covered: int = 0
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
    prompt = f"""Adjudicate one book's evidence toward one canonical historical claim.

Use only the candidate assertions. Do not use source prestige or outside knowledge.
Explicit support directly entails the claim. Implicit support is circumstantial and
must not be upgraded. Silence is never contradiction. If the book discusses the
event but does not address this proposition, use covered_but_silent + silent.

For disagreement, assign exactly one taxonomy value:
D1 factual incompatibility; D2 chronology/date; D3 scope; D4 terminology;
D5 perspective; D6 interpretation; D7 numerical discrepancy; D8 access limitation;
D9 translation/edition. Only D1 is an automatic mathematical penalty. Different
scope, calendar, wording, or perspective is not D1. Preserve uncertainty and cite
only candidate ids. A source may be mixed if it contains both forms of evidence.

CANONICAL CLAIM: {canonical['canonical_claim']}
EVENT: {canonical['event'] or 'unclassified'}
CLAIM TYPE: {canonical['claim_type']}
SOURCE: {source['title']}
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
        decision = _judge(canonical, source, candidates, settings)
        return canonical["id"], source["id"], decision, None
    except Exception as exc:
        return canonical["id"], source["id"], None, f"{type(exc).__name__}: {exc}"[:1500]


def _strengths(
    stance: Stance,
    contradiction_type: ContradictionType | None,
    manifest: SourceManifest,
) -> tuple[float, float, float]:
    values = manifest.scoring.stance_values
    penalized_types = {
        item.value for item in manifest.scoring.contradiction_penalty_types
    }
    support = 0.0
    contradiction = 0.0
    if stance == Stance.EXPLICIT_SUPPORT:
        support = max(0.0, values[Stance.EXPLICIT_SUPPORT])
    elif stance == Stance.IMPLICIT_SUPPORT:
        support = max(0.0, values[Stance.IMPLICIT_SUPPORT])
    elif stance == Stance.EXPLICIT_CONTRADICTION:
        if contradiction_type and contradiction_type.value in penalized_types:
            contradiction = abs(values[Stance.EXPLICIT_CONTRADICTION])
    elif stance == Stance.MIXED:
        support = max(0.0, values[Stance.EXPLICIT_SUPPORT])
        if contradiction_type and contradiction_type.value in penalized_types:
            contradiction = abs(values[Stance.EXPLICIT_CONTRADICTION])
    return support, contradiction, support - contradiction


def _insert_decision(
    conn: sqlite3.Connection,
    canonical_id: str,
    source_id: str,
    decision: StanceDecision,
    manifest: SourceManifest,
    model: str,
) -> None:
    support, contradiction, stance_value = _strengths(
        decision.stance, decision.contradiction_type, manifest
    )
    conn.execute(
        """
        INSERT INTO stances(
            canonical_id, source_id, stance, support_strength,
            contradiction_strength, confidence, support_evidence_ids_json,
            contradiction_evidence_ids_json, rationale, alignment_model, coverage,
            contradiction_type, chronology_notes, scope_notes, stance_value
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            canonical_id, source_id, decision.stance.value, support, contradiction,
            decision.confidence, json.dumps(decision.support_evidence_ids),
            json.dumps(decision.contradiction_evidence_ids), decision.rationale, model,
            decision.coverage.value,
            decision.contradiction_type.value if decision.contradiction_type else None,
            decision.chronology_notes, decision.scope_notes, stance_value,
        ),
    )


def align_sources(
    conn: sqlite3.Connection,
    settings: Settings,
    manifest: SourceManifest,
    *,
    force: bool = False,
) -> AlignmentStats:
    settings.require_api_key()
    if force:
        clear_from_stage(conn, "align")
        conn.commit()
    canonical_facts = conn.execute("SELECT * FROM canonical_facts ORDER BY id").fetchall()
    sources = conn.execute("SELECT * FROM sources ORDER BY id").fetchall()
    if not canonical_facts:
        raise RuntimeError("No canonical facts found. Run deduplicate first.")

    raw_rows = conn.execute(
        """
        SELECT rf.*, p.page_label FROM raw_facts rf
        JOIN chunks c ON c.id=rf.chunk_id JOIN pages p ON p.id=c.page_id
        WHERE rf.embedding_json IS NOT NULL ORDER BY rf.id
        """
    ).fetchall()
    rows_by_source: dict[str, list[sqlite3.Row]] = {row["id"]: [] for row in sources}
    for row in raw_rows:
        rows_by_source[row["source_id"]].append(row)
    source_indexes: dict[
        str, tuple[list[sqlite3.Row], np.ndarray, dict[str, int]]
    ] = {}
    for source_id, source_raw_rows in rows_by_source.items():
        if not source_raw_rows:
            continue
        matrix = np.asarray(
            [json.loads(row["embedding_json"]) for row in source_raw_rows],
            dtype=np.float32,
        )
        matrix /= np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-12)
        source_indexes[source_id] = (
            source_raw_rows,
            matrix,
            {row["id"]: index for index, row in enumerate(source_raw_rows)},
        )
    member_map: dict[str, set[str]] = {}
    for row in conn.execute("SELECT canonical_id, raw_fact_id FROM fact_members"):
        member_map.setdefault(row["canonical_id"], set()).add(row["raw_fact_id"])
    existing = {
        (row["canonical_id"], row["source_id"])
        for row in conn.execute("SELECT canonical_id, source_id FROM stances")
    }

    jobs: list[tuple[sqlite3.Row, sqlite3.Row, list[dict]]] = []
    not_covered: list[tuple[sqlite3.Row, sqlite3.Row]] = []
    for canonical in canonical_facts:
        canonical_vector = np.asarray(json.loads(canonical["embedding_json"]), dtype=np.float32)
        canonical_vector /= max(float(np.linalg.norm(canonical_vector)), 1e-12)
        direct_members = member_map.get(canonical["id"], set())
        for source in sources:
            if (canonical["id"], source["id"]) in existing:
                continue
            source_index = source_indexes.get(source["id"])
            if source_index is None:
                not_covered.append((canonical, source))
                continue
            source_raw_rows, matrix, id_to_index = source_index
            similarities = matrix @ canonical_vector
            direct_indices = {
                id_to_index[raw_id] for raw_id in direct_members if raw_id in id_to_index
            }
            retrieved_indices = set(
                np.flatnonzero(
                    similarities >= settings.alignment_retrieval_threshold
                ).tolist()
            ) - direct_indices
            ordered_direct = sorted(
                direct_indices, key=lambda index: float(similarities[index]), reverse=True
            )
            ordered_retrieved = sorted(
                retrieved_indices,
                key=lambda index: float(similarities[index]),
                reverse=True,
            )
            remaining = max(0, settings.alignment_top_k - len(ordered_direct))
            selected_indices = ordered_direct + ordered_retrieved[:remaining]
            if not selected_indices:
                not_covered.append((canonical, source))
                continue
            candidates = [
                {
                    "id": raw["id"], "claim": raw["claim"], "event": raw["event"],
                    "claim_type": raw["claim_type"], "evidence_class": raw["evidence_class"],
                    "quote": raw["evidence_quote"], "pdf_page": raw["page_number"],
                    "printed_page_label": raw["page_label"],
                    "similarity": round(similarity, 4),
                }
                for index in selected_indices
                for raw, similarity in [
                    (source_raw_rows[index], float(similarities[index]))
                ]
            ]
            jobs.append((canonical, source, candidates))

    stats = AlignmentStats()
    for canonical, source in not_covered:
        decision = StanceDecision(
            coverage=Coverage.NOT_COVERED,
            stance=Stance.SILENT,
            confidence=1.0,
            rationale="No extracted assertion from this source passed topical retrieval.",
        )
        _insert_decision(conn, canonical["id"], source["id"], decision, manifest, "retrieval")
        stats.decisions += 1
        stats.not_covered += 1
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
                    raise RuntimeError(f"Alignment failed for {canonical_id}/{source_id}: {error}")
                continue
            assert decision is not None
            allowed = candidate_ids[(canonical_id, source_id)]
            support_ids = [item for item in decision.support_evidence_ids if item in allowed]
            contradiction_ids = [
                item for item in decision.contradiction_evidence_ids if item in allowed
            ]
            if support_ids and contradiction_ids:
                stance = Stance.MIXED
            elif support_ids:
                stance = (
                    decision.stance
                    if decision.stance in {Stance.EXPLICIT_SUPPORT, Stance.IMPLICIT_SUPPORT}
                    else Stance.EXPLICIT_SUPPORT
                )
            elif contradiction_ids:
                stance = Stance.EXPLICIT_CONTRADICTION
            else:
                stance = Stance.SILENT
            sanitized = StanceDecision(
                coverage=(Coverage.COVERED_BUT_SILENT if stance == Stance.SILENT else Coverage.COVERED),
                stance=stance,
                support_evidence_ids=support_ids,
                contradiction_evidence_ids=contradiction_ids,
                contradiction_type=(
                    decision.contradiction_type
                    if contradiction_ids else None
                ),
                confidence=decision.confidence,
                rationale=decision.rationale,
                chronology_notes=decision.chronology_notes,
                scope_notes=decision.scope_notes,
            )
            _insert_decision(conn, canonical_id, source_id, sanitized, manifest, settings.llm_model)
            conn.commit()
            stats.decisions += 1
            if stance == Stance.EXPLICIT_SUPPORT:
                stats.explicit_support += 1
            elif stance == Stance.IMPLICIT_SUPPORT:
                stats.implicit_support += 1
            elif stance == Stance.EXPLICIT_CONTRADICTION:
                stats.contradictions += 1
            elif stance == Stance.MIXED:
                stats.mixed += 1
            else:
                stats.covered_but_silent += 1
    return stats
