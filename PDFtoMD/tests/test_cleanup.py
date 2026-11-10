import json
from pathlib import Path
import tempfile
import unittest

from src.config import Config, ROOT
from src.stage3_clean import Cleaner, candidates, deterministic_clean, load_confusions, word_spans


def frequency(word):
    return {"modern": 5, "clear": 5, "hello": 5, "well": 5, "model": 5}.get(word, 0)


class FakeOllama:
    def __init__(self, reply="modern"):
        self.reply, self.calls = reply, []

    def correct(self, context, word):
        self.calls.append((context, word))
        return self.reply


class CleanupTests(unittest.TestCase):
    def test_prose_repairs_and_relative_headings(self):
        source = "### Title\n\n\n##### Detail\nAn of fice with ofﬁcial af f inity.\ninter-\nnational\n"
        output = deterministic_clean(source)
        self.assertIn("# Title\n\n### Detail", output)
        self.assertIn("official", output)
        self.assertIn("international", output)
        self.assertEqual(deterministic_clean("af finity f i f l\n"), "affinity f i f l\n")

    def test_code_math_tables_links_are_byte_preserved(self):
        spans = ["```python\nx = 'rn'\n\n\ninter-\nnational\n```",
                 "~~~~\n```\nf i\n~~~~", "`af finity`", "$$a_{rn}\n\n\n+1$$",
                 r"\(f i\)", "$rn + 1$", "| af finity | rn |",
                 "![figure](data:image/png;base64,abcrn)", "[rn](https://example.test/rn)",
                 "    inter-\n    national"]
        for span in spans:
            with self.subTest(span=span):
                self.assertEqual(deterministic_clean(span + "\n"), span + "\n")

    def test_unclosed_blocks_remain_protected(self):
        for text in ("```\ninter-\nnational\n\n\n", "$$\naf finity\n"):
            self.assertEqual(deterministic_clean(text), text.rstrip("\n") + "\n")

    def test_unicode_marks_and_join_controls_survive(self):
        text = "বাংলা हिन्दी क्षि क्‍ष 中文"
        self.assertEqual(deterministic_clean(text), text + "\n")
        self.assertIn("हिन्दी", [word for _, _, word in word_spans(text)])

    def test_only_exact_occurrence_and_candidate_can_change(self):
        client = FakeOllama()
        cleaner = Cleaner(Config(max_corrections=1), client=client, frequency=frequency)
        output, stats = cleaner.run("A rnodern example. Another rnodern case.\n`rnodern`\n$rnodern$\n")
        self.assertEqual(output, "A modern example. Another rnodern case.\n`rnodern`\n$rnodern$\n")
        self.assertEqual(stats["requests"], 1)
        self.assertEqual(stats["over_budget"], 1)
        self.assertEqual(client.calls, [("A rnodern example.", "rnodern")])

    def test_rejects_rephrasing_and_non_optical_answer(self):
        for reply in ("modern example", "Modern", "**modern**", "correct", "modern\nexplanation"):
            cleaner = Cleaner(Config(), client=FakeOllama(reply), frequency=frequency)
            output, stats = cleaner.run("A rnodern example.")
            self.assertEqual(output, "A rnodern example.\n")
            self.assertEqual(stats["rejected"], 1)

    def test_long_context_and_known_words_do_not_call_llm(self):
        client = FakeOllama()
        cleaner = Cleaner(Config(context_chars=20), client=client, frequency=frequency)
        cleaner.run("The rnodern " + "word " * 100 + ". A modern model.")
        self.assertEqual(client.calls, [])

    def test_custom_multilingual_confusions_are_dictionary_gated(self):
        scores = {"বরন": 0, "বরণ": 5}
        self.assertEqual(candidates("বরন", [("ন", "ণ")], lambda w: scores.get(w, 0)), {"বরণ"})
        self.assertEqual(candidates("2021", [("1", "l")], frequency), set())

    def test_invalid_confusion_file_fails(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as directory:
            path = Path(directory) / "rules.json"
            path.write_text(json.dumps([["x", "two words"]]))
            with self.assertRaises(ValueError):
                load_confusions(path)

    def test_no_llm_has_no_optional_dependencies(self):
        output, stats = Cleaner(Config(use_llm=False)).run("inter-\nnational")
        self.assertEqual(output, "international\n")
        self.assertEqual(stats["requests"], 0)


if __name__ == "__main__":
    unittest.main()
