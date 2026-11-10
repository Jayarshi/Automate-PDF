# Human-reviewed book translation with IndicTrans2

The new workflow uses AI4Bharat IndicTrans2 for base translation and a local LLM
(Qwen through Ollama by default) for terminology discovery and post-editing.
A required human review separates preparation from translation. There is no NLLB
fallback in this workflow. The older CLI/API are retained as explicit legacy
interfaces; see [legacy documentation](docs/legacy-nllb.md).

```text
UTF-8 book text
  → Qwen scans the document and proposes terminology + clarification questions
  → STOP: human fills bilingual glossary, pronouns, honorifics, gender and register
  → validate approval against the source hash and language pair
  → sentence segmentation, token-limit checks, neighboring source context
  → IndicTrans2 batch drafts
  → Qwen applies approved rules and exact terminology to each sentence
  → QA + optional COMET-QE → targeted retry
  → PASS: final text | REVIEW: separate draft + JSON report + review queue
```

## Setup

From this directory, using Python 3.10–3.12:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[indictrans,dev]'
ollama pull qwen2.5:7b-instruct
ollama serve  # if Ollama is not already running
```

Model downloads occur on first translation. Accept any required access conditions
on the Hugging Face checkpoint pages and authenticate locally before running.
The adapter uses the checkpoints' Hugging Face custom code (`trust_remote_code=True`).
After caching the models, `indictrans.local_files_only: true` disables their downloads.
CPU inference is supported; the full 1B checkpoints can be slow and need substantial
memory. CUDA uses FP16. Checkpoint names or local model directories can be changed
in [config/book.yaml](config/book.yaml).

The adapter follows [AI4Bharat's inference interface](https://github.com/AI4Bharat/IndicTrans2/tree/main/huggingface_interface)
and uses [IndicTransToolkit](https://pypi.org/project/indictranstoolkit/) for preprocessing
and postprocessing. English↔Indic and Indic↔Indic use separate checkpoints.
Only English and the [documented IndicTrans2 languages/scripts](https://github.com/AI4Bharat/IndicTrans2#readme)
are accepted. Use aliases such as `en`, `bn`, `hi`, or explicit codes such as
`kas_Deva` and `mni_Mtei` when script matters. French and other unsupported languages
are rejected before any model or LLM call.

## 1. Generate the manual form

```bash
local-translate-book prepare --input data/input.txt --source bn --target en \
  --review data/book.en.review.yaml
```

Alternatively use `.venv/bin/python -m local_nllb.book` in place of
`local-translate-book`. Both commands accept `--config config/book.yaml`.
Preparation scans the whole document in bounded excerpts. It writes an editable
YAML table of glossary rows, entity rules and questions. Suggestions are advisory;
all final target terms and style fields start blank. Existing forms are never overwritten.

Edit the form:

- Fill `style_guide`: register, pronouns, honorifics and gender policy.
- Fill every glossary `target`; remove irrelevant rows or add missing terms.
- Fill entity gender/pronouns/honorifics. Explicit `unknown` or `none` is valid.
- Answer the questions, then set `approved: true`.

An empty glossary is allowed after review. Keep the source hash and language fields
unchanged. Each target language needs its own form. Changing source text invalidates
approval. The approval field is a local human checkpoint, not an authentication system.

## 2. Translate the approved book

```bash
local-translate-book translate --input data/input.txt --source bn --target en \
  --review data/book.en.review.yaml --output data/output/book.en.txt
```

Only the current sentence is translated; two preceding and two following source
sentences provide post-editing context. Approved rules are supplied on every attempt.
Glossary terms remain in the source draft to retain meaning, then the post-editor
must produce their exact approved target forms. Missing terms, lost placeholders,
number mismatches, unchanged source and editing failures require review.
Long sentences exceeding the tokenizer budget stop the run without silent truncation;
split them in the source and prepare a fresh form. Sentence detection is heuristic;
inspect segmentation for abbreviations or complex literary punctuation, or select
an installed spaCy/NLTK backend in the configuration.

Outputs:

- `book.en.txt`: final text, only when all gates pass.
- `book.en.txt.review.txt`: assembled draft when any gate needs human review.
- `book.en.txt.report.json`: segment scores, issues, attempts, raw drafts and approved rules.
- `data/review/books.jsonl`: failed document/segment details for human review.

Output files must be new paths. Exit status is `0` for success, `2` for review and
`1` for an error. Source line breaks and indentation are retained; this operates on
plain text and does not reconstruct PDF/DOCX typography. Preparation and translation
are separate resumable stages; interrupted translation currently restarts that stage.

## Semantic scoring

The supplied profile deliberately sends every book to human review until COMET-QE
is enabled. Structural heuristics cannot certify semantic fidelity.

```bash
pip install -e '.[comet]'
# Set quality.comet_enabled: true in config/book.yaml
```

Calibrate thresholds on human-reviewed examples for the target language/domain.
COMET-QE is a reference-free signal, not a guarantee. chrF++/BLEU require trusted
references and remain available through the legacy evaluation interface; they must
not be computed against the machine draft as a quality certificate.

## Verification

```bash
.venv/bin/python -m pytest
```

Tests use fake engines/LLM responses and do not download weights. An actual model
run is necessary to measure translation quality on your books. The old
`scripts/translate.py`, `local-translate`, `local-translate-job`, and REST API still
use the legacy NLLB configuration; use `local-translate-book` for this new workflow.
