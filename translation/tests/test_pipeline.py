import json

from local_nllb.config import AppConfig, QualityConfig, SegmentConfig
from local_nllb.engines.postedit import NoOpPostEditor
from local_nllb.pipeline import TranslationPipeline
from local_nllb.types import TranslationRequest


class FakeEngine:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = iter(outputs)
        self.calls: list[int | None] = []

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def translate_batch(
        self,
        texts: list[str],
        source_lang: str,
        target_lang: str,
        beam_size: int | None = None,
    ) -> list[str]:
        self.calls.append(beam_size)
        return [next(self.outputs) for _ in texts]


def test_pipeline_restores_glossary_and_resolves_languages(tmp_path) -> None:
    config = AppConfig(
        segmentation=SegmentConfig(batch_size=4),
        quality=QualityConfig(
            threshold=0.6, retry_threshold=0.6, review_path=str(tmp_path / "q.jsonl")
        ),
    )
    pipeline = TranslationPipeline(
        config, engine=FakeEngine(["नमस्ते <x0>."]), post_editor=NoOpPostEditor()
    )
    result = pipeline.translate(
        TranslationRequest("Hello OpenAI.", "en", "hi", glossary={"OpenAI": "ओपनएआई"})
    )
    assert result.text == "नमस्ते ओपनएआई."
    assert result.source_lang == "eng_Latn"
    assert result.target_lang == "hin_Deva"
    assert result.passed


def test_failed_first_attempt_retries_with_larger_beam(tmp_path) -> None:
    engine = FakeEngine(["", "Bonjour."])
    config = AppConfig(
        quality=QualityConfig(
            threshold=0.7,
            retry_threshold=0.7,
            max_retries=1,
            review_path=str(tmp_path / "q.jsonl"),
        )
    )
    result = TranslationPipeline(config, engine=engine).translate(
        TranslationRequest("Hello.", "en", "fr")
    )
    assert result.text == "Bonjour."
    assert result.segments[0].attempts == 2
    assert engine.calls == [None, 8]


def test_failure_is_written_to_review_queue(tmp_path) -> None:
    queue = tmp_path / "flagged.jsonl"
    config = AppConfig(
        quality=QualityConfig(
            threshold=0.95,
            retry_threshold=0.95,
            max_retries=0,
            review_path=str(queue),
        )
    )
    result = TranslationPipeline(config, engine=FakeEngine(["अनुवाद"])).translate(
        TranslationRequest("Use ACME.", "en", "hi", glossary={"ACME": "एक्मे"})
    )
    assert result.needs_review
    record = json.loads(queue.read_text(encoding="utf-8"))
    assert record["status"] == "pending_human_review"
    assert record["source"] == "Use ACME."
