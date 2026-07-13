# CP-003 — Brand Analyst agent (Stepfun VLM)

> Status: ready
> Depends on: CP-001, CP-002
> Phase: 1 Core agents

## Objective
Implement the Brand Analyst: from a brief + reference image, extract a validated
`BrandDna` JSON. This is stage 1 of the pipeline and defines the brand contract every
downstream agent consumes.

## Scope
- `src/agents/brand_analyst.py` — `async def analyze_brand(brief, image, brand_name) -> BrandDna`.
- Analyst system prompt (in `src/agents/prompts/analyst.md`) enforcing strict-JSON output
  with the exact `BrandDna` fields.
- Image input: convert local path → data URL (or upload) for `step-3.7-flash`.
- `reasoning_effort="high"` for this one-shot extraction.
- Brand-DNA caching: key = `sha1(brief + image_bytes)`; cache to
  `cache/brand_dna/<hash>.json`; return cached on hit, set `cache_hit=True` in log.
- Write `runs/<run_id>/brand_dna.json` (validated).

## Non-goals
- No asset planning (CP-004), no critique (CP-006).
- No multi-image mood boards (single reference for now).

## Constraints
- Output must validate against `BrandDna`; on failure, one repair retry asking the model
  to fix the specific invalid field, then raise.
- Palette must contain hex colors parseable by `Pillow`/`Color` (validate `#RRGGBB`).
- Never send more than one image to control latency/cost.

## Acceptance tests
- [ ] `pytest tests/test_brand_analyst.py` — mocked VLM returns valid JSON → `analyze_brand` returns a `BrandDna` that validates.
- [ ] Mocked invalid JSON → repair retry path returns a valid `BrandDna`.
- [ ] Cache hit path: second call with same input skips the VLM (assert httpx not called).
- [ ] `runs/<run_id>/brand_dna.json` validates with `BrandDna.model_validate_json`.
- [ ] Live smoke (manual): real Stepfun call on a sample image yields a sensible palette (5 hex), mood (5 words), typography_class.

## Relevant context
- Design refs: `01-agents.md` (Agent 1), `02-data-contracts.md` (`brand_dna.json`), `03-model-optimization.md` (O3 high effort, O4 caching).
- Sample image available in workshop: `sample/sample_face.jpg` (use as a stand-in reference for smokes).
- This agent is a *tool* called by the Art Director (CP-004/CP-008), but exposing it as a standalone function first.
