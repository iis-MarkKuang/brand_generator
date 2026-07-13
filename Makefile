SHELL := /bin/bash
PYTHON := uv run python
FRONTEND_DIR := frontend

.PHONY: deps up down run-demo lint typecheck test check-secrets validate-env clean

deps: ## Install python + frontend deps
	uv sync
	@if [ -f $(FRONTEND_DIR)/package.json ]; then \
		echo ">> installing frontend deps"; cd $(FRONTEND_DIR) && npm ci || npm install; \
	else echo ">> frontend not initialized yet (skipped; comes in CP-011)"; fi

up: ## Start services (stub until CP-010/CP-011)
	@echo ">> 'make up' is a stub until CP-010 (FastAPI) and CP-011 (gallery) land."
	@echo ">> For now run a single pipeline via: make run-demo"

down: ## Stop services (stub until CP-010)
	@echo ">> 'make down' is a stub until CP-010 lands."

run-demo: check-secrets validate-env ## Run a sample pipeline end-to-end (stub until CP-008)
	@echo ">> 'make run-demo' is a stub until CP-008 (orchestrator loop) lands."

lint: ## Ruff lint + format check
	uv run ruff check .
	uv run ruff format --check .

format: ## Ruff format
	uv run ruff format .

typecheck: ## Mypy
	uv run mypy src

test: ## Pytest
	uv run pytest

check-secrets: ## Fail if any secret is tracked/staged
	@bash tools/check-secrets.sh

validate-env: ## Fail if required env vars are missing/placeholder
	@bash tools/validate-env.sh

clean: ## Remove generated run/cache artifacts
	rm -rf runs/ cache/ .pytest_cache .ruff_cache .mypy_cache
