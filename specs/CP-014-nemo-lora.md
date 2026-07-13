# CP-014 — NeMo LoRA fine-tuning optimization leg

> Status: ready
> Depends on: CP-005
> Phase: 4 Stretch (scoring boosters)

## Objective
Prove a **model-specialization** optimization: LoRA-fine-tune FLUX on a small brand-style
dataset via **NVIDIA NeMo** so repeat-brand renders achieve higher palette-match with
fewer prompt tokens. Implement a minimal proof + document the full plan — deepens the
"model optimization" score (rubric 2, 25%).

## Scope
- `nemo/` folder: a minimal LoRA training config for FLUX on a small (5–20 image)
  brand-style dataset (use a sample coffee-brand image set).
- Training script that uses `HF_TOKEN` (`HF_HUB_OFFLINE=0` for this leg only) to pull base
  weights/dataset; produces a LoRA adapter.
- Generator (CP-005) support for loading a LoRA adapter in the ComfyUI workflow (extra
  LoraLoader node) gated by a `lora_adapter` setting.
- Before/after comparison: render the same asset with and without LoRA, run the Critic
  on both, record `palette_match` delta in `docs/optimization-results.md`.
- Full plan documented in `docs/` (dataset strategy, hyperparams, scaling roadmap).

## Non-goals
- No full-scale training (time-boxed minimal proof).
- No fine-tuning Nemotron (only FLUX style adaptation).
- Not required for the core demo — clearly marked as an optimization showcase.

## Constraints
- Time-box: if training can't complete on the Spark in the hackathon window, ship the
  before/after plan + any partial results rather than blocking.
- LoRA adapter files are gitignored (large); record the training config + a manifest hash.
- Do not leave `HF_HUB_OFFLINE=0` set globally; scope it to this leg only.

## Acceptance tests
- [ ] `nemo/` training config is valid and documented.
- [ ] Generator can load a LoRA adapter via the workflow (mocked adapter path) without breaking the non-LoRA path.
- [ ] If training completed: `docs/optimization-results.md` reports a `palette_match` delta (before vs after) on ≥ 1 asset.
- [ ] If training did not complete: `docs/optimization-results.md` documents the plan + partial results + why.
- [ ] `HF_HUB_OFFLINE` is `1` again after this leg (verify in `.env` and config defaults).
- [ ] `tools/check-secrets.sh` passes (no `HF_TOKEN` in tracked files).

## Relevant context
- Design refs: `03-model-optimization.md` (O7 NeMo LoRA specialization).
- This is the highest-risk packet; treat as a stretch goal after CP-011. Even a documented plan + minimal proof scores for "optimization depth."
- NeMo docs + FLUX LoRA community recipes are the reference; cite them in the docs.
