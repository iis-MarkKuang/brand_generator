# CP-006 — Critic agent (Stepfun VLM)

> Status: done
> Depends on: CP-001, CP-002, CP-003
> Phase: 1 Core agents

## Objective
Implement the Critic: per-asset visual review against the `BrandDna`, returning a
`CriticResult` (pass/fail + scores + actionable feedback). This closes the
generate→critique→refine loop.

## Scope
- `src/agents/critic.py` — `async def critic_asset(png_path, asset_spec, brand_dna, attempt) -> CriticResult`.
- Critic system prompt (`prompts/critic.md`): strict-JSON, score 0–100, sub-scores for
  `palette_match`, `mood_match`, `legibility`, `on_brand`, plus `feedback` that the Art
  Director can act on (which hex to drop, legibility fixes).
- Image input: read the rendered PNG → data URL for `step-3.7-flash`.
- Effort routing (delegated to Model Orchestrator in CP-007, but default here):
  first attempt `medium`, re-checks `low`.
- `pass = score >= 70` (configurable threshold in `Settings`).
- Write `runs/<run_id>/assets/critic__<asset_id>__v<attempt>.json`.

## Non-goals
- No prompt rewriting (Art Director does that in CP-004/CP-008).
- No loop control (CP-008).
- No video critique (image only).

## Constraints
- Strict JSON; one repair retry on parse failure, then a structured "critic_failed" result (never crash the run).
- Never compare against a different run's `BrandDna`.
- Keep `feedback` concrete and < 60 words so the Art Director rewrite is focused.
- `image_url.detail`: `high` for first attempt (legibility needs resolution), `low` for
  re-checks (attempt ≥ 2) — from `VLM_IMAGE_DETAIL_FIRST`/`RECHECK` settings (T2).
- Image is pre-resized to ≤1024px by the client (T3) before this call.

## Acceptance tests
- [ ] `pytest tests/test_critic.py` — mocked VLM returns JSON → `CriticResult` validates; `pass` logic correct at boundary (69/70).
- [ ] Re-check path (attempt ≥ 2) uses `detail="low"` (assert on the mocked request).
- [ ] Repair path: mocked bad JSON → one retry → valid result.
- [ ] `feedback` non-empty when `pass=false`.
- [ ] Live smoke (manual): a real VLM call on a sample rendered PNG + sample `BrandDna` returns sensible sub-scores.
- [ ] `make lint && make typecheck` pass.

## Relevant context
- Design refs: `01-agents.md` (Agent 4), `02-data-contracts.md` (`critic_result.json`), `03-model-optimization.md` (O3 effort routing, O5 bounded loop).
- Palette match should weight hex distance — the prompt instructs the model to compare against the DNA palette list explicitly.
- Repeated identical fails are handled by the loop (CP-008) accept-with-caveat rule, not here.
