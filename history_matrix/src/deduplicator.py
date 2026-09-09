"""Embedding candidate generation plus LLM partitioning into disputed fact families."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass

import instructor
import numpy as np
from openai import OpenAI
from sklearn.neighbors import NearestNeighbors

from .config import Settings, clear_from_stage
from .schemas import CanonicalGroup, DeduplicationResult


MAX_COMPONENT_SIZE = 60


@dataclass(slots=True)
class DeduplicationStats:
    embedded_facts: int = 0
    candidate_components: int = 0
    canonical_facts: int = 0
    fallback_singletons: int = 0


class _UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, item: int) -> int:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, left: int, right: int) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


def _embed(client: OpenAI, texts: list[str], settings: Settings) -> list[list[float]]:
    vectors: list[list[float]] = []
    for start in range(0, len(texts), settings.embedding_batch_size):
        batch = texts[start : start + settings.embedding_batch_size]
        response = client.embeddings.create(model=settings.embedding_model, input=batch)
        vectors.extend(item.embedding for item in sorted(response.data, key=lambda item: item.index))
    return vectors


def _components(matrix: np.ndarray, threshold: float) -> list[list[int]]:
    if len(matrix) == 1:
        return [[0]]
    neighbors = NearestNeighbors(metric="cosine", algorithm="brute", n_jobs=-1)
    neighbors.fit(matrix)
    distances, indices = neighbors.radius_neighbors(
        matrix, radius=max(0.0, 1.0 - threshold), return_distance=True
    )
    union_find = _UnionFind(len(matrix))
    for row_index, (row_distances, row_indices) in enumerate(zip(distances, indices)):
        for distance, neighbor_index in zip(row_distances, row_indices):
            if neighbor_index != row_index and 1.0 - float(distance) >= threshold:
                union_find.union(row_index, int(neighbor_index))
    grouped: dict[int, list[int]] = {}
    for index in range(len(matrix)):
        grouped.setdefault(union_find.find(index), []).append(index)
    return list(grouped.values())


def _bounded_components(
    matrix: np.ndarray, threshold: float, indices: list[int] | None = None
) -> list[list[int]]:
    indices = indices or list(range(len(matrix)))
    local_components = _components(matrix[indices], threshold)
    result: list[list[int]] = []
    for local in local_components:
        global_component = [indices[position] for position in local]
        if len(global_component) <= MAX_COMPONENT_SIZE or threshold >= 0.97:
            result.extend(
                global_component[start : start + MAX_COMPONENT_SIZE]
                for start in range(0, len(global_component), MAX_COMPONENT_SIZE)
            )
        else:
            result.extend(_bounded_components(matrix, threshold + 0.03, global_component))
    return result


def _singleton(row: sqlite3.Row) -> CanonicalGroup:
    return CanonicalGroup(
        raw_fact_ids=[row["id"]],
        canonical_claim=row["claim"],
        subject=row["subject"],
        time_expression=row["time_expression"],
        location=row["location"],
    )


def _partition_component(
    component_rows: list[sqlite3.Row], settings: Settings
) -> list[CanonicalGroup] | None:
    if len(component_rows) == 1:
        return [_singleton(component_rows[0])]
    payload = [
        {
            "id": row["id"],
            "claim": row["claim"],
            "subject": row["subject"],
            "time": row["time_expression"],
            "location": row["location"],
            "source_id": row["source_id"],
        }
        for row in component_rows
    ]
    prompt = f"""Partition the candidate assertions into precise fact families.

A family represents one proposition that can occupy one consensus-ledger row. Put
paraphrases together. Also put directly competing values together (for example,
different dates for the same event), because they are support/contradiction evidence
for one disputed proposition. Do NOT merge assertions merely because they mention the
same person, place, or event. Every input id must appear exactly once.

For each family, select or rewrite one concrete, testable proposition represented by
an input assertion. When values compete, choose one concrete formulation as the row's
claim so other values can be classified as contradictions; never write a meta-claim
such as "sources disagree" or list alternatives. Do not decide truth, consult outside
knowledge, or use source reputation. Preserve dates, negation, scope, and attribution
when central to the proposition.

CANDIDATES:
{json.dumps(payload, ensure_ascii=False, indent=2)}
"""
    client = instructor.from_provider(
        f"openai/{settings.llm_model}",
        mode=instructor.Mode.RESPONSES_TOOLS,
        api_key=settings.openai_api_key,
    )
    result = client.responses.create(
        input=prompt,
        response_model=DeduplicationResult,
        max_retries=settings.llm_max_retries,
    )
    expected = [row["id"] for row in component_rows]
    observed = [fact_id for group in result.groups for fact_id in group.raw_fact_ids]
    if len(observed) != len(set(observed)) or set(observed) != set(expected):
        return None
    return result.groups


def deduplicate_facts(
    conn: sqlite3.Connection,
    settings: Settings,
    *,
    force: bool = False,
) -> DeduplicationStats:
    settings.require_api_key()
    if force:
        clear_from_stage(conn, "deduplicate")
        conn.commit()
    existing = conn.execute("SELECT COUNT(*) AS n FROM canonical_facts").fetchone()["n"]
    if existing:
        return DeduplicationStats(canonical_facts=existing)

    rows = conn.execute(
        """
        SELECT id, source_id, claim, subject, time_expression, location,
               embedding_json, embedding_model
        FROM raw_facts ORDER BY id
        """
    ).fetchall()
    if not rows:
        raise RuntimeError("No raw facts found. Run the extract stage first.")

    stats = DeduplicationStats()
    openai_client = OpenAI(api_key=settings.openai_api_key)
    missing = [
        row for row in rows
        if not row["embedding_json"] or row["embedding_model"] != settings.embedding_model
    ]
    if missing:
        vectors = _embed(openai_client, [row["claim"] for row in missing], settings)
        for row, vector in zip(missing, vectors):
            conn.execute(
                """
                UPDATE raw_facts SET embedding_json=?, embedding_model=? WHERE id=?
                """,
                (json.dumps(vector), settings.embedding_model, row["id"]),
            )
        conn.commit()
        stats.embedded_facts = len(missing)
        rows = conn.execute(
            """
            SELECT id, source_id, claim, subject, time_expression, location,
                   embedding_json, embedding_model
            FROM raw_facts ORDER BY id
            """
        ).fetchall()

    matrix = np.asarray([json.loads(row["embedding_json"]) for row in rows], dtype=np.float32)
    matrix /= np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-12)
    components = _bounded_components(matrix, settings.dedup_similarity_threshold)
    stats.candidate_components = len(components)

    groups: list[CanonicalGroup] = []
    for component in components:
        component_rows = [rows[index] for index in component]
        try:
            partitioned = _partition_component(component_rows, settings)
        except Exception:
            if settings.fail_fast:
                raise
            partitioned = None
        if partitioned is None:
            groups.extend(_singleton(row) for row in component_rows)
            stats.fallback_singletons += len(component_rows)
        else:
            groups.extend(partitioned)

    canonical_vectors = _embed(
        openai_client, [group.canonical_claim for group in groups], settings
    )
    raw_index = {row["id"]: index for index, row in enumerate(rows)}
    for group, vector in zip(groups, canonical_vectors):
        canonical_id = hashlib.sha256(
            "\0".join(sorted(group.raw_fact_ids)).encode("utf-8")
        ).hexdigest()[:32]
        normalized_vector = np.asarray(vector, dtype=np.float32)
        normalized_vector /= max(float(np.linalg.norm(normalized_vector)), 1e-12)
        conn.execute(
            """
            INSERT INTO canonical_facts(
                id, canonical_claim, subject, time_expression, location,
                embedding_json, embedding_model
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                canonical_id,
                group.canonical_claim,
                group.subject,
                group.time_expression,
                group.location,
                json.dumps(vector),
                settings.embedding_model,
            ),
        )
        for raw_fact_id in group.raw_fact_ids:
            similarity = float(matrix[raw_index[raw_fact_id]] @ normalized_vector)
            conn.execute(
                """
                INSERT INTO fact_members(canonical_id, raw_fact_id, similarity)
                VALUES (?, ?, ?)
                """,
                (canonical_id, raw_fact_id, similarity),
            )
    conn.commit()
    stats.canonical_facts = len(groups)
    return stats
