from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import yaml

from .config import AppConfig
from .pipeline import TranslationPipeline
from .types import TranslationRequest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="local-translate", description="Local NLLB translation")
    parser.add_argument("--config", default=os.getenv("TRANSLATION_CONFIG", "config/default.yaml"))
    subparsers = parser.add_subparsers(dest="command", required=True)

    translate = subparsers.add_parser("translate", help="Translate text, a file, or stdin")
    source = translate.add_mutually_exclusive_group()
    source.add_argument("--text")
    source.add_argument("--input", type=Path)
    translate.add_argument("--source", required=True, help="NLLB code or alias, e.g. en")
    translate.add_argument("--target", required=True, help="NLLB code or alias, e.g. hi")
    translate.add_argument(
        "--tone",
        default="faithful",
        choices=["faithful", "formal", "literary", "academic", "colloquial"],
    )
    translate.add_argument("--glossary", type=Path, help="JSON/YAML source-to-target mapping")
    translate.add_argument("--reference", type=Path, help="Optional trusted reference for scoring")
    translate.add_argument("--output", type=Path)
    translate.add_argument("--json", action="store_true", help="Print full result as JSON")
    translate.add_argument("--document-id")

    subparsers.add_parser("validate-config", help="Validate configuration without loading models")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = AppConfig.from_file(args.config)
        if args.command == "validate-config":
            print(f"Configuration is valid: {args.config}")
            return 0
        text = args.text
        if args.input:
            text = args.input.read_text(encoding="utf-8")
        if text is None:
            text = sys.stdin.read()
        glossary = _mapping(args.glossary) if args.glossary else {}
        reference = args.reference.read_text(encoding="utf-8") if args.reference else None
        request = TranslationRequest(
            text=text,
            source_lang=args.source,
            target_lang=args.target,
            tone=args.tone,
            glossary=glossary,
            reference=reference,
            document_id=args.document_id,
        )
        result = TranslationPipeline(config).translate(request)
        rendered = (
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2) if args.json else result.text
        )
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered + "\n", encoding="utf-8")
        else:
            print(rendered)
        if result.needs_review:
            print(
                f"Quality gate failed ({result.score:.3f}); queued in {result.review_file}",
                file=sys.stderr,
            )
            return 2
        return 0
    except (FileNotFoundError, TypeError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _mapping(path: Path) -> dict[str, str]:
    with path.open(encoding="utf-8") as handle:
        value: Any = yaml.safe_load(handle)
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    ):
        raise ValueError("Glossary must be a JSON/YAML string-to-string mapping")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
