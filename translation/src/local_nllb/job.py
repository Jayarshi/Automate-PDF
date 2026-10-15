from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .pipeline import TranslationPipeline
from .types import TranslationRequest


@dataclass(slots=True)
class TranslationJob:
    pipeline_config: Path
    input_file: Path
    source_language: str
    target_languages: list[str]
    output_directory: Path
    tone: str = "faithful"
    glossary_files: dict[str, Path] = field(default_factory=dict)
    reference_files: dict[str, Path] = field(default_factory=dict)
    document_id: str | None = None


def load_job(path: str | Path) -> TranslationJob:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Translation job not found: {path}")
    with path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, dict):
        raise TypeError("Translation job must be a YAML mapping")

    required = ("input_file", "source_language", "target_languages", "output_directory")
    missing = [name for name in required if name not in raw]
    if missing:
        raise ValueError(f"Missing translation job fields: {', '.join(missing)}")
    targets = raw["target_languages"]
    if not isinstance(targets, list) or not targets or not all(isinstance(x, str) for x in targets):
        raise TypeError("target_languages must be a non-empty YAML list")

    return TranslationJob(
        pipeline_config=Path(raw.get("pipeline_config", "config/default.yaml")),
        input_file=Path(raw["input_file"]),
        source_language=str(raw["source_language"]),
        target_languages=targets,
        output_directory=Path(raw["output_directory"]),
        tone=str(raw.get("tone", "faithful")),
        glossary_files=_path_mapping(raw.get("glossary_files", {}), "glossary_files"),
        reference_files=_path_mapping(raw.get("reference_files", {}), "reference_files"),
        document_id=str(raw["document_id"]) if raw.get("document_id") is not None else None,
    )


def run_job(job: TranslationJob) -> int:
    if not job.input_file.exists():
        raise FileNotFoundError(f"Input text file not found: {job.input_file}")
    text = job.input_file.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"Input text file is empty: {job.input_file}")

    pipeline = TranslationPipeline.from_file(job.pipeline_config)
    job.output_directory.mkdir(parents=True, exist_ok=True)
    any_review = False
    for target in job.target_languages:
        glossary = _read_mapping(job.glossary_files.get(target))
        reference_path = job.reference_files.get(target)
        reference = reference_path.read_text(encoding="utf-8") if reference_path else None
        result = pipeline.translate(
            TranslationRequest(
                text=text,
                source_lang=job.source_language,
                target_lang=target,
                tone=job.tone,  # type: ignore[arg-type]
                glossary=glossary,
                reference=reference,
                document_id=job.document_id or job.input_file.stem,
            )
        )
        safe_target = re.sub(r"[^A-Za-z0-9_-]+", "_", target)
        base = f"{job.input_file.stem}.{safe_target}"
        text_path = job.output_directory / f"{base}.txt"
        report_path = job.output_directory / f"{base}.report.json"
        text_path.write_text(result.text.rstrip() + "\n", encoding="utf-8")
        report_path.write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        status = "REVIEW" if result.needs_review else "PASS"
        print(
            f"[{status}] {job.source_language} -> {target} | score={result.score:.3f}\n"
            f"  translation: {text_path}\n"
            f"  quality report: {report_path}"
        )
        any_review = any_review or result.needs_review
    return 2 if any_review else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Translate one input file into one or more languages from an editable YAML job."
    )
    parser.add_argument("--job", type=Path, default=Path("config/translation-job.yaml"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run_job(load_job(args.job))
    except (FileNotFoundError, TypeError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _path_mapping(value: Any, name: str) -> dict[str, Path]:
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    ):
        raise TypeError(f"{name} must map target-language names to file paths")
    return {key: Path(item) for key, item in value.items()}


def _read_mapping(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    if not path.exists():
        raise FileNotFoundError(f"Glossary file not found: {path}")
    with path.open(encoding="utf-8") as handle:
        value = yaml.safe_load(handle) or {}
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    ):
        raise TypeError(f"Glossary must be a string-to-string mapping: {path}")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
