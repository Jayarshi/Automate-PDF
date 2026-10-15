from local_nllb.config import AppConfig


def test_default_config_loads() -> None:
    config = AppConfig.from_file("config/default.yaml")
    assert config.nllb.compute_type == "int8"
    assert config.nllb.tokenizer.endswith("-hf")
    assert config.post_edit.enabled is False
