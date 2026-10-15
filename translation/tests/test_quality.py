from local_nllb.config import QualityConfig
from local_nllb.quality import QualityEvaluator


def test_missing_glossary_term_fails_strict_gate() -> None:
    evaluator = QualityEvaluator(QualityConfig(threshold=0.9))
    score, _, issues = evaluator.evaluate(
        "Use the quality gate now", "अब जाँच करें", {"quality gate": "गुणवत्ता जाँच"}
    )
    assert score < 0.9
    assert "missing glossary term: गुणवत्ता जाँच" in issues


def test_empty_translation_scores_zero() -> None:
    score, metrics, issues = QualityEvaluator(QualityConfig()).evaluate("hello", "")
    assert score == 0
    assert metrics["heuristic"] == 0
    assert "empty translation" in issues
