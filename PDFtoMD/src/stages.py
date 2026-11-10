"""Run one durable pipeline checkpoint at a time.

Each command is intended to be launched in its own OS process.  A successful
stage writes a manifest last, so later stages never consume partial results.
"""

import argparse
import hashlib
import json
import logging
from pathlib import Path
import sys
import time

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "src"

from .cache import atomic_write, digest
from .config import Config, ROOT
from .stage1_dewarp import rectify

log = logging.getLogger("pdftomd.stages")


def safe_stem(filename: str) -> str:
    path = Path(filename)
    if path.name != filename or path.suffix.lower() != ".pdf":
        raise ValueError("--file must be one PDF filename from input/")
    return path.stem


def stage_root(filename: str) -> Path:
    return ROOT / "work" / safe_stem(filename)


def stage1(args) -> int:
    source = ROOT / "input" / args.file
    if not source.is_file() or not source.resolve().is_relative_to((ROOT / "input").resolve()):
        raise FileNotFoundError(f"Input not found inside input/: {args.file}")
    destination = stage_root(args.file) / "stage1"
    if destination.exists():
        raise RuntimeError(f"Stage 1 checkpoint already exists: {destination}; use a new input name or inspect it")
    destination.mkdir(parents=True)
    config = Config(dpi=args.dpi, scantailor=args.scantailor, keep_temp=True,
                    scan_timeout=args.timeout, use_llm=False, recognition_batch_size=1)
    started = time.monotonic()
    pages = rectify(source, destination, config)
    artifacts = [{"file": page.relative_to(destination).as_posix(), "sha256": digest(page),
                  "bytes": page.stat().st_size} for page in pages]
    manifest = {
        "stage": 1, "source": args.file, "source_sha256": digest(source),
        "dpi": args.dpi, "pages": artifacts,
        "elapsed_seconds": round(time.monotonic() - started, 2),
    }
    atomic_write(destination / "manifest.json", json.dumps(manifest, indent=2) + "\n")
    log.info("Stage 1 complete: %d rectified page(s) in %s", len(pages), destination)
    return 0


def _completed_stage1_pages(filename: str) -> tuple[Path, list[Path]]:
    root = stage_root(filename) / "stage1"
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError("Stage 1 is not complete; its manifest is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source = ROOT / "input" / filename
    if manifest.get("source_sha256") != digest(source):
        raise RuntimeError("The input PDF changed after Stage 1")
    pages = []
    for artifact in manifest.get("pages", []):
        page = root / artifact["file"]
        if not page.is_file() or digest(page) != artifact["sha256"]:
            raise RuntimeError(f"Stage 1 artifact failed validation: {page}")
        pages.append(page)
    if not pages:
        raise RuntimeError("Stage 1 manifest contains no pages")
    return root, pages


def stage2_surya(args) -> int:
    """Run only Surya and persist its geometry-rich result as JSON.

    This command intentionally imports neither Docling nor pix2tex.  It is run
    in a separate OS process so Surya's weights are released on process exit.
    Individual page JSON files are resumable; the manifest is committed last.
    """
    _, pages = _completed_stage1_pages(args.file)
    destination = stage_root(args.file) / "stage2-surya"
    manifest_path = destination / "manifest.json"
    if manifest_path.exists():
        raise RuntimeError(f"Surya checkpoint already complete: {destination}")
    destination.mkdir(parents=True, exist_ok=True)

    # Heavy imports stay inside this one command.
    from PIL import Image
    from surya.foundation import FoundationPredictor
    from surya.recognition import RecognitionPredictor
    from surya.detection import DetectionPredictor

    log.info("Loading Surya foundation, recognition, and detection weights")
    recognizer = RecognitionPredictor(FoundationPredictor())
    detector = DetectionPredictor()
    recognizer.disable_tqdm = True
    detector.disable_tqdm = True
    started = time.monotonic()
    artifacts = []
    for index, page in enumerate(pages, 1):
        page_hash = digest(page)
        result_path = destination / f"{page.stem}.json"
        if result_path.is_file():
            existing = json.loads(result_path.read_text(encoding="utf-8"))
            if existing.get("source_sha256") == page_hash and "prediction" in existing:
                log.info("Surya page %d/%d already checkpointed", index, len(pages))
                artifacts.append({"file": result_path.name, "sha256": digest(result_path),
                                  "bytes": result_path.stat().st_size})
                continue
        log.info("Surya OCR page %d/%d (%s)", index, len(pages), page.name)
        with Image.open(page) as opened:
            image = opened.convert("RGB")
            prediction = recognizer(
                [image], det_predictor=detector,
                recognition_batch_size=args.batch_size,
                detection_batch_size=1, math_mode=True, return_words=True,
                sort_lines=True, drop_repeated_text=True,
            )[0]
        payload = {
            "source": page.name,
            "source_sha256": page_hash,
            "prediction": prediction.model_dump(mode="json"),
        }
        atomic_write(result_path, json.dumps(payload, ensure_ascii=False) + "\n")
        artifacts.append({"file": result_path.name, "sha256": digest(result_path),
                          "bytes": result_path.stat().st_size})

    manifest = {
        "stage": "2-surya", "source": args.file,
        "source_sha256": digest(ROOT / "input" / args.file),
        "pages": artifacts, "batch_size": args.batch_size,
        "elapsed_seconds": round(time.monotonic() - started, 2),
    }
    atomic_write(manifest_path, json.dumps(manifest, indent=2) + "\n")
    log.info("Surya checkpoint complete: %d page(s) in %s", len(artifacts), destination)
    return 0


def stage2_docling(args) -> int:
    """Run Docling layout/table parsing without loading any OCR engine.

    For PDFs with a usable text layer, this is both more faithful and far
    cheaper than re-OCRing every glyph.  Scanned inputs will instead use the
    separate precomputed-Surya adapter after that route has been validated.
    """
    _completed_stage1_pages(args.file)  # validates source identity/checkpoint
    source = ROOT / "input" / args.file
    import pymupdf
    from .text_quality import detect_text_quality
    with pymupdf.open(source) as probe_document:
        probe = "\n".join(page.get_text("text") for page in probe_document[:min(5, len(probe_document))])
    quality = detect_text_quality(probe)
    if not quality["usable"]:
        raise RuntimeError(
            "Embedded PDF text is not trustworthy ("
            + quality["reason"] + "); use the OCR image route instead"
        )
    destination = stage_root(args.file) / "stage2-docling"
    if (destination / "manifest.json").exists():
        raise RuntimeError(f"Docling checkpoint already complete: {destination}")
    destination.mkdir(parents=True, exist_ok=True)

    from docling.datamodel.base_models import InputFormat, ConversionStatus
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    options = PdfPipelineOptions(
        do_ocr=False,
        do_table_structure=True,
        do_formula_enrichment=False,
        generate_page_images=False,
        document_timeout=args.timeout,
        layout_batch_size=1,
        table_batch_size=1,
    )
    options.table_structure_options.do_cell_matching = True
    converter = DocumentConverter(
        allowed_formats=[InputFormat.PDF],
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)},
    )
    started = time.monotonic()
    log.info("Docling layout/table parsing with embedded PDF text (OCR disabled)")
    result = converter.convert(source, raises_on_error=True)
    if result.status != ConversionStatus.SUCCESS:
        raise RuntimeError(f"Docling returned {result.status}")
    markdown = result.document.export_to_markdown()
    if not markdown.strip():
        raise RuntimeError("Docling produced empty Markdown")
    labels = {}
    for item, _ in result.document.iterate_items():
        name = str(item.label)
        labels[name] = labels.get(name, 0) + 1
    markdown_path = destination / "raw.md"
    json_path = destination / "document.json"
    atomic_write(markdown_path, markdown.rstrip() + "\n")
    atomic_write(json_path, result.document.model_dump_json(indent=2) + "\n")
    manifest = {
        "stage": "2-docling", "source": args.file,
        "source_sha256": digest(source), "ocr": False,
        "text_quality": quality,
        "labels": labels,
        "artifacts": [
            {"file": markdown_path.name, "sha256": digest(markdown_path),
             "bytes": markdown_path.stat().st_size},
            {"file": json_path.name, "sha256": digest(json_path),
             "bytes": json_path.stat().st_size},
        ],
        "elapsed_seconds": round(time.monotonic() - started, 2),
    }
    atomic_write(destination / "manifest.json", json.dumps(manifest, indent=2) + "\n")
    log.info("Docling checkpoint complete in %s", destination)
    return 0


def stage2_docling_ocr(args) -> int:
    """Run Docling with completed, precomputed Surya page JSON."""
    _, pages = _completed_stage1_pages(args.file)
    ocr_dir = stage_root(args.file) / "stage2-surya"
    ocr_manifest_path = ocr_dir / "manifest.json"
    if not ocr_manifest_path.is_file():
        raise RuntimeError("Surya OCR is incomplete; its final manifest is missing")
    ocr_manifest = json.loads(ocr_manifest_path.read_text(encoding="utf-8"))
    artifacts = {item["file"]: item for item in ocr_manifest.get("pages", [])}
    for page in pages:
        name = f"{page.stem}.json"
        item = artifacts.get(name)
        checkpoint = ocr_dir / name
        if not item or not checkpoint.is_file() or digest(checkpoint) != item["sha256"]:
            raise RuntimeError(f"Invalid or missing Surya checkpoint: {name}")

    destination = stage_root(args.file) / "stage2-docling"
    if (destination / "manifest.json").exists():
        raise RuntimeError(f"Docling checkpoint already complete: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    from .docling_precomputed import convert_precomputed_pages
    from .text_quality import detect_text_quality
    ocr_sample = []
    for page in pages[:min(5, len(pages))]:
        payload = json.loads((ocr_dir / f"{page.stem}.json").read_text(encoding="utf-8"))
        ocr_sample.extend(line.get("text", "") for line in payload["prediction"].get("text_lines", []))
    ocr_quality = detect_text_quality("\n".join(ocr_sample))
    if not ocr_quality["usable"] or not ocr_quality["language"]:
        raise RuntimeError(f"Cannot detect a valid OCR script: {ocr_quality['reason']}")
    started = time.monotonic()
    log.info("Docling layout/tables using precomputed Surya OCR (Surya is not loaded)")
    markdown, documents, labels = convert_precomputed_pages(
        pages, ocr_dir, args.timeout, ocr_quality["language"]
    )
    if not markdown.strip():
        raise RuntimeError("Docling produced empty Markdown from precomputed OCR")
    markdown_path = destination / "raw.md"
    json_path = destination / "document.json"
    atomic_write(markdown_path, markdown.rstrip() + "\n")
    atomic_write(json_path, json.dumps(documents, ensure_ascii=False, indent=2) + "\n")
    quality = detect_text_quality(markdown)
    if not quality["usable"]:
        raise RuntimeError(f"OCR output failed Unicode quality validation: {quality['reason']}")
    manifest = {
        "stage": "2-docling", "source": args.file,
        "source_sha256": digest(ROOT / "input" / args.file),
        "ocr": True, "ocr_source": "surya-checkpoints", "text_quality": quality,
        "labels": labels,
        "artifacts": [
            {"file": markdown_path.name, "sha256": digest(markdown_path),
             "bytes": markdown_path.stat().st_size},
            {"file": json_path.name, "sha256": digest(json_path),
             "bytes": json_path.stat().st_size},
        ],
        "elapsed_seconds": round(time.monotonic() - started, 2),
    }
    atomic_write(destination / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    log.info("Docling OCR checkpoint complete in %s", destination)
    return 0


def stage2_formulas(args) -> int:
    """Inventory Docling formula regions before loading pix2tex."""
    source_dir = stage_root(args.file) / "stage2-docling"
    source_manifest = source_dir / "manifest.json"
    if not source_manifest.is_file():
        raise RuntimeError("Docling checkpoint is not complete")
    docling = json.loads(source_manifest.read_text(encoding="utf-8"))
    count = sum(value for label, value in docling.get("labels", {}).items()
                if label.lower().endswith("formula") or label.lower() == "formula")
    destination = stage_root(args.file) / "stage2-formulas"
    if (destination / "manifest.json").exists():
        raise RuntimeError(f"Formula checkpoint already complete: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    if count:
        raise RuntimeError(
            f"Docling found {count} formula block(s); crop export must be completed before pix2tex"
        )
    manifest = {
        "stage": "2-formulas", "source": args.file,
        "source_sha256": digest(ROOT / "input" / args.file),
        "formula_blocks": 0, "pix2tex_loaded": False,
        "result": "verified-no-op: Docling detected no formula regions",
    }
    atomic_write(destination / "manifest.json", json.dumps(manifest, indent=2) + "\n")
    log.info("Formula stage verified as no-op; pix2tex was not loaded")
    return 0


def stage2_reading_order(args) -> int:
    from wordfreq import zipf_frequency
    from .reading_order import repair_strong_interruptions
    from .text_quality import detect_text_quality, normalize_language

    source = stage_root(args.file) / "stage2-docling" / "raw.md"
    if not source.is_file():
        raise RuntimeError("Docling raw Markdown is missing")
    destination = stage_root(args.file) / "stage2-reading-order"
    if (destination / "manifest.json").exists():
        raise RuntimeError(f"Reading-order checkpoint already complete: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    markdown = source.read_text(encoding="utf-8")
    quality = detect_text_quality(markdown)
    if not quality["usable"]:
        raise RuntimeError(
            "Cannot repair reading order on untrustworthy extracted text ("
            + quality["reason"] + "); OCR the page images first"
        )
    requested = normalize_language(args.language)
    language = requested or quality["language"]
    if not language:
        raise RuntimeError("Language/script detection was inconclusive")
    frequency = lambda word: zipf_frequency(word, language)
    repaired, changes = repair_strong_interruptions(markdown, frequency)
    output = destination / "reordered.md"
    atomic_write(output, repaired)
    manifest = {
        "stage": "2-reading-order", "source": args.file,
        "source_sha256": digest(ROOT / "input" / args.file),
        "input_sha256": digest(source), "output_sha256": digest(output),
        "language": language, "language_source": "override" if requested else "detected",
        "text_quality": quality, "deterministic_changes": changes,
        "llm_requests": 0,
    }
    atomic_write(destination / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    log.info("Reading-order checkpoint complete: %d strong repair(s)", len(changes))
    return 0


def stage2_reading_order_llm(args) -> int:
    from .reading_order import (attach_byline, classify_blocks_ollama,
                                geometry_role_candidates)

    source = stage_root(args.file) / "stage2-reading-order" / "reordered.md"
    document_path = stage_root(args.file) / "stage2-docling" / "document.json"
    if not source.is_file() or not document_path.is_file():
        raise RuntimeError("Docling and deterministic reading-order checkpoints are required")
    destination = stage_root(args.file) / "stage2-reading-order-llm"
    if (destination / "manifest.json").exists():
        raise RuntimeError(f"LLM reading-order checkpoint already complete: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    documents = json.loads(document_path.read_text(encoding="utf-8"))
    candidates = geometry_role_candidates(documents)
    markdown = source.read_text(encoding="utf-8")
    decisions, edits = [], []
    for candidate in candidates:
        decision = classify_blocks_ollama(
            candidate["blocks"], args.ollama_url, args.ollama_model, args.timeout
        )
        decisions.append({"candidate": candidate, "decision": decision})
        metadata_id = candidate["metadata_id"]
        if (decision["confidence"] >= args.min_confidence
                and decision["roles"].get(metadata_id) == "byline"
                and decision["roles"].get(candidate["title_id"]) == "title"):
            markdown = attach_byline(
                markdown, candidate["metadata_text"], candidate["title_text"],
                allow_missing_heading=True,
            )
            edits.append({"metadata": candidate["metadata_text"],
                          "attached_to": candidate["title_text"],
                          "model_attach_to": decision["attach_to"].get(metadata_id),
                          "confidence": decision["confidence"]})
    output = destination / "reordered.md"
    atomic_write(output, markdown)
    manifest = {
        "stage": "2-reading-order-llm", "source": args.file,
        "source_sha256": digest(ROOT / "input" / args.file),
        "input_sha256": digest(source), "output_sha256": digest(output),
        "model": args.ollama_model, "candidates": len(candidates),
        "requests": len(decisions), "edits": edits, "decisions": decisions,
    }
    atomic_write(destination / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    log.info("LLM reading-order checkpoint complete: %d candidate(s), %d edit(s)",
             len(candidates), len(edits))
    return 0


def stage3_deterministic(args) -> int:
    from .stage3_clean import Cleaner

    llm_reordered = stage_root(args.file) / "stage2-reading-order-llm" / "reordered.md"
    reordered = (llm_reordered if llm_reordered.is_file()
                 else stage_root(args.file) / "stage2-reading-order" / "reordered.md")
    source = reordered if reordered.is_file() else stage_root(args.file) / "stage2-docling" / "raw.md"
    if not source.is_file():
        raise RuntimeError("Docling raw Markdown is missing")
    destination = stage_root(args.file) / "stage3-deterministic"
    if (destination / "manifest.json").exists():
        raise RuntimeError(f"Deterministic cleanup checkpoint already complete: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    raw = source.read_text(encoding="utf-8")
    cleaned, stats = Cleaner(Config(use_llm=False)).run(raw)
    output = destination / "clean.md"
    atomic_write(output, cleaned)
    manifest = {
        "stage": "3-deterministic", "source": args.file,
        "source_sha256": digest(ROOT / "input" / args.file),
        "input_sha256": digest(source), "output_sha256": digest(output),
        "input_chars": len(raw), "output_chars": len(cleaned),
        "llm_loaded": False, "cleanup": stats,
    }
    atomic_write(destination / "manifest.json", json.dumps(manifest, indent=2) + "\n")
    log.info("Deterministic cleanup checkpoint complete: %s", output)
    return 0


def stage3_scan(args) -> int:
    """Find bounded optical-confusion candidates without contacting Ollama."""
    from wordfreq import zipf_frequency
    from .stage3_clean import (candidates, load_confusions, protected_mask,
                               sentence_context, word_spans)
    from .text_quality import detect_text_quality, normalize_language

    source = stage_root(args.file) / "stage3-deterministic" / "clean.md"
    if not source.is_file():
        raise RuntimeError("Deterministic cleanup checkpoint is missing")
    destination = stage_root(args.file) / "stage3-scan"
    if (destination / "manifest.json").exists():
        raise RuntimeError(f"Ambiguity scan already complete: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    text_value = source.read_text(encoding="utf-8")
    quality = detect_text_quality(text_value)
    if not quality["usable"]:
        raise RuntimeError(f"Cannot scan untrustworthy text: {quality['reason']}")
    requested = normalize_language(args.language)
    language = requested or quality["language"]
    if not language:
        raise RuntimeError("Language/script detection was inconclusive")
    mask = protected_mask(text_value)
    pairs = load_confusions(None)
    findings = []
    frequency = lambda word: zipf_frequency(word, language)
    frequency("test")
    for start, end, word in word_spans(text_value):
        if any(mask[start:end]):
            continue
        choices = candidates(word, pairs, frequency)
        if not choices:
            continue
        context = sentence_context(text_value, start, end, args.context_chars)
        findings.append({
            "offset": start, "word": word, "choices": sorted(choices),
            "context": context, "eligible": context is not None,
        })
    result_path = destination / "candidates.json"
    atomic_write(result_path, json.dumps(findings, ensure_ascii=False, indent=2) + "\n")
    manifest = {
        "stage": "3-scan", "source": args.file,
        "source_sha256": digest(ROOT / "input" / args.file),
        "input_sha256": digest(source), "language": language,
        "language_source": "override" if requested else "detected",
        "text_quality": quality,
        "candidates": len(findings),
        "eligible": sum(bool(item["eligible"]) for item in findings),
        "ollama_loaded": False,
        "artifact": {"file": result_path.name, "sha256": digest(result_path)},
    }
    atomic_write(destination / "manifest.json", json.dumps(manifest, indent=2) + "\n")
    log.info("Ambiguity scan complete: %d candidate token(s)", len(findings))
    return 0


def publish(args) -> int:
    """Publish only a fully inspected checkpoint; perform no model inference."""
    source = stage_root(args.file) / "stage3-deterministic" / "clean.md"
    scan_path = stage_root(args.file) / "stage3-scan" / "manifest.json"
    if not source.is_file() or not scan_path.is_file():
        raise RuntimeError("Cleanup and ambiguity-scan checkpoints are required")
    scan = json.loads(scan_path.read_text(encoding="utf-8"))
    if scan.get("input_sha256") != digest(source):
        raise RuntimeError("Clean Markdown changed after the ambiguity scan")
    if scan.get("eligible"):
        raise RuntimeError("Eligible ambiguity candidates remain; run the isolated Ollama step first")
    formula_path = stage_root(args.file) / "stage2-formulas" / "manifest.json"
    if not formula_path.is_file():
        raise RuntimeError("Formula inventory checkpoint is missing")
    formulas = json.loads(formula_path.read_text(encoding="utf-8"))
    if formulas.get("formula_blocks"):
        raise RuntimeError("Unprocessed formula blocks remain")

    output = ROOT / "output" / f"{safe_stem(args.file)}.md"
    report_path = ROOT / "output" / f"{safe_stem(args.file)}.report.json"
    output.parent.mkdir(exist_ok=True)
    content = source.read_text(encoding="utf-8")
    atomic_write(output, content)
    order_path = stage_root(args.file) / "stage2-reading-order" / "manifest.json"
    order = json.loads(order_path.read_text(encoding="utf-8")) if order_path.is_file() else {}
    order_llm_path = stage_root(args.file) / "stage2-reading-order-llm" / "manifest.json"
    order_llm = (json.loads(order_llm_path.read_text(encoding="utf-8"))
                 if order_llm_path.is_file() else {})
    docling_path = stage_root(args.file) / "stage2-docling" / "manifest.json"
    docling = json.loads(docling_path.read_text(encoding="utf-8")) if docling_path.is_file() else {}
    surya_path = stage_root(args.file) / "stage2-surya" / "manifest.json"
    surya = json.loads(surya_path.read_text(encoding="utf-8")) if surya_path.is_file() else {}
    report = {
        "source": args.file,
        "source_sha256": digest(ROOT / "input" / args.file),
        "output": output.name, "output_sha256": digest(output),
        "workflow": "stepwise-test",
        "rectified_pages": len(_completed_stage1_pages(args.file)[1]),
        "surya_pages": len(surya.get("pages", [])),
        "docling_ocr": bool(docling.get("ocr")),
        "ocr_source": docling.get("ocr_source", "embedded-pdf-text"),
        "language": scan.get("language"),
        "language_source": scan.get("language_source"),
        "reading_order_repairs": (len(order.get("deterministic_changes", []))
                                  + len(order_llm.get("edits", []))),
        "reading_order_llm_requests": order_llm.get("requests", 0),
        "reading_order_model": order_llm.get("model"),
        "formula_blocks": formulas["formula_blocks"],
        "ambiguity_candidates": scan["candidates"],
        "ollama_loaded": False,
    }
    atomic_write(report_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    log.info("Published %s and %s", output, report_path)
    return 0


def status(args) -> int:
    root = stage_root(args.file)
    if not root.exists():
        print(json.dumps({"file": args.file, "stages": []}, indent=2))
        return 0
    stages = []
    for manifest in sorted(root.glob("stage*/manifest.json")):
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["manifest"] = str(manifest)
        stages.append(data)
    print(json.dumps({"file": args.file, "stages": stages}, indent=2))
    return 0


def parser():
    result = argparse.ArgumentParser(description="Run and inspect one PDFtoMD stage")
    sub = result.add_subparsers(dest="command", required=True)
    one = sub.add_parser("stage1", help="render and rectify with ScanTailor")
    one.add_argument("--file", required=True)
    one.add_argument("--dpi", type=int, default=240)
    one.add_argument("--timeout", type=int, default=1800)
    one.add_argument("--scantailor", default=str(ROOT / "tools" / "scantailor-cli"))
    one.set_defaults(function=stage1)
    surya = sub.add_parser("stage2-surya", help="run Surya OCR only and save page JSON")
    surya.add_argument("--file", required=True)
    surya.add_argument("--batch-size", type=int, default=1)
    surya.set_defaults(function=stage2_surya)
    docling = sub.add_parser("stage2-docling", help="run Docling layout/tables with PDF text")
    docling.add_argument("--file", required=True)
    docling.add_argument("--timeout", type=int, default=1800)
    docling.set_defaults(function=stage2_docling)
    docling_ocr = sub.add_parser("stage2-docling-ocr", help="run Docling using saved Surya OCR")
    docling_ocr.add_argument("--file", required=True)
    docling_ocr.add_argument("--timeout", type=int, default=1800)
    docling_ocr.set_defaults(function=stage2_docling_ocr)
    formulas = sub.add_parser("stage2-formulas", help="inventory formula crops before pix2tex")
    formulas.add_argument("--file", required=True)
    formulas.set_defaults(function=stage2_formulas)
    order = sub.add_parser("stage2-reading-order", help="repair column/page block ordering")
    order.add_argument("--file", required=True)
    order.add_argument("--language", default="auto", help="optional override; default detects Unicode script")
    order.set_defaults(function=stage2_reading_order)
    order_llm = sub.add_parser("stage2-reading-order-llm", help="classify ambiguous block roles with Ollama")
    order_llm.add_argument("--file", required=True)
    order_llm.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    order_llm.add_argument("--ollama-model", default="qwen3.5:4b")
    order_llm.add_argument("--timeout", type=int, default=120)
    order_llm.add_argument("--min-confidence", type=float, default=0.8)
    order_llm.set_defaults(function=stage2_reading_order_llm)
    deterministic = sub.add_parser("stage3-deterministic", help="run regex/heuristic cleanup only")
    deterministic.add_argument("--file", required=True)
    deterministic.set_defaults(function=stage3_deterministic)
    scan = sub.add_parser("stage3-scan", help="find optical-confusion candidates without Ollama")
    scan.add_argument("--file", required=True)
    scan.add_argument("--language", default="auto", help="optional override; default detects Unicode script")
    scan.add_argument("--context-chars", type=int, default=600)
    scan.set_defaults(function=stage3_scan)
    publish_parser = sub.add_parser("publish", help="publish validated stepwise checkpoint")
    publish_parser.add_argument("--file", required=True)
    publish_parser.set_defaults(function=publish)
    info = sub.add_parser("status", help="show completed checkpoint manifests")
    info.add_argument("--file", required=True)
    info.set_defaults(function=status)
    return result


def main(argv=None):
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = parser().parse_args(argv)
    try:
        return args.function(args)
    except Exception as exc:
        log.error("%s", exc, exc_info=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
