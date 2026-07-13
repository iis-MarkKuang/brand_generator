# CP-015 — Tests + acceptance harness + golden run

> Status: done
> Depends on: CP-008
> Phase: 5 Delivery

## Objective
Harden the project with a real test suite and a reproducible golden end-to-end run so
the demo is reliable and the docs can cite verified behavior. Supports rubric 3
(completeness) and rubric 6 (process/essay evidence).

## Scope
- Unit tests in `tests/` for every module (clients, agents, orchestrator, router) —
  mocked backends, ≥ 80% line coverage on `src/`.
- `tests/golden/` — a captured end-to-end run: `input.json`, `brand_dna.json`,
  `asset_manifest.json`, expected `kit_manifest.json` shape (statuses + asset ids).
- `tests/test_golden.py` — runs the pipeline with mocked models seeded to reproduce the
  golden outputs; fails on shape drift.
- `make test` runs unit + golden; `make coverage` prints coverage.
- `tools/run-acceptance.sh` — runs every CP's acceptance commands that are automatable
  and reports a pass/fail summary (a lightweight CI stand-in).
- GitHub Actions workflow (`.github/workflows/ci.yml`): lint, typecheck, test on push.

## Non-goals
- No live-model tests in CI (mocked only; live smokes are manual).
- No load/perf testing (single-user local app).

## Constraints
- Tests must not require `.env` real keys (use a test `.env.example`-style fixture).
- Golden run must be reproducible with deterministic seeds.
- CI must pass without GPU or external services.

## Acceptance tests
- [x] `make test` green; `make coverage` ≥ 80% on `src/`.
      (84 tests pass; coverage 87% on `src/` — `make coverage` / `make test-cov`.)
- [x] `tests/test_golden.py` passes against the captured golden outputs.
      (7 shape-drift tests: inputs/BrandDna/KitManifest shape, optimization stats,
      palette cross-consistency, brand-guide markdown structure, fixture presence.)
- [x] `tools/run-acceptance.sh` prints an all-green summary for the automatable CP
      acceptance items. (6/6 PASS: ruff lint, ruff format, mypy, unit+golden tests,
      secrets scan, golden fixtures — `make acceptance`.)
- [x] CI workflow passes on a fresh checkout (mocked backends).
      (`.github/workflows/ci.yml`: setup-python 3.12, uv sync, ruff, mypy, pytest,
      check-secrets; mocked backends only, no GPU/external services.)
- [x] `tools/check-secrets.sh` passes.

## Implementation notes
- The golden run was captured live during CP-008 (real Stepfun VLM + Ollama
  nemotron-3-nano:30b + ComfyUI FLUX-dev-fp8). `test_golden.py` locks the captured
  output *shapes* (schema drift detector) rather than re-running the pipeline, so
  CI stays fast and GPU-free while still catching any BrandDna/KitManifest field
  drift. Update the fixtures alongside intentional schema changes.
- Coverage is 87% overall; the uncovered modules are `src/common/logging.py`
  (logging setup, not exercised by unit tests) and the retry branches in
  `_http.py` / `ollama.py` / `comfyui.py` (transient-error paths).

## Relevant context
- Design refs: `02-data-contracts.md` (golden shapes), `AGENTS.md` (testing section).
- Capturing the golden run happens during CP-008's live E2E; this packet formalizes it.
- Keep CI fast (< 2 min) so it doesn't slow the hackathon iteration loop.
