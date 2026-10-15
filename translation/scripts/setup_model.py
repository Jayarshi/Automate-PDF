#!/usr/bin/env python3
"""Download NLLB once and convert it to an offline CTranslate2 model."""

from __future__ import annotations

import argparse
from pathlib import Path

from huggingface_hub import snapshot_download


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="facebook/nllb-200-distilled-600M")
    parser.add_argument("--hf-dir", type=Path, default=Path("models/nllb-200-distilled-600M-hf"))
    parser.add_argument(
        "--output-dir", type=Path, default=Path("models/nllb-200-distilled-600M-ct2-int8")
    )
    parser.add_argument(
        "--quantization",
        default="int8",
        choices=["int8", "int8_float16", "float16", "float32"],
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    try:
        import torch  # noqa: F401 -- required by the Transformers converter
        from ctranslate2.converters import TransformersConverter
    except ImportError as exc:
        raise RuntimeError(
            "Model conversion dependency is missing. Run: .venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu"
        ) from exc

    if args.output_dir.exists() and any(args.output_dir.iterdir()) and not args.force:
        parser.error(f"{args.output_dir} is not empty; use --force to overwrite via the converter")
    args.hf_dir.parent.mkdir(parents=True, exist_ok=True)
    args.output_dir.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {args.model} to {args.hf_dir} ...")
    snapshot_download(repo_id=args.model, local_dir=args.hf_dir)

    print(f"Converting to {args.quantization} at {args.output_dir} ...")
    converter = TransformersConverter(str(args.hf_dir))
    converter.convert(
        str(args.output_dir),
        quantization=args.quantization,
        force=args.force,
    )
    print("Model is ready. The Hugging Face directory is retained for offline tokenization.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
