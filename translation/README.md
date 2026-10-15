# Local NLLB Translation Pipeline

A local-first, zero-API-cost translation service centered on NLLB-200 and
CTranslate2. It supports CPU INT8 and GPU FP16 inference, optional local LLM
post-editing, glossaries, automatic scoring, retries, and a human-review queue.

> **License warning:** the default Meta NLLB checkpoint is licensed
> CC-BY-NC-4.0. It is free for permitted non-commercial use, but it is not a
> permissive commercial model. Review the [NLLB model card](https://huggingface.co/facebook/nllb-200-distilled-600M)
> and the licenses of any Ollama/vLLM and COMET checkpoints before deployment.

## Architecture

```text
UTF-8 text / file / REST request
       │
       ▼
Sentence segmentation + token-aware chunking
(regex default; spaCy, Sacremoses, NLTK optional)
       │
       ▼
Glossary / URL / email sentinel protection
       │
       ▼
NLLB-200 distilled 600M → CTranslate2 batch inference
(INT8 CPU default; FP16 or INT8-FP16 on CUDA)
       │
       ▼
Optional conservative post-editing
(Ollama native API or vLLM OpenAI-compatible API)
       │
       ▼
Restore protected terms + quality evaluation
├─ Always: empty/length/copy/repetition/glossary/placeholder checks
├─ Production, optional: reference-free COMET-QE
└─ Evaluation sets: chrF++ + BLEU with a trusted reference
       │
       ├─ pass → translated text
       └─ fail → larger-beam retry → JSONL human-review queue
```

BLEU and chrF++ require a trusted human reference. They are deliberately not
computed by comparing the polished output with raw NLLB output, because that
would produce a misleading quality score. For live traffic, enable COMET-QE.

## Quick start (CPU, INT8)

Requirements: Python 3.10–3.12, about 5 GB free disk during setup, and enough
RAM to convert/load the 600M model. The one-time model download needs internet;
inference itself is local.

```bash
./scripts/bootstrap.sh
source .venv/bin/activate

local-translate translate \
  --source en --target hi \
  --text 'Translation should be accurate and natural.'
```

The bootstrap creates a virtual environment, installs the service and test
tools, downloads the Hugging Face checkpoint, and creates an INT8 CTranslate2
model. For separate steps:

```bash
make install
make model
make test
```

Model conversion can be customized:

```bash
.venv/bin/python scripts/setup_model.py --quantization float16 \
  --output-dir models/nllb-200-distilled-600M-ct2-fp16
```

Then update `nllb.model_path`, `nllb.device: cuda`, and
`nllb.compute_type: float16` in the YAML configuration.

## CLI

### Easiest: edit one job file

For a repeatable run, edit `config/translation-job.yaml`:

1. Put the source text in `data/input.txt`.
2. Set `source_language` and one or more entries under `target_languages`.
3. Run `.venv/bin/python scripts/translate.py`.
4. Read the translations and quality reports in `data/output/`.

With the supplied example (`en` to `hi`), the files will be:

```text
data/output/input.hi.txt          # translated text to review
data/output/input.hi.report.json  # score, issues, raw output, and segment details
```

Add targets such as `bn` and `fr` to create one output pair per language. The
runner prints `PASS` or `REVIEW`; `REVIEW` means the output was still saved but
also needs human checking. The NLLB model must first exist under `models/`—run
`.venv/bin/python scripts/setup_model.py` once if it has not been downloaded.

### Direct command

Translate stdin, a file, or literal text:

```bash
printf 'Hello world.' | local-translate translate --source en --target bn

local-translate translate --source eng_Latn --target fra_Latn \
  --input source.txt --output translated.txt --tone formal

local-translate translate --source en --target hi --input source.txt \
  --glossary config/glossary.example.yaml --json
```

Aliases such as `en`, `hi`, `bn`, and `fr` are accepted. Any official NLLB
language code such as `eng_Latn`, `hin_Deva`, or `zho_Hans` can be passed
directly. Run `local-translate --help` for all options. Exit code `2` means the
translation was produced but failed the quality gate and was queued for review.

To score against a real reference:

```bash
local-translate translate --source en --target fr --input source.txt \
  --reference trusted-french.txt --json
```

## Local LLM post-editor

The post-editor is off by default because NLLB should remain the reliable core
and an LLM can alter facts. When enabled, the prompt is conservative, requests
JSON only, fixes tone/artifacts, and requires every protected placeholder to be
preserved. Restoration and the quality gate catch missing placeholders.

With Ollama:

```bash
ollama pull qwen2.5:7b-instruct
ollama serve
local-translate --config config/with-ollama.yaml translate \
  --source en --target hi --tone academic --input source.txt
```

To use vLLM, set `post_edit.provider: vllm`, set `model` to the served model
name, and use a base URL such as `http://127.0.0.1:8000/v1`. Both providers are
called over localhost with Python's standard library; no paid SDK or cloud API
is used.

## Quality gate

The default lightweight gate has no extra model. It catches structural failure,
but it cannot reliably judge semantic fidelity. For unattended production,
install and enable the reference-free COMET model:

```bash
.venv/bin/pip install -e '.[comet]'
# Set quality.comet_enabled: true in config/default.yaml
```

COMET downloads its checkpoint once and then runs locally. `threshold`, length
and copy-ratio limits, and `max_retries` are all in `config/default.yaml`.
Failed records are appended to `data/review/flagged.jsonl` with source, raw and
final translations, metrics, issues, and `pending_human_review` status.

Treat the default `0.72` as a starting point, not a universal truth. Calibrate
it per language pair and domain using a labeled validation set. BLEU is reported
for compatibility; chrF++ and COMET are generally more useful for gating.

## REST API

```bash
make api
curl -s http://localhost:8080/v1/translate \
  -H 'content-type: application/json' \
  -d '{
    "text": "A careful translation.",
    "source_lang": "en",
    "target_lang": "hi",
    "tone": "formal",
    "glossary": {"translation": "अनुवाद"}
  }'
```

`GET /health` is lightweight and does not load the model. The first translation
loads NLLB lazily. Calls are serialized because the tokenizer carries mutable
source-language state; scale horizontally with multiple API workers/containers
when necessary.

## Docker

Build the image only after `make model`; model files are mounted rather than
baked into the image:

```bash
docker compose up --build translator
```

To start the optional Ollama container too:

```bash
docker compose --profile llm up -d ollama
docker compose exec ollama ollama pull qwen2.5:7b-instruct
```

Enable post-editing by mounting or selecting `config/with-ollama.yaml` as
`TRANSLATION_CONFIG`. GPU passthrough is host/runtime-specific and intentionally
not forced in the portable Compose file.

## Segmentation and terminology

`regex` is dependency-free and handles common Latin, Indic, and CJK sentence
terminators. Alternatives are selected with `segmentation.backend`:

```bash
pip install -e '.[spacy]'
# or
pip install -e '.[nltk]'
```

NLTK Punkt resources and spaCy language models must be downloaded explicitly.
Sacremoses is installed in the base environment. Large sentences are split by
the actual NLLB tokenizer count, not character length. Source line endings, blank lines,
indentation, and trailing newlines are preserved exactly in translated output.

Glossary keys found in the source are replaced with sentinels before NLLB and
restored to their configured target forms afterward. URLs and email addresses
receive the same treatment. For names that must never be transliterated, put
them in the glossary (mapping a name to itself is valid). This deterministic
approach is safer than relying on an LLM to recognize every domain entity.

## Configuration profiles

- `config/default.yaml`: CPU INT8, NLLB only, lightweight quality gate.
- `config/with-ollama.yaml`: same NLLB path with Ollama post-editing enabled.
- `.env.example`: endpoint/config overrides.

All components are lazy-loaded. Config validation therefore works without
downloading or initializing models:

```bash
local-translate --config config/default.yaml validate-config
```

## Project layout

```text
src/local_nllb/
  segment.py       sentence splitting, token limits, batching
  protect.py       glossary and structured-entity sentinels
  engines/nllb.py  CTranslate2 NLLB adapter
  engines/postedit.py  Ollama/vLLM adapters and prompt
  quality.py       heuristics, COMET-QE, chrF++, BLEU
  pipeline.py      orchestration, retry, review queue
  cli.py / api.py  CLI and FastAPI entry points
config/             deployable YAML profiles and sample glossary
scripts/            environment/model setup
tests/              model-free unit and integration tests
```

## Operational notes

- Do not send secrets or private text to a remotely hosted Ollama/vLLM endpoint
  unless that deployment is trusted; the project assumes localhost.
- Keep a held-out, human-reviewed test set for every important language/domain.
- Glossary protection is exact/Unicode-text based. Normalize upstream text if
  your source can contain multiple Unicode representations.
- A failed post-editor request falls back to raw NLLB, records the failure, and
  still passes through the quality gate.
- The repository code is MIT licensed. Model and dataset licenses are separate.
