from local_nllb.config import AppConfig, QualityConfig
from local_nllb.pipeline import TranslationPipeline
from local_nllb.types import TranslationRequest


class RetryEngine:
    def __init__(self) -> None:
        self.calls = 0

    def count_tokens(self, text: str) -> int:
        return 1

    def translate_batch(self, texts, source_lang, target_lang, beam_size=None):
        self.calls += 1
        return ["first candidate" if self.calls == 1 else "<x0> translated"]


class OrderedEvaluator:
    def evaluate(self, source, candidate, glossary=None, inherited_issues=None, reference=None):
        score = 0.9 if candidate == "first candidate" else 0.8
        return score, {"heuristic": score}, []


def test_passing_retry_wins_even_if_failed_candidate_had_higher_score(tmp_path) -> None:
    config = AppConfig(
        quality=QualityConfig(
            threshold=0.7,
            retry_threshold=0.7,
            max_retries=1,
            review_path=str(tmp_path / "review.jsonl"),
        )
    )
    result = TranslationPipeline(
        config, engine=RetryEngine(), evaluator=OrderedEvaluator()
    ).translate(TranslationRequest("ACME", "en", "fr", glossary={"ACME": "ACME"}))
    assert result.text == "ACME translated"
    assert result.passed
    assert result.segments[0].attempts == 2
