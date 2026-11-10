from contextlib import ExitStack
from dataclasses import replace
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from src.cache import Cache, atomic_write, digest, process_lock
from src.config import Config, ROOT
from src.pipeline import discover, run_batch


class CacheTests(unittest.TestCase):
    def test_hash_and_artifact_validation(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as folder:
            root = Path(folder)
            output = root / "book.md"
            atomic_write(output, "old text")
            cache = Cache(root / "state.sqlite3")
            try:
                cache.record("book.pdf", "input1", "config1", [output])
                self.assertTrue(cache.valid("book.pdf", "input1", "config1", root))
                self.assertFalse(cache.valid("book.pdf", "input2", "config1", root))
                self.assertFalse(cache.valid("book.pdf", "input1", "config2", root))
                atomic_write(output, "manual edit")
                self.assertFalse(cache.valid("book.pdf", "input1", "config1", root))
                output.unlink()
                self.assertFalse(cache.valid("book.pdf", "input1", "config1", root))
            finally:
                cache.close()

    def test_failed_atomic_write_preserves_previous_output(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as folder:
            path = Path(folder) / "book.md"
            atomic_write(path, "previous result")
            with patch("src.cache.os.replace", side_effect=OSError("disk error")):
                with self.assertRaises(OSError):
                    atomic_write(path, "new result")
            self.assertEqual(path.read_text(), "previous result")
            self.assertEqual(list(Path(folder).iterdir()), [path])

    def test_concurrent_runs_cannot_share_cache(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as folder:
            path = Path(folder) / "lock"
            with process_lock(path):
                with self.assertRaises(RuntimeError):
                    with process_lock(path):
                        pass
            with process_lock(path):
                pass


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "tmp")
        self.root = Path(self.temp.name)
        with patch("src.config.ROOT", self.root):
            self.config = Config(root=self.root, use_llm=False)
        for name in ("input", "output", "tmp", ".cache"):
            (self.root / name).mkdir()
        self.stack = ExitStack()
        # Tests use deterministic fake stages; PDF rasterization has a separate real-image test.
        self.stack.enter_context(patch("src.pipeline.prepare_directories"))
        self.stack.enter_context(patch("src.pipeline.fingerprint", return_value="signature"))
        self.check = self.stack.enter_context(patch("src.pipeline.preflight", return_value=None))
        self.rectify = self.stack.enter_context(patch("src.pipeline.rectify", return_value=[Path("page.png")]))
        self.engine = self.stack.enter_context(patch("src.pipeline.OCREngine"))
        self.engine.return_value.run.return_value = SimpleNamespace(markdown="A clean page.", report={"pages": []})

    def tearDown(self):
        self.stack.close()
        self.temp.cleanup()

    def put_pdf(self, name, content=b"pdf snapshot"):
        path = self.root / "input" / name
        path.write_bytes(content)
        return path

    def test_second_run_skips_without_loading_models_or_preflight(self):
        self.put_pdf("book.PDF")
        self.assertEqual(run_batch(self.config), 0)
        self.assertEqual((self.root / "output" / "book.md").read_text(), "A clean page.\n")
        self.check.reset_mock()
        self.engine.reset_mock()
        self.assertEqual(run_batch(self.config), 0)
        self.check.assert_not_called()
        self.engine.assert_not_called()
        (self.root / "output" / "book.md").write_text("edited")
        self.assertEqual(run_batch(self.config), 0)
        self.check.assert_called_once()

    def test_failure_continues_batch_and_is_retried(self):
        self.put_pdf("a.pdf")
        self.put_pdf("b.pdf")
        self.rectify.side_effect = [RuntimeError("bad scan"), [Path("page.png")]]
        with self.assertLogs("pdftomd", level="ERROR"):
            self.assertEqual(run_batch(self.config), 1)
        self.assertFalse((self.root / "output" / "a.md").exists())
        self.assertTrue((self.root / "output" / "b.md").exists())
        self.rectify.side_effect = None
        self.rectify.reset_mock()
        self.assertEqual(run_batch(self.config), 0)
        self.rectify.assert_called_once()

    def test_source_mutation_during_conversion_does_not_publish(self):
        source = self.put_pdf("book.pdf")
        def change_source(*args):
            source.write_bytes(b"new input")
            return [Path("page.png")]
        self.rectify.side_effect = change_source
        with self.assertLogs("pdftomd", level="ERROR"):
            self.assertEqual(run_batch(self.config), 1)
        self.assertFalse((self.root / "output" / "book.md").exists())

    def test_case_insensitive_output_collisions_fail_before_processing(self):
        self.put_pdf("book.pdf")
        self.put_pdf("BOOK.PDF")
        with self.assertRaisesRegex(ValueError, "collision"):
            discover(self.config)
        self.engine.assert_not_called()


if __name__ == "__main__":
    unittest.main()
