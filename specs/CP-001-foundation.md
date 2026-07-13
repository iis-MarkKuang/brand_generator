# CP-001 — Foundation: config, schemas, deps, Makefile

> Status: done (acceptance tests green; pending first commit)
> Depends on: none
> Phase: 0 Foundation

## Objective
Establish the runnable skeleton: dependency management, typed config from `.env`,
the Pydantic data-contract schemas mirroring `references/design/02-data-contracts.md`,
and a `Makefile` for one-command bring-up. Every later packet imports from this.

## Scope
- `pyproject.toml` (uv-managed): python 3.12, deps: `fastapi`, `uvicorn`, `pydantic>=2`,
  `pydantic-settings`, `httpx`, `structlog`, `pillow`, `python-multipart`, `ruff`, `mypy`, `pytest`.
- `src/common/config.py` — `Settings` (pydantic-settings) reading `.env`; no `os.environ` elsewhere.
- `src/common/schemas.py` — Pydantic models: `RunInput`, `BrandDna`, `PaletteColor`,
  `AssetSpec`, `AssetManifest`, `CriticResult`, `KitManifest`, `OrchestratorEvent`.
  Constraints: `AssetSpec.flux_prompt` ≤ 600 chars, `negative_prompt` ≤ 300 chars
  (token hygiene, T7); `RunInput.run_id` matches `RUN_ID_REGEX` (`^[A-Za-z0-9_-]{1,64}$`).
- `src/common/logging.py` — structlog setup with `run_id`/`agent`/`latency_s` fields; never logs secrets; a `sanitize()` helper strips any known key values.
- `src/common/runs.py` — `RunDir` helper creating/reading the `runs/<run_id>/` layout; `run_id` validated against the regex; path helpers refuse to escape the run dir.
- `Makefile` targets: `deps`, `up`, `down`, `run-demo`, `lint`, `typecheck`, `test`, `check-secrets`.
- New `Settings` fields from `07-security-and-tokens.md` §D: `MAX_UPLOAD_MB`,
  `CORS_ALLOWED_ORIGINS` (list), `TELEGRAM_ALLOWED_CHAT_IDS` (list of int),
  `MAX_TOTAL_VLM_CALLS`, `MAX_TOTAL_RENDERS`, `RUN_TIMEOUT_S`, `NO_CLOUD_VISION`,
  `VLM_IMAGE_DETAIL_FIRST`, `VLM_IMAGE_DETAIL_RECHECK`, `RUN_ID_REGEX`.
- `.env.example` updated with the new keys (already done in the review pass).

## Non-goals
- No agent logic, no HTTP calls to models yet (CP-002).
- No FastAPI app (CP-010), no frontend (CP-011).
- No OpenClaw skill (CP-009).

## Constraints
- Schemas must validate the example JSON in `02-data-contracts.md` byte-for-byte semantically.
- `Settings` must fail fast with a clear message if a required key is a placeholder.
- No secret values in code or logs.

## Acceptance tests
- [ ] `uv sync` succeeds and creates a venv.
- [ ] `python -c "from src.common.config import settings; print(settings.stepfun_vlm_model)"` prints `step-3.7-flash`; `settings.max_total_vlm_calls == 25`.
- [ ] `tests/test_schemas.py` validates all schemas against the `02-data-contracts.md` examples; a `flux_prompt` of 601 chars is rejected; a `run_id` with `/` is rejected.
- [ ] `make lint` and `make typecheck` pass with zero errors.
- [ ] `tools/validate-env.sh` passes (incl. new keys).
- [ ] `make deps` installs python + frontend deps idempotently.

## Relevant context
- Design refs: `references/design/02-data-contracts.md` (schemas), `06-deployment.md` (Makefile targets).
- The `.env`/`.env.example` already exist with all keys.
- Risk: Stepfun `reasoning_effort` and Ollama `think:false` quirks — model them in config as enums now even if unused until CP-002.
