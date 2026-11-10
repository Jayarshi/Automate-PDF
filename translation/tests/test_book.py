import copy
import json

import pytest
import yaml

from local_nllb.book import SentenceSegmenter, main, prepare, validate_review
from local_nllb.config import AppConfig, QualityConfig, SegmentConfig
from local_nllb.engines.indictrans import IndicTransConfig, language_pair
from local_nllb.engines.postedit import LocalLLMPostEditor
from local_nllb.pipeline import TranslationPipeline
from local_nllb.types import TranslationRequest


class ProposalEditor:
    def complete_json(self, system, prompt):
        return {
            "glossary": [{"source": "Alice", "suggested_target": "एलिस"}],
            "entities": ["Alice"],
            "questions": ["Which register?"],
        }


def approved_form():
    form = prepare("Alice arrived.", "en", "hi", ProposalEditor())
    form["approved"] = True
    form["style_guide"] = dict.fromkeys(form["style_guide"], "formal")
    form["glossary"][0]["target"] = "एलिस"
    form["entities"][0].update(gender="unknown", pronouns="unknown", honorific="none")
    form["questions"][0]["answer"] = "formal"
    return form


@pytest.mark.parametrize(
    "source,target,direction",
    [
        ("en", "hi", "en_indic"),
        ("bn", "en", "indic_en"),
        ("kn", "bn", "indic_indic"),
        ("kas_Deva", "mni_Mtei", "indic_indic"),
    ],
)
def test_model_routing(source, target, direction):
    assert language_pair(source, target)[2] == direction


@pytest.mark.parametrize("source,target", [("en", "fr"), ("bad", "hi"), ("hi", "hi")])
def test_unsupported_pair_rejected(source, target):
    with pytest.raises(ValueError):
        language_pair(source, target)


def test_preparation_never_approves_or_fills_targets():
    form = prepare("Alice arrived.", "en", "hi", ProposalEditor())
    assert form["approved"] is False
    assert form["glossary"][0]["target"] == ""
    assert form["glossary"][0]["suggested_target"] == "एलिस"


def test_approval_requires_complete_matching_form():
    form = approved_form()
    glossary, style = validate_review(form, "Alice arrived.", "en", "hi")
    assert glossary == {"Alice": "एलिस"}
    assert style["entities"][0]["gender"] == "unknown"
    for key, value in [
        ("approved", False),
        ("source_sha256", "stale"),
        ("target_language", "ben_Beng"),
        ("style_guide", {}),
    ]:
        broken = {**form, key: value}
        with pytest.raises(ValueError):
            validate_review(broken, "Alice arrived.", "en", "hi")
    broken = copy.deepcopy(form)
    broken["questions"][0]["answer"] = ""
    with pytest.raises(ValueError):
        validate_review(broken, "Alice arrived.", "en", "hi")


def test_unapproved_cli_does_not_load_engine(tmp_path, monkeypatch):
    source = tmp_path / "source.txt"
    source.write_text("Alice arrived.")
    review = tmp_path / "review.yaml"
    form = approved_form()
    form["approved"] = False
    review.write_text(yaml.safe_dump(form))

    def forbidden(*args):
        pytest.fail("Engine must not load before approval")

    monkeypatch.setattr("local_nllb.book.IndicTransEngine", forbidden)
    assert (
        main(
            [
                "translate",
                "--input",
                str(source),
                "--source",
                "en",
                "--target",
                "hi",
                "--review",
                str(review),
                "--output",
                str(tmp_path / "out.txt"),
            ]
        )
        == 1
    )


def test_sentence_overflow_is_not_silently_split():
    segmenter = SentenceSegmenter(SegmentConfig(max_source_tokens=2))
    with pytest.raises(ValueError, match="token budget"):
        segmenter.segment("This sentence is too long.", "eng_Latn")


class BookEngine:
    config = IndicTransConfig()

    def __init__(self):
        self.calls = []

    def count_tokens(self, text):
        return len(text.split())

    def translate_batch(self, texts, source, target, beam_size=None):
        self.calls.append((texts, beam_size))
        return ["वह घर आई।" for _ in texts]


class ContextEditor:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def edit(self, *args):
        pytest.fail("Book editing requires context")

    def edit_with_context(self, *args, style, context):
        self.calls.append((style, context, args[-1]))
        if self.fail:
            raise RuntimeError("offline")
        # Deliberately omit glossary term on first attempt to trigger exact QA.
        return "एलिस घर आई।" if len(self.calls) > 1 else "वह घर आई।"


def test_context_and_exact_glossary_retry(tmp_path):
    engine, editor = BookEngine(), ContextEditor()
    config = AppConfig(quality=QualityConfig(review_path=str(tmp_path / "review.jsonl")))
    result = TranslationPipeline(
        config, engine=engine, post_editor=editor, book_mode=True
    ).translate(
        TranslationRequest(
            "Alice arrived. She smiled.",
            "en",
            "hi",
            glossary={"Alice": "एलिस"},
            style_guide={"register": "formal"},
        )
    )
    assert result.segments[0].attempts == 2
    assert engine.calls[1][1] == 10
    assert editor.calls[0][1] == {"before": [], "after": ["She smiled."]}
    assert editor.calls[0][0] == {"register": "formal"}
    assert "missing exact glossary term: एलिस" in editor.calls[1][2]


def test_postedit_failure_cannot_pass_on_high_heuristic_score(tmp_path):
    config = AppConfig(
        quality=QualityConfig(max_retries=0, review_path=str(tmp_path / "review.jsonl"))
    )
    result = TranslationPipeline(
        config, engine=BookEngine(), post_editor=ContextEditor(True), book_mode=True
    ).translate(TranslationRequest("She arrived.", "en", "hi"))
    assert result.needs_review
    assert any("offline" in issue for issue in result.issues)


def test_posteditor_prompt_contains_rules_and_context(monkeypatch):
    editor = LocalLLMPostEditor(AppConfig().post_edit)
    seen = []

    def fake(system, prompt):
        seen.append(json.loads(prompt))
        return {"translation": "अनुवाद"}

    monkeypatch.setattr(editor, "complete_json", fake)
    editor.edit_with_context(
        "source",
        "draft",
        "en",
        "hi",
        "formal",
        {},
        [],
        {"pronouns": "formal"},
        {"before": ["Alice spoke."]},
    )
    assert seen[0]["approved_style_guide"] == {"pronouns": "formal"}
    assert seen[0]["neighboring_source_sentences"]["before"] == ["Alice spoke."]


def test_no_qe_writes_review_draft_only(tmp_path, monkeypatch):
    source, review, output = (tmp_path / name for name in ("source.txt", "form.yaml", "out.txt"))
    source.write_text("Alice arrived.")
    review.write_text(yaml.safe_dump(approved_form()))
    engine = BookEngine()
    engine.direction = "en_indic"
    editor = ContextEditor()
    monkeypatch.setattr("local_nllb.book.IndicTransEngine", lambda *args: engine)
    monkeypatch.setattr("local_nllb.book.LocalLLMPostEditor", lambda *args: editor)
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({"quality": {"review_path": str(tmp_path / "queue.jsonl")}}))
    assert (
        main(
            [
                "translate",
                "--input",
                str(source),
                "--source",
                "en",
                "--target",
                "hi",
                "--config",
                str(config),
                "--review",
                str(review),
                "--output",
                str(output),
            ]
        )
        == 2
    )
    assert not output.exists()
    assert (tmp_path / "out.txt.review.txt").exists()
    report = json.loads((tmp_path / "out.txt.report.json").read_text())
    assert report["needs_review"]
    assert report["approved_review"]["approved"]
