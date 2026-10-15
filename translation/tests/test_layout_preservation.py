from local_nllb.config import AppConfig, QualityConfig, SegmentConfig
from local_nllb.pipeline import TranslationPipeline
from local_nllb.segment import Segmenter
from local_nllb.types import TranslationRequest


class LayoutEngine:
    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def translate_batch(self, texts, source_lang, target_lang, beam_size=None):
        return [f"T:{text}" for text in texts]


def test_segmenter_preserves_single_blank_and_trailing_line_breaks() -> None:
    source = "\n  First line.\r\nSecond line.\n\nFourth line.  \n"
    segments = Segmenter(SegmentConfig()).segment(source, "eng_Latn")
    rendered = "".join(item.prefix + f"T:{item.text}" + item.separator for item in segments)
    assert rendered == ("\n  T:First line.\r\nT:Second line.\n\nT:Fourth line.  \n")


def test_pipeline_preserves_each_source_line_break(tmp_path) -> None:
    source = "First paragraph.\nSecond paragraph.\n\nFinal paragraph.\n"
    config = AppConfig(
        segmentation=SegmentConfig(batch_size=8),
        quality=QualityConfig(
            threshold=0.5,
            retry_threshold=0.5,
            review_path=str(tmp_path / "review.jsonl"),
        ),
    )
    result = TranslationPipeline(config, engine=LayoutEngine()).translate(
        TranslationRequest(source, "en", "fr")
    )
    assert result.text == ("T:First paragraph.\nT:Second paragraph.\n\nT:Final paragraph.\n")
    assert result.text.count("\n") == source.count("\n")
