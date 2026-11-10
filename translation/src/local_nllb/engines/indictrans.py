"""Lazy Hugging Face IndicTrans2 adapter; no NLLB fallback."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..languages import resolve_language

INDIC_CODES = {
    "asm_Beng",
    "ben_Beng",
    "brx_Deva",
    "doi_Deva",
    "gom_Deva",
    "guj_Gujr",
    "hin_Deva",
    "kan_Knda",
    "kas_Arab",
    "kas_Deva",
    "mai_Deva",
    "mal_Mlym",
    "mar_Deva",
    "mni_Beng",
    "mni_Mtei",
    "npi_Deva",
    "ory_Orya",
    "pan_Guru",
    "san_Deva",
    "sat_Olck",
    "snd_Arab",
    "snd_Deva",
    "tam_Taml",
    "tel_Telu",
    "urd_Arab",
}
ALIASES = dict(
    zip(
        ["as", "brx", "doi", "kok", "kn", "ks", "mai", "mni", "sa", "sat", "sd"],
        [
            "asm_Beng",
            "brx_Deva",
            "doi_Deva",
            "gom_Deva",
            "kan_Knda",
            "kas_Arab",
            "mai_Deva",
            "mni_Mtei",
            "san_Deva",
            "sat_Olck",
            "snd_Arab",
        ],
    )
)


def language_pair(source: str, target: str) -> tuple[str, str, str]:
    source, target = (ALIASES.get(x.lower(), resolve_language(x)) for x in (source, target))
    for code in (source, target):
        if code not in INDIC_CODES | {"eng_Latn"}:
            raise ValueError(f"IndicTrans2 does not support language: {code}")
    if source == target:
        raise ValueError("Source and target languages must be different")
    direction = (
        "en_indic"
        if source == "eng_Latn"
        else ("indic_en" if target == "eng_Latn" else "indic_indic")
    )
    return source, target, direction


@dataclass
class IndicTransConfig:
    en_indic: str = "ai4bharat/indictrans2-en-indic-1B"
    indic_en: str = "ai4bharat/indictrans2-indic-en-1B"
    indic_indic: str = "ai4bharat/indictrans2-indic-indic-1B"
    device: str = "auto"
    beam_size: int = 5
    max_source_tokens: int = 256
    max_decoding_length: int = 256
    local_files_only: bool = False


class IndicTransEngine:
    def __init__(self, config: IndicTransConfig, source: str, target: str):
        self.config = config
        self.source, self.target, self.direction = language_pair(source, target)
        self.model: Any = None

    def _load(self):
        if self.model is not None:
            return
        try:
            import torch
            from IndicTransToolkit import IndicProcessor
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        except ImportError as exc:
            raise RuntimeError(
                "Install the indictrans extra and IndicTransToolkit; see README."
            ) from exc
        checkpoint = getattr(self.config, self.direction)
        self.device = (
            ("cuda" if torch.cuda.is_available() else "cpu")
            if (self.config.device == "auto")
            else self.config.device
        )
        kwargs = {"trust_remote_code": True, "local_files_only": self.config.local_files_only}
        self.tokenizer = AutoTokenizer.from_pretrained(checkpoint, **kwargs)
        model = AutoModelForSeq2SeqLM.from_pretrained(checkpoint, **kwargs).to(self.device)
        if self.device.startswith("cuda"):
            model.half()
        self.processor = IndicProcessor(inference=True)
        self.model = model.eval()

    def count_tokens(self, text: str) -> int:
        self._load()
        batch = self.processor.preprocess_batch([text], src_lang=self.source, tgt_lang=self.target)
        return len(self.tokenizer(batch[0], truncation=False)["input_ids"])

    def translate_batch(self, texts, source_lang, target_lang, beam_size=None):
        if (source_lang, target_lang) != (self.source, self.target):
            raise ValueError("Engine language pair differs from requested pair")
        self._load()
        import torch

        batch = self.processor.preprocess_batch(texts, src_lang=source_lang, tgt_lang=target_lang)
        inputs = self.tokenizer(batch, padding=True, truncation=False, return_tensors="pt")
        if inputs["input_ids"].shape[1] > self.config.max_source_tokens:
            raise ValueError(
                "Sentence exceeds IndicTrans2 token limit; split it manually before retrying"
            )
        with torch.inference_mode():
            ids = self.model.generate(
                **inputs.to(self.device),
                num_beams=beam_size or self.config.beam_size,
                max_length=self.config.max_decoding_length,
                num_return_sequences=1,
            )
        decoded = self.tokenizer.batch_decode(ids, skip_special_tokens=True)
        return self.processor.postprocess_batch(decoded, lang=target_lang)
