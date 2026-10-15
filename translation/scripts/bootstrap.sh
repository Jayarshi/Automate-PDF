#!/usr/bin/env bash
set -euo pipefail

python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv/bin/pip install -e '.[api,dev]'
.venv/bin/python scripts/setup_model.py

echo "Ready. Activate with: source .venv/bin/activate"
echo "Translate with: local-translate translate --source en --target hi --text 'Hello world.'"

