# Markdown translation with IndicTrans2

## First run

Run these commands from the repository root:

```bash
cd translation2_ai4bharat
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Put the Markdown file you want to translate in the `input/` folder. There is a
sample at `input/guide.md`; replace it with your own file or copy your file
there. The example below translates that Hindi sample into English:

```bash
ollama pull qwen2.5:3b
```

That downloads the LLM used for the consistency pass. Make sure Ollama is
installed and running. If it is not already running, start it in a separate
terminal and leave it running:

```bash
ollama serve
```

Then, from `translation2_ai4bharat/`, run:

```bash
translate-markdown --input input/guide.md --target English \
  --output output/guide_english.md
```

The completed translation will be at `output/guide_english.md`. For your own
file, replace `input/guide.md` with its path and change `--target` (for example
`Hindi`, `hi`, `bn`, `ta`, or `te`). If you omit `--output`, the translated
file is saved beside the input as `<filename>_<target>.md`.

The `--ollama-url http://127.0.0.1:11434` option is the address the program
uses to contact the Ollama service running on your own computer. It is not a
website to open in a browser. Ollama uses that local address by default; only
set the option if your Ollama server is listening elsewhere. You can skip the
LLM consistency pass with `--no-llm`.

If you prefer not to use the sample, a typical command with your own file is:

```bash
translate-markdown --input input/my-document.md --target Hindi
```

That writes `input/my-document_hindi.md`.

The source-language detector requires at least 20 characters of single-language
prose and supports only language pairs available in IndicTrans2. If detection
is uncertain or unsupported, the command stops instead of guessing.

## What it does

- Groups Markdown paragraphs into token-limited chunks. Headings form context
  boundaries; adjacent paragraphs remain together when they fit the IndicTrans2
  input limit.
- Sends each chunk to the matching AI4Bharat IndicTrans2 1B checkpoint. Model
  weights download from Hugging Face on the first run; the code uses the
  official `IndicTransToolkit` preprocessing/postprocessing interface.
- Uses the checkpoint's legacy KV cache for fast autoregressive generation.
  Recent Transformers releases default to a different cache representation;
  the runner selects the legacy cache expected by IndicTrans2.
- Keeps YAML front matter and fenced code blocks unchanged. It protects
  headings, list markers, inline code, URLs, HTML tags and common Markdown
  syntax during translation.
- By default, asks a local Ollama model (`qwen2.5:3b`) at temperature
  zero to make only obvious consistency corrections to names, glossary terms,
  and forms of address. It carries a glossary forward from chunk to chunk and
  supplies neighboring source paragraphs as context. It is not a general
  rewrite or a guarantee of translation accuracy.

You can select another installed model and Ollama endpoint:

```bash
ollama pull qwen2.5:3b
translate-markdown --input input/guide.md --target English \
  --ollama-model qwen2.5:3b --ollama-url http://127.0.0.1:11434
```

To select compute hardware, pass `--device cpu`, `--device cuda`, or leave it
at `auto`. CPU inference can be slow and the 1B model needs substantial
memory. For GPU installations, install the matching PyTorch build for your
CUDA version before installing this project.

### Limitations

This tool does not support arbitrary source languages: both source and target
must be in IndicTrans2's supported English/Indic language set. Automatic
detection can be ambiguous for very short text or documents containing a lot
of multilingual material. Review the output, especially tables, complex nested
Markdown, and language-specific punctuation. Model prompts and temperature
zero reduce consistency drift but cannot guarantee that an LLM changes only
the requested terms.

## Development

```bash
python -m pip install -e '.[dev]'
pytest
```

The tests use fake translation and consistency engines; they do not download
model weights or require Ollama.
