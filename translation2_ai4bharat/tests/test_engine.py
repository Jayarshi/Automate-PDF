import sys
from contextlib import nullcontext
from types import ModuleType

from indictrans2_md.engines import IndicTrans2


class TokenBatch(dict):
    def to(self, device: str) -> "TokenBatch":
        return self


class FakeTokenizer:
    def __call__(self, texts, **kwargs):
        return TokenBatch(input_ids=["encoded"])

    def batch_decode(self, generated, **kwargs):
        return ["draft"]


class FakeProcessor:
    def preprocess_batch(self, texts, **kwargs):
        return texts

    def postprocess_batch(self, texts, **kwargs):
        return ["translated"]


class FakeModel:
    def _supports_default_dynamic_cache(self) -> bool:
        return True

    def generate(self, **kwargs):
        self.generate_kwargs = kwargs
        self.dynamic_cache_enabled = self._supports_default_dynamic_cache()
        return ["generated"]


def test_translation_disables_incompatible_generation_cache(monkeypatch) -> None:
    torch = ModuleType("torch")
    torch.inference_mode = nullcontext
    monkeypatch.setitem(sys.modules, "torch", torch)

    engine = IndicTrans2("hin_Deva", "eng_Latn", "cpu")
    engine.model = FakeModel()
    engine.processor = FakeProcessor()
    engine.tokenizer = FakeTokenizer()

    assert engine.translate("नमस्ते") == "translated"
    assert engine.model.generate_kwargs["use_cache"] is True
    assert engine.model.dynamic_cache_enabled is False
