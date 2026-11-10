from __future__ import annotations

from typing import Any


class IndicTrans2:
    def __init__(self, source: str, target: str, device: str = "auto") -> None:
        self.source = source
        self.target = target
        self.device = device
        self.model: Any = None

    def _load(self) -> None:
        if self.model is not None:
            return
        try:
            import torch
            from IndicTransToolkit import IndicProcessor
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        except ImportError as exc:
            raise RuntimeError(
                "IndicTrans2 dependencies are missing. Install this folder with "
                "'python -m pip install -e .'."
            ) from exc
        if self.source == self.target:
            raise ValueError("The detected source language and target language are identical.")
        direction = (
            "en-indic" if self.source == "eng_Latn"
            else "indic-en" if self.target == "eng_Latn"
            else "indic-indic"
        )
        self.checkpoint = f"ai4bharat/indictrans2-{direction}-1B"
        self.device = (
            ("cuda" if torch.cuda.is_available() else "cpu")
            if self.device == "auto" else self.device
        )
        kwargs = {"trust_remote_code": True}
        self.tokenizer = AutoTokenizer.from_pretrained(self.checkpoint, **kwargs)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(self.checkpoint, **kwargs).to(self.device)
        if self.device.startswith("cuda"):
            self.model.half()
        self.processor = IndicProcessor(inference=True)
        self.model.eval()

    def count_tokens(self, text: str) -> int:
        self._load()
        prepared = self.processor.preprocess_batch(
            [text], src_lang=self.source, tgt_lang=self.target
        )
        return len(self.tokenizer(prepared[0], truncation=False)["input_ids"])

    def translate(self, text: str) -> str:
        self._load()
        import torch

        prepared = self.processor.preprocess_batch(
            [text], src_lang=self.source, tgt_lang=self.target
        )
        inputs = self.tokenizer(prepared, padding=True, truncation=False, return_tensors="pt")
        # The checkpoint's remote decoder expects legacy tuple caches. Transformers 4.57+
        # otherwise initializes an EncoderDecoderCache containing None tensors.
        self.model._supports_default_dynamic_cache = lambda: False
        with torch.inference_mode():
            generated = self.model.generate(
                **inputs.to(self.device),
                num_beams=5,
                max_length=256,
                num_return_sequences=1,
                use_cache=True,
            )
        decoded = self.tokenizer.batch_decode(generated, skip_special_tokens=True)
        return self.processor.postprocess_batch(decoded, lang=self.target)[0]
