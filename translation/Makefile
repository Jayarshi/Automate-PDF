.PHONY: install model test lint api docker

install:
	python3 -m venv .venv
	.venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
	.venv/bin/pip install -e '.[api,dev]'

model:
	.venv/bin/python scripts/setup_model.py

test:
	.venv/bin/pytest

lint:
	.venv/bin/ruff check .

api:
	.venv/bin/local-translate-api

docker:
	docker compose up --build translator
