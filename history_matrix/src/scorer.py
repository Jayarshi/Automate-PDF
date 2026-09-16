"""Deterministic, multidimensional, independence-aware research scoring."""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass

from .config import SourceManifest, clear_from_stage
from .schemas import ClaimType, EvidenceClass, Stance


FORMULA_VERSION = "independence-aware-evidence-index-v2"


@dataclass(slots=True)
class ScoringStats:
    scored_facts: int = 0
    established: int = 0
    probable: int = 0
    plausible: int = 0
    contested: int = 0
    unverified: int = 0
    interpretations: int = 0


def _evidence_factor(
    conn: sqlite3.Connection,
    evidence_ids: list[str],
    multipliers: dict[EvidenceClass, float],
) -> tuple[float, set[EvidenceClass]]:
    if not evidence_ids:
        return 0.0, set()
    placeholders = ",".join("?" for _ in evidence_ids)
    rows = conn.execute(
        f"""
        SELECT evidence_class, extraction_confidence FROM raw_facts
        WHERE id IN ({placeholders}) AND quote_verified=1
        """,
        tuple(evidence_ids),
    ).fetchall()
    factors: list[float] = []
    classes: set[EvidenceClass] = set()
    for row in rows:
        try:
            evidence_class = EvidenceClass(row["evidence_class"])
        except ValueError:
            evidence_class = EvidenceClass.E7
        classes.add(evidence_class)
        factors.append(
            multipliers[evidence_class] * max(0.0, min(1.0, row["extraction_confidence"]))
        )
    # Multiple quotations from one source improve auditability, not independence.
    return max(factors, default=0.0), classes


def _classification(
    claim_type: str,
    support_mass: float,
    contradiction_mass: float,
    independent_supports: int,
    primary_documents: int,
    manifest: SourceManifest,
) -> tuple[str, str]:
    if claim_type == ClaimType.INTERPRETATION.value:
        return "INTERPRETATION", "Interpretive claim — factual tier not applicable"
    if claim_type in {ClaimType.CAUSAL_INTERPRETATION.value, ClaimType.MOTIVE_CLAIM.value}:
        return "CAUSAL_INTERPRETATION", "Interpretive claim — heightened scrutiny"
    if claim_type == ClaimType.REPORTED_SPEECH.value:
        return "SOURCE_REPORT", "Source report — occurrence not independently established"

    threshold = manifest.scoring.tier_thresholds
    if (
        contradiction_mass >= threshold.serious_contradiction
        and support_mass >= threshold.meaningful_contribution
    ):
        return "FACT_CONTESTED", "Tier 4 — Contested"
    if (
        support_mass >= threshold.established_support_mass
        and independent_supports >= threshold.established_independent_clusters
        and (primary_documents >= 1 or independent_supports >= 3)
        and contradiction_mass < threshold.serious_contradiction
    ):
        return "FACT_ESTABLISHED", "Tier 1 — Established"
    if (
        support_mass >= threshold.probable_support_mass
        and independent_supports >= threshold.probable_independent_clusters
        and contradiction_mass < threshold.serious_contradiction
    ):
        return "FACT_PROBABLE", "Tier 2 — Probable"
    if (
        support_mass >= threshold.plausible_support_mass
        and contradiction_mass < threshold.serious_contradiction
    ):
        return "FACT_PLAUSIBLE", "Tier 3 — Plausible / unverified"
    return "FACT_UNVERIFIED", "Tier 5 — Unsupported / speculative"


def score_facts(
    conn: sqlite3.Connection,
    manifest: SourceManifest,
    *,
    force: bool = False,
) -> ScoringStats:
    """Score evidence strength/direction without claiming truth probabilities.

    For source i, q_i is the policy's weighted geometric source quality. Selected
    evidence contributes q_i * class_multiplier * extraction_confidence *
    alignment_confidence * stance_value. Within each dependence cluster, only the
    largest support and contradiction contributions survive. For A=support mass and
    D=penalizable contradiction mass, I(F)=100(A-D)/(1+A+D).
    """
    if force:
        clear_from_stage(conn, "score")
    source_policy = {source.id: source for source in manifest.sources}
    source_rows = conn.execute("SELECT id FROM sources ORDER BY id").fetchall()
    facts = conn.execute("SELECT id, claim_type FROM canonical_facts ORDER BY id").fetchall()
    if not facts:
        raise RuntimeError("No canonical facts found. Run deduplicate first.")

    quality = {
        source.id: source.quality(manifest.scoring.dimension_weights)
        for source in manifest.sources
    }
    total_cluster_quality: dict[str, float] = {}
    for source in manifest.sources:
        total_cluster_quality[source.independence_cluster_id] = max(
            total_cluster_quality.get(source.independence_cluster_id, 0.0), quality[source.id]
        )
    total_weight = sum(total_cluster_quality.values())
    penalized_types = {
        item.value for item in manifest.scoring.contradiction_penalty_types
    }
    stats = ScoringStats()

    for fact in facts:
        decisions = conn.execute(
            "SELECT * FROM stances WHERE canonical_id=? ORDER BY source_id", (fact["id"],)
        ).fetchall()
        if len(decisions) != len(source_rows):
            raise RuntimeError(
                f"Fact {fact['id']} has {len(decisions)}/{len(source_rows)} source decisions. "
                "Run or resume align first."
            )

        cluster_support: dict[str, float] = {}
        cluster_contradiction: dict[str, float] = {}
        covered_cluster_quality: dict[str, float] = {}
        supporting_sources = 0
        primary_sources: set[str] = set()
        eyewitness_sources: set[str] = set()
        scholarly_sources: set[str] = set()
        serious_contradictions = 0

        for decision in decisions:
            source = source_policy[decision["source_id"]]
            cluster = source.independence_cluster_id
            q_i = quality[source.id]
            if decision["coverage"] != "not_covered":
                covered_cluster_quality[cluster] = max(
                    covered_cluster_quality.get(cluster, 0.0), q_i
                )
            support_ids = json.loads(decision["support_evidence_ids_json"])
            contradiction_ids = json.loads(decision["contradiction_evidence_ids_json"])
            support_factor, support_classes = _evidence_factor(
                conn, support_ids, manifest.scoring.evidence_class_multipliers
            )
            contradiction_factor, contradiction_classes = _evidence_factor(
                conn, contradiction_ids, manifest.scoring.evidence_class_multipliers
            )
            if EvidenceClass.E1 in support_classes:
                primary_sources.add(source.id)
            if EvidenceClass.E2 in support_classes:
                eyewitness_sources.add(source.id)
            if EvidenceClass.E4 in support_classes:
                scholarly_sources.add(source.id)

            confidence = max(0.0, min(1.0, float(decision["confidence"])))
            stance = Stance(decision["stance"])
            support_strength = 0.0
            contradiction_strength = 0.0
            if stance == Stance.EXPLICIT_SUPPORT:
                support_strength = max(
                    0.0, manifest.scoring.stance_values[Stance.EXPLICIT_SUPPORT]
                )
            elif stance == Stance.IMPLICIT_SUPPORT:
                support_strength = max(
                    0.0, manifest.scoring.stance_values[Stance.IMPLICIT_SUPPORT]
                )
            elif stance == Stance.MIXED:
                support_strength = max(
                    0.0, manifest.scoring.stance_values[Stance.EXPLICIT_SUPPORT]
                )
            if (
                stance in {Stance.EXPLICIT_CONTRADICTION, Stance.MIXED}
                and decision["contradiction_type"]
                in penalized_types
            ):
                contradiction_strength = abs(
                    manifest.scoring.stance_values[Stance.EXPLICIT_CONTRADICTION]
                )

            support = q_i * support_factor * confidence * support_strength
            contradiction = (
                q_i
                * contradiction_factor
                * confidence
                * contradiction_strength
            )
            if support > 0:
                supporting_sources += 1
                cluster_support[cluster] = max(cluster_support.get(cluster, 0.0), support)
            if contradiction > 0:
                serious_contradictions += 1
                cluster_contradiction[cluster] = max(
                    cluster_contradiction.get(cluster, 0.0), contradiction
                )

        support_mass = sum(cluster_support.values())
        contradiction_mass = sum(cluster_contradiction.values())
        independent_supports = sum(
            contribution >= manifest.scoring.tier_thresholds.meaningful_contribution
            for contribution in cluster_support.values()
        )
        # A weak independent source is not thereby a dependent source. This count
        # records only extra supporting books inside already represented clusters.
        dependent_supports = max(0, supporting_sources - len(cluster_support))
        coverage = (
            sum(covered_cluster_quality.values()) / total_weight if total_weight else 0.0
        )
        research_index = 100.0 * (support_mass - contradiction_mass) / (
            1.0 + support_mass + contradiction_mass
        )
        evidence_strength = 100.0 * (1.0 - math.exp(-(support_mass + contradiction_mass)))
        conflict = (
            2.0 * min(support_mass, contradiction_mass) / (support_mass + contradiction_mass)
            if support_mass + contradiction_mass else 0.0
        )
        grade, tier = _classification(
            fact["claim_type"], support_mass, contradiction_mass, independent_supports,
            len(primary_sources), manifest,
        )
        conn.execute(
            """
            INSERT INTO scores(
                canonical_id, believability_score, support_mass, contradiction_mass,
                total_source_weight, evidence_coverage, conflict_index, grade,
                formula_version, research_index, evidence_strength,
                independent_support_count, dependent_support_count, primary_document_count,
                eyewitness_count, scholarly_reconstruction_count,
                serious_contradiction_count, confidence_tier, scored_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(canonical_id) DO UPDATE SET
                believability_score=excluded.believability_score,
                support_mass=excluded.support_mass,
                contradiction_mass=excluded.contradiction_mass,
                total_source_weight=excluded.total_source_weight,
                evidence_coverage=excluded.evidence_coverage,
                conflict_index=excluded.conflict_index, grade=excluded.grade,
                formula_version=excluded.formula_version,
                research_index=excluded.research_index,
                evidence_strength=excluded.evidence_strength,
                independent_support_count=excluded.independent_support_count,
                dependent_support_count=excluded.dependent_support_count,
                primary_document_count=excluded.primary_document_count,
                eyewitness_count=excluded.eyewitness_count,
                scholarly_reconstruction_count=excluded.scholarly_reconstruction_count,
                serious_contradiction_count=excluded.serious_contradiction_count,
                confidence_tier=excluded.confidence_tier, scored_at=CURRENT_TIMESTAMP
            """,
            (
                fact["id"], research_index, support_mass, contradiction_mass, total_weight,
                coverage, conflict, grade, FORMULA_VERSION, research_index,
                evidence_strength, independent_supports, dependent_supports,
                len(primary_sources), len(eyewitness_sources), len(scholarly_sources),
                serious_contradictions, tier,
            ),
        )
        stats.scored_facts += 1
        if grade == "FACT_ESTABLISHED":
            stats.established += 1
        elif grade == "FACT_PROBABLE":
            stats.probable += 1
        elif grade == "FACT_PLAUSIBLE":
            stats.plausible += 1
        elif grade == "FACT_CONTESTED":
            stats.contested += 1
        elif grade == "FACT_UNVERIFIED":
            stats.unverified += 1
        else:
            stats.interpretations += 1
    conn.commit()
    return stats
