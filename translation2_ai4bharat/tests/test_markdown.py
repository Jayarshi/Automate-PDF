from indictrans2_md.markdown import (
    detection_text,
    markdown_chunks,
    protect_markdown,
    restore_markdown,
)


def test_fenced_code_and_front_matter_are_not_translated() -> None:
    fence = chr(96) * 4
    text = (
        "---\ntitle: Hello\n---\n\n# Heading\n\n"
        + fence
        + "py\nprint('Hi')\n"
        + fence
        + "\n\nBody."
    )
    chunks = markdown_chunks(text, lambda value: len(value.split()))
    assert "".join(chunk.text for chunk in chunks) == text
    protected = [chunk.text for chunk in chunks if not chunk.translatable]
    assert "".join(protected[:2]) == "---\ntitle: Hello\n---\n\n"
    assert protected[2] == fence + "py\nprint('Hi')\n" + fence


def test_chunks_group_context_but_respect_token_limit_and_heading() -> None:
    text = "First paragraph.\n\nSecond paragraph.\n\n# Heading\n\nThird paragraph."
    chunks = markdown_chunks(text, lambda value: len(value.split()), max_tokens=5)
    assert "".join(chunk.text for chunk in chunks) == text
    assert len(chunks) >= 3
    assert all(len(chunk.text.split()) <= 5 for chunk in chunks if chunk.translatable)


def test_markdown_tokens_round_trip() -> None:
    text = "# A *heading* with `code` and [link](https://example.com)\n\nNext paragraph."
    protected, tokens = protect_markdown(text)
    assert restore_markdown(protected, tokens) == text


def test_detection_ignores_front_matter_and_code() -> None:
    text = "---\ntitle: हिन्दी\n---\n\nEnglish prose is used here for detection.\n\n```py\nprint('bonjour')\n```"
    assert "bonjour" not in detection_text(text)
    assert "English prose" in detection_text(text)
