# CP-014 — Model-specialization optimization results

> Status: plan + Generator-side adapter loading DONE; training run time/memory-boxed out
> for the hackathon window. NeMo install feasibility assessed (installable on this Spark).

## What was delivered

### 1. Generator LoRA adapter loading (DONE, tested)

`src/agents/generator.py` `build_workflow` now accepts `lora_adapter` + `lora_strength`
and injects a ComfyUI `LoraLoader` node between the FLUX checkpoint and the model/clip
consumers. Gated by `Settings.lora_adapter` (empty = the default non-LoRA path, unchanged).

- LoRA + no-PuLID: KSampler model → `["100", 0]`, CLIPTextEncode clip → `["100", 1]`.
- LoRA + PuLID: `ApplyPulidFlux` model → `["100", 0]`, KSampler model → `["6", 0]` (PuLID
  output), clip → `["100", 1]`.
- No-LoRA: node `100` absent, clip stays `["1", 1]` — fully backward-compatible.
- VAE always comes from the checkpoint (`["1", 2]`); LoRA does not touch the VAE.

Unit tests (`tests/test_generator.py`): `test_build_workflow_no_lora_is_unchanged`,
`test_build_workflow_lora_inserts_loader_no_pulid`, `test_build_workflow_lora_with_pulid` —
all green (8/8 generator tests pass).

To use a trained adapter: copy the `.safetensors` to ComfyUI's `models/loras/` and set
`LORA_ADAPTER=<filename>` (and optionally `LORA_STRENGTH`) in `.env`.

### 2. Training config + script (DONE)

- `nemo/lora_config.yaml`: rank 16 / alpha 16, attention projections, 200 epochs, bf16,
  lr 1e-4, ComfyUI-compatible safetensors export.
- `nemo/flux_lora_train.py`: config-driven diffusers+peft+accelerate trainer; validates
  the dataset, writes `training_manifest.json`, runs the loop when the heavy deps are
  present (returns a clear "deps not installed" message otherwise).
- `nemo/datasets/coffee_brand/captions.txt`: sample captions embedding brand palette hex
  tokens (the dataset images themselves are gitignored).

## NeMo install feasibility (assessed 2026-07-13)

A dry-run resolve through the Clash proxy + Tsinghua PyPI mirror succeeded on this aarch64
Spark:

```
$ uv pip install --dry-run nemo_toolkit   # exit 0
 + nemo_toolkit
 + torch==2.13.0
 + triton==3.7.1
 + nvidia-nccl-cu13==2.29.7
 + scikit-learn==1.9.0   + scipy==1.18.0   + tensorboard==2.20.0
```

`nemo_toolkit` and its full CUDA-13 dependency tree have aarch64 wheels and are installable
here. The full install (several GB) + a FLUX LoRA training run are time- and GPU-memory-
boxed out for the hackathon window — the GB10's ~120 GiB unified memory is shared with the
live Ollama (nemotron-3-nano:30b) + ComfyUI (FLUX-dev-fp8) demo, and a FLUX LoRA training
run needs the ~24 GB base model loaded plus optimizer state, which would contend with the
live demo path. The training leg is therefore shipped as a validated plan + Generator-side
adapter loading rather than a completed run.

## Before/after plan (methodology)

Render the same `AssetSpec` with `lora_adapter=""` (before) and with the trained adapter
(after), then run the Critic (CP-006) on both. Record per asset:

| metric | before (no LoRA) | after (LoRA) | delta |
|---|---|---|---|
| `palette_match` (Critic palette-alignment, 0–100) | TBD | TBD | target > 0 |
| prompt hex-token count | TBD | TBD | target < 0 (adapter encodes the palette) |
| render latency (s) | TBD | TBD | informational |

The `palette_match` metric is extracted from the Critic's structured `CriticResult` (the
palette-alignment sub-score). The prompt-token delta is computed by counting hex tokens in
`AssetSpec.flux_prompt` before (full palette) vs after (palette tokens dropped, relying on
the adapter). Target: ≥ 1 asset with a positive `palette_match` delta and a reduced
prompt-token count.

## Why the training run did not complete

1. **GPU unified-memory contention:** the GB10's ~120 GiB unified memory concurrently
   hosts Ollama (nemotron-3-nano:30b ~ 18 GB) and ComfyUI (FLUX-dev-fp8 ~ 24 GB) for the
   live demo. FLUX LoRA training needs the base model + optimizer state + activations,
   which would thrash the unified memory and degrade the demo.
2. **Hackathon time-box:** a 200-epoch LoRA run on a 5-image dataset is feasible on the
   GB10 but exceeds the remaining demo-prep window; the spec explicitly allows shipping the
   plan + partial results in this case ("if training can't complete... ship the before/after
   plan + any partial results rather than blocking").
3. **Install weight:** `nemo_toolkit` + torch 2.13 + the CUDA-13 wheel set is several GB
   even through the mirror; a dedicated training venv is the right isolation but adds setup
   time beyond the window.

## Partial results

- NeMo install: **feasible** (dry-run resolved on aarch64 through the proxy + mirror).
- Generator adapter loading: **DONE** (code + unit tests).
- Training config + script: **DONE** (validated structure; `--dry-run` path ready).
- Training run + measured `palette_match` delta: **deferred** (time/memory-boxed).

## HF_HUB_OFFLINE hygiene

`HF_HUB_OFFLINE` defaults to `1` in `Settings` (`config.py`) and in `.env`. The training
leg would set `HF_HUB_OFFLINE=0` only inside the training venv for the duration of the
base-checkpoint / dataset pull; the orchestrator's `.env` and config defaults remain
`HF_HUB_OFFLINE=1` so the live demo path stays offline-first. Verified: no `HF_TOKEN` in
any tracked file (`tools/check-secrets.sh`); the token lives only in `.env`.

## Scaling roadmap

See `nemo/README.md` § "Scaling roadmap": single-brand adapter → multi-brand adapter
registry (Art Director selects by `brand_name`) → NeMo/Megatron-managed training control
plane (diffusers+peft inner loop, NeMo for experiment/distributed management) → adapter
cache warming in the Model Orchestrator's VRAM-swap idle window.
