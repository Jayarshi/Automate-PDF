import pytest
from pydantic import ValidationError

from local_nllb.api import TranslateBody, health


def test_health_does_not_load_translation_model() -> None:
    assert health() == {"status": "ok"}


def test_api_rejects_unknown_tone() -> None:
    with pytest.raises(ValidationError):
        TranslateBody(text="Hello", source_lang="en", target_lang="fr", tone="marketing")
