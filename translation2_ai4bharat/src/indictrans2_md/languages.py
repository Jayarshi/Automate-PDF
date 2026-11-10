from __future__ import annotations

from langdetect import DetectorFactory, detect_langs
from langdetect.lang_detect_exception import LangDetectException

DetectorFactory.seed = 0

LANGUAGES = {
    "as": ("asm_Beng", "Assamese"),
    "assamese": ("asm_Beng", "Assamese"),
    "bn": ("ben_Beng", "Bengali"),
    "bengali": ("ben_Beng", "Bengali"),
    "brx": ("brx_Deva", "Bodo"),
    "bodo": ("brx_Deva", "Bodo"),
    "doi": ("doi_Deva", "Dogri"),
    "dogri": ("doi_Deva", "Dogri"),
    "gom": ("gom_Deva", "Konkani"),
    "konkani": ("gom_Deva", "Konkani"),
    "gu": ("guj_Gujr", "Gujarati"),
    "gujarati": ("guj_Gujr", "Gujarati"),
    "hi": ("hin_Deva", "Hindi"),
    "hindi": ("hin_Deva", "Hindi"),
    "kn": ("kan_Knda", "Kannada"),
    "kannada": ("kan_Knda", "Kannada"),
    "ks": ("kas_Arab", "Kashmiri"),
    "kashmiri": ("kas_Arab", "Kashmiri"),
    "mai": ("mai_Deva", "Maithili"),
    "maithili": ("mai_Deva", "Maithili"),
    "ml": ("mal_Mlym", "Malayalam"),
    "malayalam": ("mal_Mlym", "Malayalam"),
    "mr": ("mar_Deva", "Marathi"),
    "marathi": ("mar_Deva", "Marathi"),
    "mni": ("mni_Mtei", "Manipuri"),
    "manipuri": ("mni_Mtei", "Manipuri"),
    "ne": ("npi_Deva", "Nepali"),
    "nepali": ("npi_Deva", "Nepali"),
    "or": ("ory_Orya", "Odia"),
    "odia": ("ory_Orya", "Odia"),
    "pa": ("pan_Guru", "Punjabi"),
    "punjabi": ("pan_Guru", "Punjabi"),
    "sa": ("san_Deva", "Sanskrit"),
    "sanskrit": ("san_Deva", "Sanskrit"),
    "sat": ("sat_Olck", "Santali"),
    "santali": ("sat_Olck", "Santali"),
    "sd": ("snd_Arab", "Sindhi"),
    "sindhi": ("snd_Arab", "Sindhi"),
    "ta": ("tam_Taml", "Tamil"),
    "tamil": ("tam_Taml", "Tamil"),
    "te": ("tel_Telu", "Telugu"),
    "telugu": ("tel_Telu", "Telugu"),
    "ur": ("urd_Arab", "Urdu"),
    "urdu": ("urd_Arab", "Urdu"),
    "en": ("eng_Latn", "English"),
    "english": ("eng_Latn", "English"),
}

DETECTOR_CODES = {
    "af": "af", "ar": "ar", "bg": "bg", "bn": "bn", "ca": "ca", "cs": "cs",
    "da": "da", "de": "de", "el": "el", "en": "en", "es": "es", "et": "et",
    "fa": "fa", "fi": "fi", "fr": "fr", "gu": "gu", "he": "he", "hi": "hi",
    "hr": "hr", "hu": "hu", "id": "id", "it": "it", "ja": "ja", "kn": "kn",
    "ko": "ko", "lt": "lt", "lv": "lv", "mk": "mk", "ml": "ml", "mr": "mr",
    "ne": "ne", "nl": "nl", "no": "no", "pa": "pa", "pl": "pl", "pt": "pt",
    "ro": "ro", "ru": "ru", "sk": "sk", "sl": "sl", "so": "so", "sq": "sq",
    "sv": "sv", "sw": "sw", "ta": "ta", "te": "te", "th": "th", "tl": "tl",
    "tr": "tr", "uk": "uk", "ur": "ur", "vi": "vi", "zh-cn": "zh-cn",
}


def target_language(value: str) -> tuple[str, str, str]:
    result = LANGUAGES.get(value.strip().lower())
    if not result:
        raise ValueError(f"Unsupported IndicTrans2 target language: {value}")
    code, name = result
    return code, name, value.strip()


def detect_source(text: str) -> tuple[str, str, float]:
    sample = text.strip()
    if len(sample) < 20:
        raise ValueError("Not enough text to detect the source language (need at least 20 characters).")
    try:
        prediction = detect_langs(sample)[0]
    except LangDetectException as exc:
        raise ValueError(f"Could not detect the source language: {exc}") from exc
    language = DETECTOR_CODES.get(prediction.lang)
    if language is None or language not in LANGUAGES:
        raise ValueError(
            f"Detected language '{prediction.lang}' is not supported by this IndicTrans2 setup."
        )
    if prediction.prob < 0.60:
        raise ValueError(
            f"Source language detection is uncertain ({prediction.lang}: "
            f"{prediction.prob:.0%}); provide a longer, single-language Markdown file."
        )
    code, name = LANGUAGES[language]
    return code, name, prediction.prob
