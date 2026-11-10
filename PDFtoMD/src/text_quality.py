"""Lightweight Unicode-script and extracted-text quality detection."""

from __future__ import annotations

from collections import Counter
import unicodedata


SCRIPT_RANGES = {
    "bn": ((0x0980, 0x09FF),),
    "hi": ((0x0900, 0x097F),),
    "gu": ((0x0A80, 0x0AFF),),
    "pa": ((0x0A00, 0x0A7F),),
    "ta": ((0x0B80, 0x0BFF),),
    "te": ((0x0C00, 0x0C7F),),
    "kn": ((0x0C80, 0x0CFF),),
    "ml": ((0x0D00, 0x0D7F),),
    "or": ((0x0B00, 0x0B7F),),
    "ar": ((0x0600, 0x06FF), (0x0750, 0x077F)),
    "zh": ((0x3400, 0x4DBF), (0x4E00, 0x9FFF)),
}
ALIASES = {"ben": "bn", "eng": "en", "hin": "hi", "pan": "pa",
           "tam": "ta", "tel": "te", "kan": "kn", "mal": "ml",
           "ori": "or", "guj": "gu", "ara": "ar", "zho": "zh"}


def normalize_language(value: str | None) -> str | None:
    if value is None or value.lower() in {"", "auto"}:
        return None
    value = value.lower().replace("_", "-").split("-", 1)[0]
    return ALIASES.get(value, value)


def detect_text_quality(text: str) -> dict:
    counts = Counter()
    ascii_letters = symbols = letters = 0
    for char in text:
        point = ord(char)
        category = unicodedata.category(char)
        if category.startswith("L"):
            letters += 1
            if char.isascii():
                ascii_letters += 1
        if category in {"Sk", "Sm", "So"}:
            symbols += 1
        for language, ranges in SCRIPT_RANGES.items():
            if any(start <= point <= end for start, end in ranges):
                counts[language] += 1
                break

    visible = sum(not char.isspace() for char in text)
    symbol_ratio = symbols / max(1, visible)
    dominant, dominant_count = counts.most_common(1)[0] if counts else (None, 0)
    script_ratio = dominant_count / max(1, letters)
    latin_ratio = ascii_letters / max(1, letters)

    if len(text.strip()) < 100:
        usable, language, reason = False, None, "too little extracted text"
    elif symbol_ratio > 0.05 and script_ratio < 0.20:
        usable, language, reason = False, None, "symbol-heavy legacy/custom font encoding"
    elif dominant and script_ratio >= 0.20:
        usable, language, reason = True, dominant, f"dominant Unicode script: {dominant}"
    elif latin_ratio >= 0.70 and symbol_ratio < 0.02:
        usable, language, reason = True, "en", "predominantly Latin Unicode text"
    else:
        usable, language, reason = False, None, "no reliable Unicode script detected"
    return {
        "usable": usable, "language": language, "reason": reason,
        "characters": len(text), "letters": letters,
        "symbol_ratio": round(symbol_ratio, 4),
        "latin_ratio": round(latin_ratio, 4),
        "script_counts": dict(counts),
    }
