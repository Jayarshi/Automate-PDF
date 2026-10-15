from local_nllb.protect import TextProtector


def test_glossary_and_url_round_trip() -> None:
    protected = TextProtector().protect(
        "OpenAI docs are at https://example.com/a.", {"OpenAI": "ओपनएआई"}
    )
    assert protected.text == "<x0> docs are at <x1>"
    restored, issues = protected.restore("Visit <x0> via < x 1 >")
    assert restored == "Visit ओपनएआई via https://example.com/a."
    assert issues == []


def test_missing_placeholder_is_reported() -> None:
    protected = TextProtector().protect("Use ACME", {"ACME": "ACME Corp"})
    _, issues = protected.restore("Use the company")
    assert issues == ["missing protected value: ACME Corp"]
