"""Batch CLI. Run with python -m src.pipeline from PDFtoMD."""

import argparse
from contextlib import closing
import hashlib
from importlib import metadata
import json
import logging
import os
from pathlib import Path
import platform
import shutil
import sys
import tempfile
import time
import unicodedata

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "src"

from .cache import Cache, atomic_write, digest, process_lock
from .config import Config, ROOT
from .stage1_dewarp import check_scantailor, rectify
from .stage2_ocr import OCREngine
from .stage3_clean import Cleaner, Ollama, load_confusions

log = logging.getLogger("pdftomd")
PINNED_APIS = {"docling": "2.80.0", "docling-core": "2.69.0", "surya-ocr": "0.17.0", "pix2tex": "0.1.4"}
PACKAGES = (*PINNED_APIS, "PyMuPDF", "Pillow", "wordfreq", "torch", "torchvision", "transformers")


def prepare_directories(config):
    for name in ("input", "output", "tmp", ".cache"):
        path = config.root / name
        if not path.resolve().is_relative_to(config.root.resolve()):
            raise ValueError(f"{path} points outside PDFtoMD")
        path.mkdir(exist_ok=True)
    # Keep model/download caches within the requested folder. Set before imports.
    model_root = config.root / ".cache" / "models"
    for key, relative in (("HF_HOME", "huggingface"), ("TORCH_HOME", "torch"),
                          ("XDG_CACHE_HOME", "xdg"), ("MODEL_CACHE_DIR", "datalab")):
        os.environ[key] = str(model_root / relative)
    os.environ["TMPDIR"] = str(config.root / "tmp")
    tempfile.tempdir = str(config.root / "tmp")


def package_versions():
    values = {}
    for package in PACKAGES:
        try:
            values[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            values[package] = "missing"
    return values


def fingerprint(config):
    binary = shutil.which(config.scantailor)
    payload = {"settings": config.signature_settings(), "python": platform.python_version(),
               "packages": package_versions(),
               "code": {p.name: digest(p) for p in sorted((ROOT / "src").glob("*.py"))},
               "binary": digest(Path(binary)) if binary else "missing",
               "confusions": digest(config.confusion_file) if config.confusion_file else None}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def preflight(config):
    problems = []
    versions = package_versions()
    if not ((3, 10) <= sys.version_info[:2] <= (3, 12)):
        problems.append("Use Python 3.10–3.12 (3.12 recommended for the pinned ML stack)")
    for package, version in versions.items():
        if package == "wordfreq" and not config.use_llm:
            continue
        expected = PINNED_APIS.get(package)
        if version == "missing":
            problems.append(f"Missing Python package: {package}")
        elif expected and version != expected:
            problems.append(f"{package}=={expected} required by adapter; found {version}")
    try:
        executable = check_scantailor(config.scantailor)
        log.info("ScanTailor CLI: %s", executable)
    except (OSError, RuntimeError, TimeoutError) as exc:
        problems.append(str(exc))
    if config.use_llm:
        try:
            model_digest = Ollama(config).check()
        except RuntimeError as exc:
            problems.append(str(exc))
            model_digest = None
    else:
        model_digest = None
    if problems:
        raise RuntimeError("Preflight failed:\n  - " + "\n  - ".join(problems))
    return model_digest


def discover(config, filename=None):
    paths = sorted((p for p in config.input_dir.iterdir()
                    if p.is_file() and p.suffix.lower() == ".pdf"), key=lambda p: p.name.casefold())
    names = {}
    for path in paths:
        if not path.resolve().is_relative_to(config.root.resolve()):
            raise ValueError(f"Input symlink points outside PDFtoMD: {path.name}")
        key = unicodedata.normalize("NFC", path.stem).casefold()
        if key in names:
            raise ValueError(f"Output name collision: {names[key]} and {path.name}")
        names[key] = path.name
    if filename:
        paths = [p for p in paths if p.name == filename]
        if not paths:
            raise ValueError(f"No input PDF named {filename!r}")
    return paths


def run_batch(config, force=False, filename=None):
    prepare_directories(config)
    with process_lock(config.root / ".cache" / "pipeline.lock"):
        paths = discover(config, filename)
        if not paths:
            log.info("No PDFs found in %s", config.input_dir)
            return 0
        signature = fingerprint(config)
        with closing(Cache(config.root / ".cache" / "state.sqlite3", signature)) as cache:
            pending = []
            skipped = 0
            for pdf in paths:
                input_hash = digest(pdf)
                if not force and cache.valid(pdf.name, input_hash, signature, config.output_dir):
                    log.info("SKIP %s (verified content and output hashes)", pdf.name)
                    skipped += 1
                else:
                    pending.append((pdf, input_hash))
            if not pending:
                log.info("Finished: 0 processed, %d skipped, 0 failed", skipped)
                return 0
            model_digest = preflight(config)
            cache.namespace += model_digest or "no-llm"
            if force:
                # A forced rerun must not reuse previous language-model decisions.
                cache.namespace += str(time.time_ns())
            engine = OCREngine(config)
            cleaner = Cleaner(config, cache)
            failed = succeeded = 0
            for pdf, input_hash in pending:
                started = time.monotonic()
                workspace = Path(tempfile.mkdtemp(prefix="document-", dir=config.root / "tmp"))
                log.info("START %s", pdf.name)
                try:
                    # Process a stable snapshot, even if an input is replaced mid-run.
                    snapshot = workspace / "input.pdf"
                    shutil.copyfile(pdf, snapshot)
                    if digest(snapshot) != input_hash:
                        raise RuntimeError("Input changed while taking its snapshot; retry the document")
                    pages = rectify(snapshot, workspace, config)
                    result = engine.run(pages)
                    atomic_write(workspace / "raw.md", result.markdown)
                    markdown, cleanup = cleaner.run(result.markdown)
                    if digest(pdf) != input_hash:
                        raise RuntimeError("Input changed during processing; output was not published")
                    report = {"source": pdf.name, "sha256": input_hash, "signature": signature,
                              "ollama_model_digest": model_digest, "rectified_pages": len(pages),
                              "elapsed_seconds": round(time.monotonic() - started, 2),
                              "ocr": result.report, "cleanup": cleanup}
                    output = config.output_dir / (pdf.stem + ".md")
                    report_path = config.output_dir / (pdf.stem + ".report.json")
                    atomic_write(report_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
                    atomic_write(output, markdown)
                    # A crash before this commit causes a rerun, never a false skip.
                    cache.record(pdf.name, input_hash, signature, [output, report_path])
                    succeeded += 1
                    log.info("DONE %s -> %s (%.1fs)", pdf.name, output.name, time.monotonic() - started)
                    if not config.keep_temp:
                        shutil.rmtree(workspace)
                except Exception:
                    failed += 1
                    log.exception("FAILED %s; diagnostic workspace retained at %s", pdf.name, workspace)
                    # A timed-out Docling pipeline may have stale worker state.
                    engine = OCREngine(config)
            log.info("Finished: %d processed, %d skipped, %d failed", succeeded, skipped, failed)
            return 1 if failed else 0


def parser():
    result = argparse.ArgumentParser(description="Scanned PDF -> ScanTailor -> Docling/Surya/pix2tex -> Markdown")
    result.add_argument("--doctor", action="store_true", help="Check dependencies, CLI capabilities and Ollama model")
    result.add_argument("--force", action="store_true", help="Ignore document and correction cache")
    result.add_argument("--file", help="Process one exact filename from input/")
    result.add_argument("--keep-temp", action="store_true", help="Keep raster pages, rectified images and raw Markdown")
    result.add_argument("--no-llm", action="store_true", help="Run deterministic cleanup only")
    result.add_argument("--scantailor", default="scantailor-cli", help="Path/name of a compatible ScanTailor CLI")
    result.add_argument("--layout", choices=["0", "1", "1.5", "2"], default="0", help="0 auto, 1 single, 1.5 cut, 2 spread")
    result.add_argument("--direction", choices=["lr", "rl"], default="lr")
    result.add_argument("--dpi", type=int, default=300)
    result.add_argument("--scan-timeout", type=int, default=600)
    result.add_argument("--page-timeout", type=int, default=600, help="Docling cooperative page deadline (seconds)")
    result.add_argument("--max-pixels", type=int, default=80_000_000)
    result.add_argument("--max-pages", type=int, default=5000)
    result.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    result.add_argument("--ollama-model", default="qwen2.5:7b-instruct-q4_K_M")
    result.add_argument("--ollama-timeout", type=int, default=60)
    result.add_argument("--max-corrections", type=int, default=64, help="Maximum Ollama calls per PDF")
    result.add_argument("--context-chars", type=int, default=600)
    result.add_argument("--language", default="en", help="wordfreq dictionary language, e.g. en, hi, bn")
    result.add_argument("--confusion-file", type=Path, help="JSON optical-confusion pairs inside PDFtoMD")
    result.add_argument("--confidence-threshold", type=float, default=0.75)
    result.add_argument("--recognition-batch-size", type=int, default=4)
    result.add_argument("--verbose", action="store_true")
    return result


def main(argv=None):
    arguments = vars(parser().parse_args(argv))
    doctor, force, filename = (arguments.pop(key) for key in ("doctor", "force", "file"))
    verbose = arguments.pop("verbose")
    arguments["use_llm"] = not arguments.pop("no_llm")
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        config = Config(**arguments)
        prepare_directories(config)
        load_confusions(config.confusion_file)
        file_handler = logging.FileHandler(ROOT / ".cache" / "pipeline.log", encoding="utf-8")
        file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logging.getLogger().addHandler(file_handler)
        try:
            if doctor:
                preflight(config)
                log.info("Dependency checks passed. Model inference is checked during conversion.")
                return 0
            return run_batch(config, force, filename)
        finally:
            logging.getLogger().removeHandler(file_handler)
            file_handler.close()
    except KeyboardInterrupt:
        log.error("Interrupted; completed documents remain cached")
        return 130
    except Exception as exc:
        log.error("%s", exc, exc_info=verbose)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
