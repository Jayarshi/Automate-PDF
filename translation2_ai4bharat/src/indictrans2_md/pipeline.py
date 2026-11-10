from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .consistency import OllamaConsistency
from .engines import IndicTrans2
from .languages import detect_source, target_language
from .markdown import detection_text, markdown_chunks, protect_markdown, restore_markdown


class Translator(Protocol):
    def count_tokens(self, text: str) -> int: ...

    def translate(self, text: str) -> str: ...


class ConsistencyEditor(Protocol):
    def edit(
        self, source: str, draft: str, source_language: str, target_language: str,
        glossary: dict[str, str], context: str,
    ) -> tuple[str, dict[str, str]]: ...


def translate_markdown(
    source_path: Path,
    target: str,
    output_path: Path | None = None,
    device: str = "auto",
    use_llm: bool = True,
    model: str = "qwen2.5:3b-instruct",
    ollama_url: str = "http://127.0.0.1:11434",
    translator: Translator | None = None,
    editor: ConsistencyEditor | None = None,
) -> Path:
    source_text = source_path.read_text(encoding="utf-8")
    if not source_text.strip():
        raise ValueError("Input Markdown file is empty.")
    source_code, source_name, confidence = detect_source(detection_text(source_text))
    target_code, target_name, target_label = target_language(target)
    if output_path is not None and output_path.resolve() == source_path.resolve():
        raise ValueError("Output path must not be the same as the input file.")
    if source_code == target_code:
        raise ValueError(f"Detected source language and target ({target_name}) are the same.")
    translator = translator or IndicTrans2(source_code, target_code, device)
    if use_llm and editor is None:
        editor = OllamaConsistency(model=model, base_url=ollama_url)

    chunks = markdown_chunks(source_text, translator.count_tokens)
    glossary: dict[str, str] = {}
    translated: list[str] = []
    for index, chunk in enumerate(chunks):
        if not chunk.translatable or not chunk.text.strip():
            translated.append(chunk.text)
            continue
        protected, replacements = protect_markdown(chunk.text)
        draft = translator.translate(protected)
        draft = restore_markdown(draft, replacements)
        if editor:
            context = "\n\n".join(
                item.text
                for item in chunks[max(0, index - 1): index] + chunks[index + 1:index + 2]
                if item.translatable
            )
            protected_draft, draft_tokens = protect_markdown(draft)
            edited, updates = editor.edit(
                chunk.text, protected_draft, source_name, target_name, glossary, context
            )
            draft = restore_markdown(edited, draft_tokens)
            # Previously established terms are immutable for this run.
            for source_term, target_term in updates.items():
                if source_term in chunk.text and target_term in draft:
                    glossary.setdefault(source_term, target_term)
        translated.append(draft)

    if output_path is None:
        label = "".join(
            character if character.isalnum() or character in "-_" else "-"
            for character in target_label.lower()
        ).strip("-")
        output_path = source_path.with_name(f"{source_path.stem}_{label}.md")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("".join(translated), encoding="utf-8")
    print(
        f"Detected {source_name} ({confidence:.0%} confidence); translating to "
        f"{target_name} using IndicTrans2."
    )
    return output_path
