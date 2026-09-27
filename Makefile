# Development entrypoints. Every gate here also runs in CI.
.DEFAULT_GOAL := help
.PHONY: help install fmt lint typecheck test test-slow check clean schema

help: ## Show available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Sync all workspace packages and dev dependencies
	uv sync --all-packages

fmt: ## Apply formatting and import sorting
	uv run ruff format packages tests
	uv run ruff check --fix packages tests

lint: ## Check formatting and lint rules (no writes)
	uv run ruff format --check packages tests
	uv run ruff check packages tests

typecheck: ## Strict type checking
	uv run mypy

test: ## Fast tests (excludes real renders)
	uv run pytest -m "not slow and not network"

test-slow: ## Golden render tests (real Manim, minutes)
	uv run pytest -m slow

check: lint typecheck test ## Everything CI runs

schema: ## Export the Visual IR JSON Schema
	uv run manorem schema --out docs/schema

clean: ## Remove caches and render output
	rm -rf .pytest_cache .mypy_cache .ruff_cache .hypothesis out media
	find . -type d -name __pycache__ -not -path './.venv/*' -exec rm -rf {} + 2>/dev/null || true






