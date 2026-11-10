from dataclasses import replace
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from src.config import Config, ROOT
from src.stage1_dewarp import REQUIRED_OPTIONS, check_scantailor, rectify
from src.stage2_ocr import OCREngine, crop_box, latex_body, refine_inline

HAS_IMAGES = importlib.util.find_spec("PIL") is not None and importlib.util.find_spec("pymupdf") is not None
HAS_CORE = importlib.util.find_spec("docling_core") is not None


class FormulaTests(unittest.TestCase):
    def test_formula_delimiters_and_braces(self):
        self.assertEqual(latex_body(r"$$\frac{x}{y}$$"), r"\frac{x}{y}")
        self.assertEqual(latex_body(r"\text{\$5}"), r"\text{\$5}")
        for text in ("", "{x", "x}", "```latex", "$x$$"):
            with self.assertRaises(RuntimeError):
                latex_body(text)

    def test_invalid_inline_geometry_preserves_surya_formula(self):
        line = SimpleNamespace(text=r"Find \(x_1\) now", chars=[])
        stats = {"inline_crops": 0, "inline_without_geometry": 0}
        output = refine_inline(line, None, lambda _: self.fail("must not guess crop"), stats)
        self.assertEqual(output, "Find $x_1$ now")
        self.assertEqual(stats["inline_without_geometry"], 1)

    @unittest.skipUnless(HAS_IMAGES, "image dependencies not installed")
    def test_inline_crop_replaces_only_math_span(self):
        from PIL import Image
        text = "Find $x$ now"
        chars = [SimpleNamespace(text=c, bbox_valid=True, bbox=[i * 10, 5, i * 10 + 8, 20])
                 for i, c in enumerate(text)]
        line = SimpleNamespace(text=text, chars=chars)
        stats = {"inline_crops": 0, "inline_without_geometry": 0}
        with Image.new("RGB", (200, 40), "white") as image:
            def recognize(crop):
                self.assertEqual(crop.size, (12, 19))
                return "y_1"
            self.assertEqual(refine_inline(line, image, recognize, stats), "Find $y_1$ now")
            self.assertEqual(stats["inline_crops"], 1)
            with self.assertRaises(RuntimeError):
                crop_box(image, [40, 0, 2, 20])

    @unittest.skipUnless(HAS_CORE, "docling-core not installed")
    def test_real_docling_export_preserves_inline_and_display_math(self):
        from PIL import Image
        from docling_core.types.doc import DoclingDocument, DocItemLabel, ImageRef, Size, ProvenanceItem, BoundingBox, CoordOrigin
        doc = DoclingDocument(name="equation")
        image = Image.new("RGB", (200, 100), "white")
        doc.add_page(page_no=1, size=Size(width=200, height=100), image=ImageRef.from_pil(image, dpi=72))
        doc.add_text(label=DocItemLabel.TEXT, text=r"Use $x_1 < y$ here.")
        doc.add_text(label=DocItemLabel.FORMULA, text="old", prov=ProvenanceItem(
            page_no=1, charspan=(0, 3), bbox=BoundingBox(l=20, t=60, r=100, b=20, coord_origin=CoordOrigin.BOTTOMLEFT)))
        engine = OCREngine(Config())
        engine.formula = lambda crop: r"\frac{x}{y}"
        engine.stats = {"display_crops": 0}
        markdown = engine._export(doc)
        self.assertIn("Use $x_1 < y$ here.", markdown)
        self.assertIn(r"$$\frac{x}{y}$$", markdown)
        self.assertNotIn("PDFTOMDMATH", markdown)
        self.assertEqual(engine.stats["display_crops"], 1)


class ScanTailorTests(unittest.TestCase):
    def test_capability_probe_accepts_help_exit_one(self):
        result = SimpleNamespace(stdout="\n".join("--" + f + "=value" for f in REQUIRED_OPTIONS), stderr="", returncode=1)
        with patch("src.stage1_dewarp.shutil.which", return_value="/bin/true"), patch("src.stage1_dewarp.subprocess.run", return_value=result):
            self.assertEqual(check_scantailor("scan"), Path("/bin/true").resolve())
            result.stdout = "--help"
            with self.assertRaisesRegex(RuntimeError, "Incompatible"):
                check_scantailor("scan")

    @unittest.skipUnless(HAS_IMAGES, "image dependencies not installed")
    def test_real_pdf_render_and_rectified_output_order(self):
        import pymupdf
        from PIL import Image
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as folder:
            root = Path(folder)
            pdf = root / "scan.pdf"
            with pymupdf.open() as doc:
                page = doc.new_page(width=144, height=72)
                page.insert_text((10, 30), "Scanned page")
                doc.save(pdf)
            workspace = root / "work"
            def fake_scan(args, **kwargs):
                self.assertIn("--dewarping=auto", args)
                self.assertIn("--layout=0", args)
                source, target = Path(args[-2]), Path(args[-1])
                with Image.open(next(source.glob("*.png"))) as image:
                    self.assertEqual(image.size, (600, 300))
                    image.save(target / "page_2L.tif")
                    image.save(target / "page_1R.tif")
                return SimpleNamespace(returncode=0)
            with (patch("src.stage1_dewarp.check_scantailor", return_value=Path("/fake/scantailor")),
                  patch("src.stage1_dewarp.cli_kind", return_value="legacy"),
                  patch("src.stage1_dewarp.subprocess.run", side_effect=fake_scan)):
                pages = rectify(pdf, workspace, Config())
            self.assertEqual([p.name for p in pages], ["page-000001-1.png", "page-000001-2.png"])
            self.assertTrue(all(p.is_file() for p in pages))


if __name__ == "__main__":
    unittest.main()
