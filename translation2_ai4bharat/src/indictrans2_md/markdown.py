from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Chunk:
    text: str
    translatable: bool


_FENCED_CODE = re.compile(r"(?ms)^(`{3,}|~{3,})[^\n]*\n.*?^\1[ \t]*$")
_FRONT_MATTER = re.compile(r"\A---[ \t]*\n.*?\n---[ \t]*(?:\n[ \t]*\n*|\Z)", re.DOTALL)
_PARAGRAPH_SPLIT = re.compile(r"(\n[ \t]*\n+)")
_HEADING = re.compile(r"(?m)^\s{0,3}#{1,6}\s")


def detection_text(text: str) -> str:
    text = _FRONT_MATTER.sub(" ", text, count=1)
    text = _FENCED_CODE.sub(" ", text)
    text = re.sub(r"`+[^`\n]*`+", " ", text)
    text = re.sub(r"https?://[^\s)>]+", " ", text)
    text = re.sub(r"<[^>\n]+>", " ", text)
    text = re.sub(r"(?m)^\s{0,3}(?:#{1,6}\s+|>\s?|[-+*]\s+|\d+[.)]\s+)", " ", text)
    return text


def markdown_chunks(
    text: str, token_count: Callable[[str], int], max_tokens: int = 220
) -> list[Chunk]:
    """Group adjacent Markdown paragraphs without splitting headings or code blocks."""
    pieces: list[Chunk] = []
    protected_ranges: list[tuple[int, int]] = []
    for pattern in (_FRONT_MATTER, _FENCED_CODE):
        for match in pattern.finditer(text):
            protected_ranges.append(match.span())
    protected_ranges.sort()

    spans = _paragraph_spans(text)
    for start, end in spans:
        boundaries = {start, end}
        for protected_start, protected_end in protected_ranges:
            if start < protected_start < end:
                boundaries.add(protected_start)
            if start < protected_end < end:
                boundaries.add(protected_end)
        ordered = sorted(boundaries)
        for left, right in zip(ordered, ordered[1:]):
            is_protected = any(
                protected_start <= left and right <= protected_end
                for protected_start, protected_end in protected_ranges
            )
            pieces.append(Chunk(text[left:right], not is_protected))

    result: list[Chunk] = []
    pending = ""

    def flush() -> None:
        nonlocal pending
        if pending:
            result.append(Chunk(pending, True))
            pending = ""

    for piece in pieces:
        if not piece.translatable:
            flush()
            result.append(piece)
            continue
        segments = _split_at_headings(piece.text)
        for segment in segments:
            if _HEADING.match(segment):
                flush()
            candidate = pending + segment
            if pending and token_count(candidate) > max_tokens:
                flush()
                candidate = segment
            if token_count(candidate) > max_tokens:
                subchunks = _split_oversized(segment, token_count, max_tokens)
                if any(token_count(value) > max_tokens for value in subchunks):
                    raise ValueError(
                        "A single unbroken Markdown token exceeds the IndicTrans2 input limit; "
                        "split or reformat it in the source."
                    )
                result.extend(Chunk(value, True) for value in subchunks[:-1])
                pending = subchunks[-1]
            else:
                pending = candidate
            if _HEADING.match(segment):
                flush()
    flush()
    return result


def _paragraph_spans(text: str) -> list[tuple[int, int]]:
    spans = []
    start = 0
    for match in _PARAGRAPH_SPLIT.finditer(text):
        if match.start() > start:
            spans.append((start, match.start()))
        spans.append(match.span())
        start = match.end()
    if start < len(text):
        spans.append((start, len(text)))
    return spans


def _split_at_headings(text: str) -> list[str]:
    starts = [match.start() for match in _HEADING.finditer(text)]
    if not starts:
        return [text]
    boundaries = [0, *[start for start in starts if start > 0], len(text)]
    return [text[left:right] for left, right in zip(boundaries, boundaries[1:]) if left < right]


def _split_oversized(
    text: str, token_count: Callable[[str], int], max_tokens: int
) -> list[str]:
    sentences = re.split(r"(?<=[.!?।॥])(\s+)", text)
    units = []
    for index in range(0, len(sentences), 2):
        units.append(sentences[index])
        if index + 1 < len(sentences):
            units.append(sentences[index + 1])
    parts: list[str] = []
    current = ""
    for unit in units:
        candidate = current + unit
        if current and token_count(candidate) > max_tokens:
            parts.append(current)
            current = unit
        else:
            current = candidate
    if current:
        parts.append(current)
    if any(token_count(part) > max_tokens for part in parts):
        smaller: list[str] = []
        for part in parts:
            if token_count(part) <= max_tokens:
                smaller.append(part)
                continue
            units = re.split(r"(\s+)", part)
            current = ""
            for unit in units:
                if current and token_count(current + unit) > max_tokens:
                    smaller.append(current)
                    current = ""
                current += unit
            if current:
                smaller.append(current)
        parts = smaller
    return parts


_MARKDOWN_TOKEN = re.compile(
    r"(\r\n|\r|\n|`+[^`\n]*`+|https?://[^\s)>]+|(?<=\]\()[^)\s]+|<[^>\n]+>|"
    r"(?m:^[ \t]{0,3}(?:#{1,6}[ \t]+|>[ \t]?|[-+*][ \t]+|\d+[.)][ \t]+))|"
    r"(?m:^[ \t]*\|)|(?m:^[ \t]*(?:[-*_][ \t]*){3,}$)|"
    r"\|{1,2}|[*_~]{1,3}|!\[|\]\(|\)|\[|\])"
)


def protect_markdown(text: str) -> tuple[str, dict[str, str]]:
    replacements: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        token = f"ZXQMARKDOWN{len(replacements)}QXZ"
        replacements[token] = match.group()
        return token

    return _MARKDOWN_TOKEN.sub(replace, text), replacements


def restore_markdown(text: str, replacements: dict[str, str]) -> str:
    for token, original in replacements.items():
        if text.count(token) != 1:
            raise RuntimeError(f"IndicTrans2 changed or dropped Markdown token {token}.")
        text = text.replace(token, original)
    return text
