from indictrans2_md.languages import detect_source, target_language


def test_detects_english_and_resolves_target() -> None:
    code, name, confidence = detect_source(
        "This is a sufficiently long English paragraph with several ordinary words."
    )
    assert code == "eng_Latn"
    assert name == "English"
    assert confidence >= 0.6
    assert target_language("Hindi") == ("hin_Deva", "Hindi", "Hindi")


def test_rejects_unsupported_target() -> None:
    try:
        target_language("French")
    except ValueError as exc:
        assert "Unsupported" in str(exc)
    else:
        raise AssertionError("Unsupported target should fail.")
