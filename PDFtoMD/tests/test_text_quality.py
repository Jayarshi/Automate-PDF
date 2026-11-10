import unittest

from src.text_quality import detect_text_quality, normalize_language


class TextQualityTests(unittest.TestCase):
    def test_detects_bengali_unicode(self):
        result = detect_text_quality("বাংলা ভাষার একটি দীর্ঘ পরীক্ষামূলক বাক্য। " * 10)
        self.assertTrue(result["usable"])
        self.assertEqual(result["language"], "bn")

    def test_rejects_legacy_font_mojibake(self):
        result = detect_text_quality("ˆ§ˆÏ≤Wz¡∫Ó˚ñ !ÓŸªË˛yÓ˚ï˛# " * 20)
        self.assertFalse(result["usable"])
        self.assertIn("legacy", result["reason"])

    def test_detects_latin_and_normalizes_iso_alias(self):
        result = detect_text_quality("This is ordinary English document text. " * 10)
        self.assertTrue(result["usable"])
        self.assertEqual(result["language"], "en")
        self.assertEqual(normalize_language("ben"), "bn")
        self.assertIsNone(normalize_language("auto"))


if __name__ == "__main__":
    unittest.main()
