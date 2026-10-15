from local_nllb.config import QualityConfig
from local_nllb.numbers import extract_numbers
from local_nllb.protect import TextProtector
from local_nllb.quality import QualityEvaluator


def test_short_numbers_are_normalized_without_placeholders() -> None:
    protected = TextProtector().protect("২০২১ সালে ৫০% এবং ১২২৭টি পদ", {})
    assert protected.text == "2021 সালে 50% এবং 1227টি পদ"
    assert protected.replacements == {}


def test_numbers_are_extracted_when_followed_by_bengali_suffixes() -> None:
    assert list(extract_numbers("২০২১-এ ১২২৭টি পদ").elements()) == ["2021", "1227"]


def test_translated_spelled_out_number_may_become_digits() -> None:
    evaluator = QualityEvaluator(QualityConfig())
    _, metrics, issues = evaluator.evaluate("সাতটা পদ", "7 positions")
    assert metrics["numbers_preserved"] == 1.0
    assert not any(issue.startswith("number mismatch:") for issue in issues)
