# PDFtoMD

Checkpointed PDF-to-Markdown experiments. Each heavy model runs in a separate
OS process so its memory is released before the next model starts. Do not use
the combined `src.pipeline` runner yet; the tested path is `src.stages`.

## Why VS Code was collapsing

The Linux OOM daemon killed the entire VS Code cgroup after it reached roughly
11–12 GiB and sustained high memory pressure. Python child processes, model
weights, image tensors, file cache, Pylance, terminals, and Ollama were all
charged to that same cgroup. The individual hardware figures for Surya,
Docling, and Qwen are minimum standalone estimates, not additive limits.

For the supplied 20-page test PDF:

- ScanTailor: 20 pages at 240 DPI in 48 seconds.
- Surya 0.17: 6.92 GiB observed peak with batch size 1; a cover page took about
  133 seconds on one CPU thread. Four threads remained too slow for dense pages.
- Docling with the PDF text layer and OCR disabled: the complete document in
  34.6 seconds on CPU.
- Formula regions: zero, so pix2tex was correctly not loaded.
- Dictionary-gated optical ambiguities: zero, so Ollama was correctly not
  loaded.

This PDF should therefore use embedded text + Docling. Surya remains a fallback
for scanned, non-Latin, or low-confidence regions.

## Layout

```text
input/       source PDFs
output/      published Markdown and reports
work/        durable per-stage checkpoints
tmp/         disposable files
tools/       ScanTailor CLI/AppImage
src/         implementation
tests/       unit and integration tests
```

## Environment

Python 3.12 is recommended. Install a CPU or CUDA build of PyTorch appropriate
for the machine, then install the pinned requirements. The tested environment
in this workspace is `.venv-check`.

ScanTailor is invoked through `tools/scantailor-cli`. Ollama is only needed if
the ambiguity scan produces eligible candidates; the intended model is
`qwen2.5:7b-instruct-q4_K_M`.

Model caches stay under `.cache/models/`, which is excluded from VS Code file
watching and Python analysis.

## Tested stepwise commands

Run from this directory:

```bash
.venv-check/bin/python -m src.stages stage1 \
  --file Eng_Naya_Disha_2025_09.pdf --dpi 240

.venv-check/bin/python -m src.stages stage2-surya \
  --file Eng_Naya_Disha_2025_09.pdf --batch-size 1

.venv-check/bin/python -m src.stages stage2-docling \
  --file Eng_Naya_Disha_2025_09.pdf

.venv-check/bin/python -m src.stages stage2-reading-order \
  --file Eng_Naya_Disha_2025_09.pdf

.venv-check/bin/python -m src.stages stage2-formulas \
  --file Eng_Naya_Disha_2025_09.pdf

.venv-check/bin/python -m src.stages stage3-deterministic \
  --file Eng_Naya_Disha_2025_09.pdf

.venv-check/bin/python -m src.stages stage3-scan \
  --file Eng_Naya_Disha_2025_09.pdf --language en

.venv-check/bin/python -m src.stages publish \
  --file Eng_Naya_Disha_2025_09.pdf
```

The Surya command is resumable page by page. For this test it was intentionally
stopped after one representative page because the PDF has a good English text
layer and full-document CPU OCR would waste hours.

For production heavy stages, launch each command in its own user systemd scope,
with a memory ceiling and a unique unit name. Example:

```bash
systemd-run --user --scope --collect --unit=pdftomd-docling \
  --property=MemoryHigh=6G --property=MemoryMax=8G \
  env OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 \
  .venv-check/bin/python -m src.stages stage2-docling \
  --file Eng_Naya_Disha_2025_09.pdf
```

Stop a scope by name with `systemctl --user stop UNIT.scope`. Sending Ctrl-C to
the `systemd-run` terminal wrapper is not sufficient proof that the scoped
worker stopped; verify with `systemctl --user show UNIT.scope`.

## Verification

```bash
.venv-check/bin/python -m unittest discover -s tests -v
.venv-check/bin/python -m src.stages status \
  --file Eng_Naya_Disha_2025_09.pdf
```

All 26 tests pass in the tested environment. Checkpoint manifests include input
and artifact hashes and are written last, preventing a partial stage from being
treated as complete. Ollama requests use `temperature=0`, are restricted to one
token replacement, and set `keep_alive` to zero so Qwen unloads immediately.

Reading-order repair is separate from optical-token correction. Strong cases
such as a short floating header interrupting `pro-` / `longed` are repaired
deterministically and the metadata is attached to the preceding article title.
Ambiguous cases use immutable block IDs: the language model may return only an
exact permutation, semantic roles, attachment IDs, and confidence. It cannot
rewrite or omit OCR text.

## Automatic language and legacy-font routing

Do not pass a language for normal operation. The stage runner detects Unicode
script and records both the language and its evidence in each manifest. ISO
aliases such as `ben` are normalized to `bn` when an override is explicitly
needed.

The embedded-text Docling route rejects symbol-heavy legacy/custom encodings
instead of treating a high character count as usable text. For those PDFs, run
the image OCR branch:

```bash
.venv-check/bin/python -m src.stages stage2-surya \
  --file DOCUMENT.pdf --batch-size 16

.venv-check/bin/python -m src.stages stage2-docling-ocr \
  --file DOCUMENT.pdf

.venv-check/bin/python -m src.stages stage2-reading-order \
  --file DOCUMENT.pdf
```

`stage2-docling-ocr` consumes saved Surya JSON without loading Surya again.
Ambiguous right-column metadata can then be classified in small immutable-block
windows with `stage2-reading-order-llm`; the model may classify and attach
blocks but cannot rewrite OCR text. The Bengali legacy-font test completed with
32 passing tests and automatic language `bn`.
