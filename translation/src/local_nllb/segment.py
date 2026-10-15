from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .config import SegmentConfig


@dataclass(slots=True)
class TextSegment:
    text: str
    separator: str = " "
    prefix: str = ""


class Segmenter:
    """Sentence segmentation and token splitting without changing source layout."""

    def __init__(
        self,
        config: SegmentConfig,
        token_counter: Callable[[str], int] | None = None,
    ) -> None:
        self.config = config
        self.token_counter = token_counter or (lambda value: len(value.split()))

    def segment(self, text: str, language: str) -> list[TextSegment]:
        if not text.strip():
            return []

        result: list[TextSegment] = []
        pending_prefix = ""
        # Splitting on every line ending makes a single newline just as significant
        # as a blank line. The captured delimiters are attached to translated chunks.
        for part in re.split(r"(\r\n|\r|\n)", text):
            if not part:
                continue
            if part in {"\r\n", "\r", "\n"}:
                if result:
                    result[-1].separator += part
                else:
                    pending_prefix += part
                continue
            if not part.strip():
                if result:
                    result[-1].separator += part
                else:
                    pending_prefix += part
                continue

            leading = part[: len(part) - len(part.lstrip(" \t\f\v"))]
            trailing = part[len(part.rstrip(" \t\f\v")) :]
            content_end = len(part) - len(trailing) if trailing else len(part)
            content = part[len(leading) : content_end]
            sentences = self._sentences(content, language)
            expanded = [piece for sentence in sentences for piece in self._split_long(sentence)]
            for index, sentence in enumerate(expanded):
                prefix = pending_prefix + leading if index == 0 else ""
                separator = " " if index < len(expanded) - 1 else trailing
                result.append(TextSegment(sentence, separator, prefix))
            pending_prefix = ""

        if pending_prefix and result:
            result[-1].separator += pending_prefix
        return result

    def batches(self, segments: list[TextSegment]) -> Iterable[list[TextSegment]]:
        size = max(1, self.config.batch_size)
        for start in range(0, len(segments), size):
            yield segments[start : start + size]

    def _sentences(self, text: str, language: str) -> list[str]:
        backend = self.config.backend.lower()
        try:
            if backend == "spacy":
                import spacy

                nlp = (
                    spacy.load(self.config.spacy_model)
                    if self.config.spacy_model
                    else spacy.blank(_spacy_code(language))
                )
                if not nlp.pipe_names:
                    nlp.add_pipe("sentencizer")
                return [sent.text.strip() for sent in nlp(text).sents if sent.text.strip()]
            if backend == "nltk":
                from nltk.tokenize import sent_tokenize

                return [item.strip() for item in sent_tokenize(text) if item.strip()]
            if backend == "sacremoses":
                from sacremoses import MosesSentenceSplitter

                splitter = MosesSentenceSplitter(lang=_iso_code(language))
                return [item.strip() for item in splitter([text]) if item.strip()]
            if backend != "regex":
                raise ValueError(f"Unknown segmentation backend: {backend}")
        except (ImportError, LookupError, OSError) as exc:
            raise RuntimeError(
                f"Segmentation backend '{backend}' is not ready: {exc}. "
                "Install its optional dependency/model or use backend: regex."
            ) from exc
        # Includes common Indic sentence terminators and CJK punctuation.
        return [
            item.strip()
            for item in re.split(r"(?<=[.!?。！？।])(?:\s+|(?=[^\s]))", text)
            if item.strip()
        ]

    def _split_long(self, sentence: str) -> list[str]:
        limit = max(8, self.config.max_source_tokens)
        if self.token_counter(sentence) <= limit:
            return [sentence]
        units = sentence.split()
        joiner = " "
        if len(units) == 1:
            units = list(sentence)
            joiner = ""
        chunks: list[str] = []
        current: list[str] = []
        for unit in units:
            proposal = joiner.join([*current, unit])
            if current and self.token_counter(proposal) > limit:
                chunks.append(joiner.join(current))
                current = [unit]
            else:
                current.append(unit)
        if current:
            chunks.append(joiner.join(current))
        return chunks


def _iso_code(language: str) -> str:
    aliases = {"eng": "en", "fra": "fr", "deu": "de", "spa": "es", "zho": "zh"}
    prefix = language.split("_", 1)[0].lower()
    return aliases.get(prefix, prefix[:2])


def _spacy_code(language: str) -> str:
    code = _iso_code(language)
    # spaCy supports xx as a multilingual blank tokenizer.
    return code if code in {"en", "de", "fr", "es", "it", "nl", "pt", "zh", "ja"} else "xx"
