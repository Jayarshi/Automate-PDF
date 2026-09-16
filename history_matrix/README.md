# History Matrix

An auditable, multi-stage historical claim ledger for the Russian Revolution
corpus. The pipeline processes every book independently, verifies quotations
against page text, canonicalizes atomic claims, classifies each source's coverage
and stance, applies an independence-aware mathematical evidence policy, and writes
complete Excel, CSV, and Markdown reports.

## Setup

```bash
conda env create -f environment.yml
conda activate pdf_venv
cp .env.example .env
```

Set `OPENAI_API_KEY` in `.env`. Tesseract is included because the Carr volume is
image-only. Never commit `.env`.

For an existing environment, update it and run the built-in diagnostic:

```bash
conda env update -n pdf_venv -f environment.yml --prune
conda activate pdf_venv
python main.py doctor
```

## Run

The production path is one command:

```bash
python main.py
```

It runs `parse → extract → deduplicate → align → score → export`, resuming durable
SQLite checkpoints. Individual stages remain available:

```bash
python main.py status
python main.py doctor
python main.py parse
python main.py extract
python main.py deduplicate
python main.py align
python main.py score
python main.py export
```

Use `--force` on a stage only when its cached results must be rebuilt.

## Results

The `output/` directory receives:

- `fact_consensus_matrix.xlsx` — styled fact ledger, source evidence, source policy,
  and methodology sheets.
- `fact_consensus_matrix.csv` — flat sortable ledger.
- `fact_consensus_report.md` — complete claim-by-claim narrative audit with exact
  passages and page citations.

The evidence direction index is

```text
I(F) = 100 × (A − D) / (1 + A + D)
```

where `A` is dependence-deduplicated support mass and `D` is D1 factual
contradiction mass. It is a research index, not a probability of truth. The full
multidimensional policy and source assumptions live in the marked executable block
at the end of `sources.md`.
