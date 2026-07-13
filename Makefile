SHELL := /bin/bash
PYTHON := uv run python
FRONTEND_DIR := frontend

.PHONY: deps up down run-demo lint typecheck test check-secrets validate-env clean

deps: ## Install python + frontend deps
	uv sync
	@if [ -f $(FRONTEND_DIR)/package.json ]; then \
		echo ">> installing frontend deps"; cd $(FRONTEND_DIR) && npm ci || npm install; \
	else echo ">> frontend not initialized yet (skipped; comes in CP-011)"; fi

up: ## Start FastAPI backend + Vite gallery (CP-010/CP-011)
	@echo ">> starting FastAPI on :8000 (logs: /tmp/styleforge_api.log)"
	@cd . && nohup uv run uvicorn src.orchestrator.api:app --host 0.0.0.0 --port 8000 --log-level warning > /tmp/styleforge_api.log 2>&1 &
	@echo ">> starting Vite gallery on :5173 (logs: /tmp/styleforge_vite.log)"
	@cd $(FRONTEND_DIR) && nohup npm run dev > /tmp/styleforge_vite.log 2>&1 &
	@sleep 3 && echo ">> up: backend http://127.0.0.1:8000  gallery http://127.0.0.1:5173"

down: ## Stop FastAPI + Vite
	@fuser -k 8000/tcp 2>/dev/null || true
	@fuser -k 5173/tcp 2>/dev/null || true

run-demo: check-secrets validate-env ## Run a sample pipeline end-to-end
	$(PYTHON) tools/run_pipeline.py --brand "Ember & Oat" \
		--brief "A warm, craft-first small-batch coffee roaster; hand-drawn serif, espresso and oat cream palette." \
		--ref /home/Developer/build_a_claw_workshop-bundle/sample/sample_face.jpg \
		--assets logo,social_square --run-id demo-001

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
