# CP-017 — VLM reasoning chain + cross-asset consistency matrix

## Objective
Enhance the Critic agent to perform multi-step visual reasoning (describe →
extract palette from render → compare to Brand DNA → pixel-level fix suggestions)
and add a final cross-asset consistency check that compares all approved assets
for palette/typography/mood coherence, producing a consistency matrix.

## Motivation
The current Critic does a single-pass score. This doesn't showcase the VLM's
deep image understanding. Multi-step reasoning + cross-asset comparison
demonstrates the VLM's ability to ground visual features and compare across
multiple generated images — a key differentiator for Stepfun VLM.

## Changes
- `src/agents/critic.py`: add `critic_deep` mode — 3 VLM calls per asset
  (describe, extract-palette, compare+suggest). Merge into structured result.
- `src/agents/consistency.py` (new): `check_consistency(assets, brand_dna)` —
  VLM compares all approved assets side-by-side, scores consistency per
  dimension (palette, typography, mood, composition), returns matrix.
- `src/common/schemas.py`: add `ConsistencyMatrix` schema.
- `src/orchestrator/runner.py`: call consistency check after all assets approved.
- `src/orchestrator/api.py`: include consistency matrix in manifest + SSE.
- `frontend/src/components/ConsistencyMatrix.tsx` (new): heatmap visualization.
- `tests/test_critic.py` + `tests/test_consistency.py`: unit tests.

## Acceptance
- [x] Deep critic produces 3-step reasoning per asset (visible in log)
- [x] Consistency matrix generated for multi-asset runs
- [x] Matrix visible in gallery UI as heatmap
- [x] All tests pass (87 passing)

## Status: ✅ done
