from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .pipeline import translate_markdown


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Translate a Markdown file with AI4Bharat IndicTrans2."
    )
    parser.add_argument("--input", required=True, type=Path, help="Source Markdown file")
    parser.add_argument("--target", required=True, help="Target language name or code (e.g. hi, Hindi)")
    parser.add_argument("--output", type=Path, help="Output file (default: <name>_<target>.md)")
    parser.add_argument("--device", default="auto", help="auto, cpu, cuda, or a specific torch device")
    parser.add_argument("--no-llm", action="store_true", help="Skip the Ollama consistency pass")
    parser.add_argument("--ollama-model", default="qwen2.5:3b")
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    args = parser.parse_args()
    try:
        if not args.input.is_file():
            raise FileNotFoundError(f"Input file not found: {args.input}")
        output = translate_markdown(
            args.input,
            args.target,
            args.output,
            args.device,
            not args.no_llm,
            args.ollama_model,
            args.ollama_url,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(f"Saved: {output}")


if __name__ == "__main__":
    main()
