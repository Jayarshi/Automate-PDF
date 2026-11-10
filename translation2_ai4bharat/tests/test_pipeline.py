from pathlib import Path

from indictrans2_md.pipeline import translate_markdown


class FakeTranslator:
    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def translate(self, text: str) -> str:
        return text.replace("Hello", "नमस्ते").replace("World", "दुनिया")


class FakeEditor:
    def edit(self, source, draft, source_language, target_language, glossary, context):
        assert source_language == "English"
        assert target_language == "Hindi"
        return draft, {"World": "दुनिया"}


def test_outputs_markdown_with_target_suffix_and_preserves_code(tmp_path: Path) -> None:
    source = tmp_path / "guide.md"
    source.write_text("# Hello World\n\nHello World.\n\n```py\nprint('Hello')\n```\n", encoding="utf-8")
    output = translate_markdown(
        source, "hi", use_llm=True, translator=FakeTranslator(), editor=FakeEditor()
    )
    assert output.name == "guide_hi.md"
    result = output.read_text(encoding="utf-8")
    assert "# नमस्ते दुनिया" in result
    assert "नमस्ते दुनिया." in result
    assert "print('Hello')" in result
