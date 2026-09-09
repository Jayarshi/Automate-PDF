"""Deterministic source-weighted believability scoring."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .config import clear_from_stage


FORMULA_VERSION = "weighted-neutral-silence-v1"


@dataclass(slots=True)
class ScoringStats:
    scored_facts: int = 0


def _grade(score: float, coverage: float, conflict: float) -> str:
    if coverage < 0.15:
        return "insufficient evidence"
    if conflict >= 0.5:
        return "contested"
    if score >= 85:
        return "very strong"
    if score >= 70:
        return "strong"
    if score >= 55:
        return "leaning credible"
    if score > 45:
        return "uncertain"
    if score > 30:
        return "leaning doubtful"
    if score > 15:
        return "weak"
    return "very weak"


def score_facts(conn: sqlite3.Connection, *, force: bool = False) -> ScoringStats:
    if force:
        clear_from_stage(conn, "score")
    sources = conn.execute(
        "SELECT id, credibility_weight * independence_factor AS weight FROM sources"
    ).fetchall()
    total_weight = sum(float(source["weight"]) for source in sources)
    if total_weight <= 0:
        raise RuntimeError("Total effective source weight must be positive.")
    facts = conn.execute("SELECT id FROM canonical_facts ORDER BY id").fetchall()
    if not facts:
        raise RuntimeError("No canonical facts found. Run deduplicate first.")

    stats = ScoringStats()
    for fact in facts:
        rows = conn.execute(
            """
            SELECT st.support_strength, st.contradiction_strength, st.confidence,
                   s.credibility_weight * s.independence_factor AS weight
            FROM stances st JOIN sources s ON s.id = st.source_id
            WHERE st.canonical_id = ?
            """,
            (fact["id"],),
        ).fetchall()
        if len(rows) != len(sources):
            raise RuntimeError(
                f"Fact {fact['id']} has {len(rows)}/{len(sources)} source decisions. "
                "Run or resume align before scoring."
            )
        support_mass = sum(
            float(row["weight"]) * float(row["confidence"]) * float(row["support_strength"])
            for row in rows
        )
        contradiction_mass = sum(
            float(row["weight"])
            * float(row["confidence"])
            * float(row["contradiction_strength"])
            for row in rows
        )
        evidence_mass = min(total_weight, support_mass + contradiction_mass)
        coverage = evidence_mass / total_weight
        # Silence contributes neutral 0.5 probability. This is algebraically equivalent
        # to 50 + 50 * (support_mass - contradiction_mass) / total_weight.
        score = 50.0 + 50.0 * (support_mass - contradiction_mass) / total_weight
        score = min(100.0, max(0.0, score))
        conflict = (
            2.0 * min(support_mass, contradiction_mass) / (support_mass + contradiction_mass)
            if support_mass + contradiction_mass > 0
            else 0.0
        )
        grade = _grade(score, coverage, conflict)
        conn.execute(
            """
            INSERT INTO scores(
                canonical_id, believability_score, support_mass, contradiction_mass,
                total_source_weight, evidence_coverage, conflict_index, grade,
                formula_version, scored_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(canonical_id) DO UPDATE SET
                believability_score=excluded.believability_score,
                support_mass=excluded.support_mass,
                contradiction_mass=excluded.contradiction_mass,
                total_source_weight=excluded.total_source_weight,
                evidence_coverage=excluded.evidence_coverage,
                conflict_index=excluded.conflict_index,
                grade=excluded.grade,
                formula_version=excluded.formula_version,
                scored_at=CURRENT_TIMESTAMP
            """,
            (
                fact["id"],
                score,
                support_mass,
                contradiction_mass,
                total_weight,
                coverage,
                conflict,
                grade,
                FORMULA_VERSION,
            ),
        )
        stats.scored_facts += 1
    conn.commit()
    return stats
