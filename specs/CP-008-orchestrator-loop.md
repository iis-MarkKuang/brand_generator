# CP-008 — Master orchestrator loop + Assembler

> Status: done
> Depends on: CP-003, CP-004, CP-005, CP-006, CP-007
> Phase: 2 Orchestration

## Objective
Wire the agents into the end-to-end run loop driven by the Art Director, and assemble
the final `brand_kit/` + `brand_guide.md` + `kit_manifest.json`. This is the pipeline
that everything else surfaces (API, gallery, OpenClaw, Telegram).

## Scope
- `src/orchestrator/runner.py` — `async def run_pipeline(run_input: RunInput) -> KitManifest`:
  1. Create `RunDir`.
  2. `analyze_brand` (via Brand Analyst, cache-aware).
  3. `plan_assets` (Art Director) → `AssetManifest`.
  4. For each asset (bounded `max_retries_per_asset`):
     - `orchestrator.request_vram("comfyui")` → `generate_asset` → `critic_asset`.
     - On `pass`: mark approved. On fail: `art_director.rewrite_prompt` → re-render.
     - After retries exhausted: mark `failed`, continue (partial-kit resilience).
     - `orchestrator.request_vram("ollama")` when reasoning needed between assets.
  5. `assemble_kit` → write `brand_kit/`, `brand_guide.md`, `kit_manifest.json`.
- `src/agents/assembler.py` — `async def assemble_kit(run_dir, manifest, brand_dna) -> KitManifest`:
  copy approved assets to canonical names, write `brand_guide.md` (palette swatches in
  markdown, typography, dos/don'ts, asset list), emit `kit_manifest.json` with
  `optimization_stats` from the orchestrator log.
- `run.log` writer: every agent call logged (agent, model, latency_s, tokens/steps).
- SSE event emitter hook (consumed by CP-010) — emit per-stage events.

## Non-goals
- No FastAPI server (CP-010), no gallery (CP-011).
- No OpenClaw skill packaging (CP-009) — just the callable pipeline.
- No NIM routing (CP-013) — assume local Ollama available; fail loud if not (until CP-013).

## Constraints
- A single asset failure must not abort the run.
- Total runtime target ≤ ~6 min for a 5-asset kit on the Spark.
- The loop must be cancellable (cooperative cancellation between assets).
- Every intermediate file validated against its schema on write.
- **Token/runtime caps (enforced here):** `MAX_TOTAL_VLM_CALLS` (25), `MAX_TOTAL_RENDERS`
  (20), `RUN_TIMEOUT_S` (600). On any cap, stop iterating and assemble a partial kit
  (T1/T6/T8). An always-fail critic must not cause a runaway.
- Per-asset `rewrite_prompt` only; never re-plan the whole manifest (T5).
- Director context stays text-only; never feed images into it (T4).

## Acceptance tests
- [ ] `pytest tests/test_runner.py` — fully mocked agents: a 3-asset run produces a `KitManifest` with 2 approved + 1 failed (injected critic fail) and does not raise.
- [ ] Cap test: an injected always-fail critic stops at `MAX_TOTAL_VLM_CALLS` (no runaway) and assembles a partial kit.
- [ ] Timeout test: `RUN_TIMEOUT_S` exceeded → partial kit assembled (no hang).
- [ ] `brand_guide.md` contains all palette hex values and the asset list.
- [ ] `kit_manifest.json` validates and includes `optimization_stats` (swap count, effort counts, cache hit).
- [ ] Cancellation: setting a cancel event between assets stops the run cleanly.
- [ ] Golden E2E (manual, on Spark): a real run on the sample input produces a complete kit; record inputs + manifest under `tests/golden/`.
- [ ] `make lint && make typecheck` pass.

## Relevant context
- Design refs: `00-overview.md` (§4 runtime sequence), `01-agents.md` (delegating topology + Assembler), `02-data-contracts.md` (`kit_manifest.json`).
- The Art Director's tool-calling interface (CP-004) is realized here as concrete function calls; keep the tool schema and the calls consistent.
- Partial-kit resilience is a scoring point for "project completeness" (rubric 3).
