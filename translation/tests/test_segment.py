from local_nllb.config import SegmentConfig
from local_nllb.segment import Segmenter


def test_preserves_paragraph_boundaries() -> None:
    parts = Segmenter(SegmentConfig()).segment("One. Two.\n\nThree!", "eng_Latn")
    assert [item.text for item in parts] == ["One.", "Two.", "Three!"]
    assert [item.separator for item in parts] == [" ", "\n\n", ""]


def test_splits_long_segments_to_token_limit() -> None:
    segmenter = Segmenter(SegmentConfig(max_source_tokens=8), lambda text: len(text.split()))
    parts = segmenter.segment("one two three four five six seven eight nine ten", "eng_Latn")
    assert len(parts) == 2
    assert all(len(item.text.split()) <= 8 for item in parts)
