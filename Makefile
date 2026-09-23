.PHONY: setup test lint demo

setup:
	UV_CACHE_DIR=.state/uv-cache uv sync --frozen
	python3 scripts/bootstrap.py

test:
	PYTHONPATH=src .venv/bin/python -m pytest -q

lint:
	.venv/bin/ruff check src tests scripts

demo:
	PYTHONPATH=src .venv/bin/python -m autonomy_lab.cli demo
