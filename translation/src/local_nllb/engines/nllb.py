from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import NLLBConfig


class NLLBEngine:
    """CTranslate2 NLLB inference with a Hugging Face tokenizer."""

    def __init__(self, config: NLLBConfig) -> None:
        self.config = config
        self._translator: Any = None
        self._tokenizer: Any = None

    def load(self) -> None:
        if self._translator is not None:
            return
        model_path = Path(self.config.model_path)
        tokenizer_path = Path(self.config.tokenizer)
        missing_local_tokenizer = (
            self.config.tokenizer.startswith("models/") and not tokenizer_path.is_dir()
        )
        if not model_path.is_dir() or missing_local_tokenizer:
            raise RuntimeError(
                "NLLB model is not installed. Run: .venv/bin/python scripts/setup_model.py"
            )

        import ctranslate2
        from transformers import AutoTokenizer

        try:
            self._tokenizer = AutoTokenizer.from_pretrained(self.config.tokenizer)
            kwargs: dict[str, Any] = {
                "device": self.config.device,
                "compute_type": self.config.compute_type,
            }
            if self.config.cpu_threads > 0:
                kwargs["intra_threads"] = self.config.cpu_threads
            self._translator = ctranslate2.Translator(self.config.model_path, **kwargs)
        except (OSError, RuntimeError, ValueError) as exc:
            raise RuntimeError(
                f"Could not load CTranslate2 model at '{self.config.model_path}'. "
                "Run .venv/bin/python scripts/setup_model.py and check device/compute_type."
            ) from exc

    def count_tokens(self, text: str) -> int:
        self.load()
        return len(self._tokenizer.encode(text, add_special_tokens=False))

    def translate_batch(
        self,
        texts: list[str],
        source_lang: str,
        target_lang: str,
        beam_size: int | None = None,
    ) -> list[str]:
        if not texts:
            return []
        self.load()
        self._tokenizer.src_lang = source_lang
        token_batches = [
            self._tokenizer.convert_ids_to_tokens(self._tokenizer.encode(text)) for text in texts
        ]
        results = self._translator.translate_batch(
            token_batches,
            target_prefix=[[target_lang] for _ in texts],
            beam_size=beam_size or self.config.beam_size,
            max_decoding_length=self.config.max_decoding_length,
        )
        translations: list[str] = []
        for result in results:
            tokens = list(result.hypotheses[0])
            if tokens and tokens[0] == target_lang:
                tokens = tokens[1:]
            token_ids = self._tokenizer.convert_tokens_to_ids(tokens)
            translations.append(self._tokenizer.decode(token_ids, skip_special_tokens=True).strip())
        return translations
