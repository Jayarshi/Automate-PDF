import json
import unittest

from src.reading_order import (build_reorder_prompt, repair_strong_interruptions,
                               validate_reorder_decision, attach_byline,
                               geometry_role_candidates)


class ReadingOrderTests(unittest.TestCase):
    def test_floating_byline_cannot_split_hyphenated_word(self):
        source = (
            "# An article\n\nOpening paragraph.\n\nThe policy caused a pro-\n\n"
            "# A Person\n\nlonged suspension of services.\n"
        )
        result, changes = repair_strong_interruptions(source, lambda word: 4 if word == "prolonged" else 0)
        self.assertIn("# An article\n\n*A Person*", result)
        self.assertIn("a prolonged suspension", result)
        self.assertNotIn("# A Person", result)
        self.assertEqual(len(changes), 1)

    def test_does_not_move_a_real_heading_without_word_continuity(self):
        source = "# First\n\nA complete sentence.\n\n# Second topic\n\nNew paragraph.\n"
        result, changes = repair_strong_interruptions(source, lambda _: 9)
        self.assertEqual(result, source)
        self.assertEqual(changes, [])

    def test_llm_decision_must_be_exact_permutation(self):
        blocks = [{"id": "b1", "text": "pro-"}, {"id": "b2", "text": "longed"}]
        self.assertIn("immutable", build_reorder_prompt(blocks))
        valid = {"order": ["b1", "b2"], "roles": {"b1": "body", "b2": "body"},
                 "attach_to": {}, "confidence": 0.9}
        self.assertEqual(validate_reorder_decision(valid, ["b1", "b2"]), valid)
        invalid = json.loads(json.dumps(valid))
        invalid["order"] = ["b1", "b1"]
        with self.assertRaises(ValueError):
            validate_reorder_decision(invalid, ["b1", "b2"])

    def test_moves_validated_byline_but_preserves_text(self):
        source = "# Article\n\nBody left.\n\n# Writer\n\nBody right.\n"
        result = attach_byline(source, "Writer", "Article")
        self.assertEqual(result.count("Writer"), 1)
        self.assertIn("# Article\n\n*Writer*", result)
        self.assertIn("Body left.", result)
        self.assertIn("Body right.", result)

    def test_can_restore_validated_byline_omitted_by_exporter(self):
        source = "# Article\n\nBody.\n"
        result = attach_byline(source, "Writer", "Article", allow_missing_heading=True)
        self.assertIn("# Article\n\n*Writer*", result)

    def test_geometry_finds_short_right_column_header(self):
        def item(label, text, l, t, r, b):
            return {"label": label, "text": text, "prov": [{"bbox": {
                "l": l, "t": t, "r": r, "b": b, "coord_origin": "BOTTOMLEFT"}}]}
        document = {"pages": {"1": {"size": {"width": 2000, "height": 2600}}},
                    "texts": [
                        item("section_header", "Article title", 500, 2450, 1500, 2400),
                        item("text", "Left column body", 100, 2200, 900, 200),
                        item("section_header", "Writer", 1700, 2350, 1900, 2300),
                        item("text", "Right column body", 1100, 2200, 1900, 200),
                    ]}
        found = geometry_role_candidates([document])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["metadata_text"], "Writer")


if __name__ == "__main__":
    unittest.main()
