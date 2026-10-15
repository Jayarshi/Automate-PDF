from local_nllb.config import QualityConfig
from local_nllb.numbers import ascii_digits, extract_numbers
from local_nllb.protect import TextProtector
from local_nllb.quality import QualityEvaluator


def test_bengali_phone_number_is_protected_and_normalized() -> None:
    protected = TextProtector().protect("যোগাযোগ: ৯৮৩৬২২১৮১৮", {})
    assert protected.text == "যোগাযোগ: <x0>"
    assert protected.replacements == {"<x0>": "9836221818"}
    restored, issues = protected.restore("Contact number: <x0>")
    assert restored == "Contact number: 9836221818"
    assert issues == []


def test_unicode_numbers_normalize_without_changing_punctuation() -> None:
    assert ascii_digits("২০২১, ৫০%, ৭:০০") == "2021, 50%, 7:00"
    assert extract_numbers("২০২১ সালে ৫০%") == extract_numbers("In 2021 it was 50%")


def test_quality_gate_rejects_missing_phone_digits() -> None:
    evaluator = QualityEvaluator(QualityConfig(threshold=0.72))
    score, metrics, issues = evaluator.evaluate("যোগাযোগ: ৯৮৩৬২২১৮১৮", "Contact number: 98362218")
    assert score < 0.72
    assert metrics["numbers_preserved"] == 0.0
    assert any(issue.startswith("number mismatch:") for issue in issues)


def test_quality_gate_accepts_script_normalized_number() -> None:
    evaluator = QualityEvaluator(QualityConfig())
    _, metrics, issues = evaluator.evaluate("যোগাযোগ: ৯৮৩৬২২১৮১৮", "Contact number: 9836221818")
    assert metrics["numbers_preserved"] == 1.0
    assert not any(issue.startswith("number mismatch:") for issue in issues)
