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

The default backend is local Ollama, so no API key or per-request payment is needed.
Install Ollama on Linux, start it, and download the two configured models:

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama serve
# In a second terminal:
conda activate pdf_venv
python main.py pull-models
```

The default `qwen3.5:4b` model is selected for a 16 GiB CPU-only computer. For more
quality at substantially lower speed and tighter memory headroom, set
`LLM_MODEL=qwen3.5:9b` and run `ollama pull qwen3.5:9b`. The separate
`qwen3-embedding:0.6b` model performs semantic retrieval and clustering.

Tesseract is included because the Carr volume is image-only. Never commit `.env`.

For an existing environment, update it and run the built-in diagnostic:

```bash
conda env update -n pdf_venv -f environment.yml --prune
conda activate pdf_venv
python main.py doctor
```

`doctor` checks the Ollama server and verifies that both configured models are
installed before the pipeline schedules any LLM work.

Local CPU inference is free of API charges but slow. The pipeline uses one worker,
bounded 3,500-character chunks, durable SQLite checkpoints, and automatic re-chunking
from cached page text. You may stop with `Ctrl+C` and rerun the same command later.
Because this is a compact local model, review the final ledger; exact-quote validation
rejects unsupported quotations, but it cannot guarantee perfect historical judgment.

### Optional OpenAI backend

Hosted OpenAI inference remains available. Set these values in `.env`:

```dotenv
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-proj-...
LLM_MODEL=gpt-5.4-mini
EMBEDDING_MODEL=text-embedding-3-small
LLM_WORKERS=4
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
