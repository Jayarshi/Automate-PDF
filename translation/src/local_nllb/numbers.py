from __future__ import annotations

import re
import unicodedata
from collections import Counter

# Python's \d is Unicode-aware, so numeric prefixes are found even when a language-specific
# suffix immediately follows (for example Bengali "১২২৭টি"). A separator is included only
# when another digit follows it, which avoids consuming ordinary trailing punctuation.
NUMBER_PATTERN = re.compile(r"\+?\d+(?:[ \u00a0.,:/-]\d+)*%?")


def ascii_digits(value: str) -> str:
    """Convert Unicode decimal digits to ASCII without altering other characters."""
    converted: list[str] = []
    for character in value:
        try:
            converted.append(str(unicodedata.decimal(character)))
        except (TypeError, ValueError):
            converted.append(character)
    return "".join(converted)


def extract_numbers(value: str) -> Counter[str]:
    """Return normalized numeric tokens as a multiset for order-independent validation."""
    return Counter(
        ascii_digits(match.group()).replace("\u00a0", " ")
        for match in NUMBER_PATTERN.finditer(value)
    )
