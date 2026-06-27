.PHONY: setup dev lint format typecheck test check install-pre-commit clean

# ── First-time setup ──────────────────────────────────

UNAME := $(shell uname)
UNAME_M := $(shell uname -m)

setup: sync install-pre-commit lint
	@echo "✓ Setup complete. Ready to develop."

sync:
ifeq ($(UNAME)-$(UNAME_M), Darwin-arm64)
	uv sync --extra dev --extra mlx
else
	uv sync --extra dev
endif

sync-all:
ifeq ($(UNAME)-$(UNAME_M), Darwin-arm64)
	uv sync --extra dev --extra mlx
else
	@echo "MLX extras are Apple Silicon only; installing dev extras."
	uv sync --extra dev
endif

install-pre-commit:
	uv run pre-commit install

# ── Quality checks ────────────────────────────────────

lint:
	uv run ruff check src/

format:
	uv run ruff format src/

typecheck:
	uv run mypy src/ --strict

test:
	uv run pytest tests/ -v

check: lint typecheck test
	@echo "✓ All checks passed."

# ── Housekeeping ──────────────────────────────────────

clean:
	rm -rf dist/ build/ *.egg-info/ .ruff_cache/ .mypy_cache/ .pytest_cache/ htmlcov/ .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
