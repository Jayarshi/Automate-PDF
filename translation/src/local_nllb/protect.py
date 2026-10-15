from __future__ import annotations

import re
from dataclasses import dataclass, field

from .numbers import NUMBER_PATTERN, ascii_digits


@dataclass(slots=True)
class ProtectedText:
    text: str
    replacements: dict[str, str] = field(default_factory=dict)
    source_terms: dict[str, str] = field(default_factory=dict)

    def restore(self, translated: str) -> tuple[str, list[str]]:
        issues: list[str] = []
        for placeholder, value in self.replacements.items():
            number = placeholder.removeprefix("<x").removesuffix(">")
            # NLLB sometimes copies <x0> as x0 or adds spaces around its brackets.
            pattern = re.compile(rf"(?:<\s*)?x\s*{re.escape(number)}(?:\s*>)?", re.IGNORECASE)
            translated, count = pattern.subn(lambda _, replacement=value: replacement, translated)
            if count == 0:
                issues.append(f"missing protected value: {value}")
        return translated, issues


class TextProtector:
    """Protect glossaries/identifiers and normalize other Unicode numbers."""

    _structured = re.compile(r"https?://\S+|\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")

    def protect(self, text: str, glossary: dict[str, str]) -> ProtectedText:
        # start, end, original, target, use_placeholder
        matches: list[tuple[int, int, str, str, bool]] = []
        for match in self._structured.finditer(text):
            matches.append((match.start(), match.end(), match.group(), match.group(), True))
        for match in NUMBER_PATTERN.finditer(text):
            original = match.group()
            normalized = ascii_digits(original)
            digit_count = sum(character.isdigit() for character in original)
            # Long numeric identifiers (phone/account/postal-like values) must be copied
            # exactly. Shorter numbers are safer as normalized ASCII input to NLLB.
            matches.append((match.start(), match.end(), original, normalized, digit_count >= 7))
        for source, target in sorted(glossary.items(), key=lambda item: len(item[0]), reverse=True):
            if not source:
                continue
            pattern = re.compile(re.escape(source), re.IGNORECASE)
            for match in pattern.finditer(text):
                matches.append((match.start(), match.end(), match.group(), target, True))

        # Prefer the longest candidate at a position and reject overlaps.
        chosen: list[tuple[int, int, str, str, bool]] = []
        for candidate in sorted(matches, key=lambda item: (item[0], -(item[1] - item[0]))):
            if not chosen or candidate[0] >= chosen[-1][1]:
                chosen.append(candidate)

        replacements: dict[str, str] = {}
        source_terms: dict[str, str] = {}
        pieces: list[str] = []
        cursor = 0
        placeholder_index = 0
        for start, end, original, target, use_placeholder in chosen:
            pieces.append(text[cursor:start])
            if use_placeholder:
                placeholder = f"<x{placeholder_index}>"
                placeholder_index += 1
                pieces.append(placeholder)
                replacements[placeholder] = target
            else:
                pieces.append(target)
            if original != target:
                source_terms[original] = target
            cursor = end
        pieces.append(text[cursor:])
        return ProtectedText("".join(pieces), replacements, source_terms)
