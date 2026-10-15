from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from .config import QualityConfig
from .numbers import extract_numbers


class QualityEvaluator:
    """Reference-free checks, optional COMET-QE, and reference metrics when available."""

    def __init__(self, config: QualityConfig) -> None:
        self.config = config
        self._comet_model: Any = None

    def evaluate(
        self,
        source: str,
        candidate: str,
        glossary: dict[str, str] | None = None,
        inherited_issues: list[str] | None = None,
        reference: str | None = None,
    ) -> tuple[float, dict[str, float | None], list[str]]:
        issues = list(inherited_issues or [])
        metrics: dict[str, float | None] = {
            "heuristic": None,
            "comet_qe": None,
            "chrf++": None,
            "bleu": None,
        }
        if not candidate.strip():
            issues.append("empty translation")
            metrics["heuristic"] = 0.0
            return 0.0, metrics, _unique(issues)

        score = 1.0
        source_size = max(1, len(_content_units(source)))
        candidate_size = len(_content_units(candidate))
        ratio = candidate_size / source_size
        metrics["length_ratio"] = round(ratio, 4)
        if ratio < self.config.min_length_ratio or ratio > self.config.max_length_ratio:
            issues.append(f"suspicious length ratio: {ratio:.2f}")
            score -= 0.25

        copy_ratio = SequenceMatcher(None, source.casefold(), candidate.casefold()).ratio()
        metrics["copy_ratio"] = round(copy_ratio, 4)
        if copy_ratio > self.config.max_copy_ratio and source.casefold() != candidate.casefold():
            issues.append(f"source-copy ratio too high: {copy_ratio:.2f}")
            score -= 0.15

        repetition = _repetition_ratio(candidate)
        metrics["repetition_ratio"] = round(repetition, 4)
        if repetition > 0.35:
            issues.append(f"repeated phrase ratio too high: {repetition:.2f}")
            score -= 0.15

        source_numbers = extract_numbers(source)
        candidate_numbers = extract_numbers(candidate)
        numbers_preserved = source_numbers <= candidate_numbers
        metrics["numbers_preserved"] = 1.0 if numbers_preserved else 0.0
        if not numbers_preserved:
            issues.append(
                "number mismatch: "
                f"source={list(source_numbers.elements())}, "
                f"translation={list(candidate_numbers.elements())}"
            )
            score -= 0.6

        missing_terms = [
            target
            for source_term, target in (glossary or {}).items()
            if source_term.casefold() in source.casefold()
            and target.casefold() not in candidate.casefold()
        ]
        if missing_terms:
            issues.extend(f"missing glossary term: {term}" for term in missing_terms)
            score -= min(0.5, 0.15 * len(missing_terms))

        # Restoration or local-LLM failures arrive as inherited issues.
        score -= min(0.5, 0.15 * len(inherited_issues or []))
        heuristic = max(0.0, min(1.0, score))
        metrics["heuristic"] = round(heuristic, 4)

        metric_scores: list[tuple[float, float]] = [(heuristic, 0.5)]
        if self.config.comet_enabled:
            comet_score = self._comet(source, candidate, reference)
            metrics["comet_qe"] = round(comet_score, 4)
            metric_scores.append((comet_score, 0.5))

        if reference is not None:
            from sacrebleu import sentence_bleu, sentence_chrf

            chrf = sentence_chrf(candidate, [reference], word_order=2).score / 100.0
            bleu = sentence_bleu(candidate, [reference]).score / 100.0
            metrics["chrf++"] = round(chrf, 4)
            metrics["bleu"] = round(bleu, 4)
            # chrF++ is more stable than sentence BLEU; BLEU is reported but lightly weighted.
            metric_scores.extend(((chrf, 0.3), (bleu, 0.1)))

        total_weight = sum(weight for _, weight in metric_scores)
        final_score = sum(value * weight for value, weight in metric_scores) / total_weight
        if final_score < self.config.threshold:
            issues.append(
                f"quality score {final_score:.3f} is below threshold {self.config.threshold:.3f}"
            )
        return round(final_score, 4), metrics, _unique(issues)

    def _comet(self, source: str, candidate: str, reference: str | None) -> float:
        if self._comet_model is None:
            try:
                import torch
                from comet import download_model, load_from_checkpoint
            except ImportError as exc:
                raise RuntimeError(
                    "COMET is enabled but not installed. Run: pip install -e '.[comet]'"
                ) from exc
            checkpoint = download_model(self.config.comet_model)
            self._comet_model = load_from_checkpoint(checkpoint)
            self._comet_gpus = 1 if torch.cuda.is_available() else 0
        row = {"src": source, "mt": candidate}
        if reference is not None:
            row["ref"] = reference
        prediction = self._comet_model.predict(
            [row], batch_size=1, gpus=self._comet_gpus, progress_bar=False
        )
        raw_score = float(prediction.system_score)
        return max(0.0, min(1.0, raw_score))


def _content_units(value: str) -> list[str]:
    words = re.findall(r"\w+", value, flags=re.UNICODE)
    return words if len(words) > 1 else [char for char in value if not char.isspace()]


def _repetition_ratio(value: str) -> float:
    tokens = re.findall(r"\w+", value.casefold(), flags=re.UNICODE)
    if len(tokens) < 6:
        return 0.0
    trigrams = [tuple(tokens[index : index + 3]) for index in range(len(tokens) - 2)]
    return 1.0 - (len(set(trigrams)) / len(trigrams))


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))
