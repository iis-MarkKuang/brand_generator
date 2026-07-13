# StyleForge FLUX LoRA specialization (CP-014)

LoRA-fine-tune FLUX on a small brand-style dataset so repeat-brand renders achieve
higher palette-match with fewer prompt tokens. This is the "model-specialization"
optimization leg (rubric 2, 25%) — a minimal proof + documented full plan.

## What landed

1. **Generator LoRA support** (`src/agents/generator.py`): `build_workflow` now accepts
   `lora_adapter` + `lora_strength` and injects a ComfyUI `LoraLoader` node between the
   checkpoint and the model/clip consumers. Gated by `Settings.lora_adapter` (empty = the
   default non-LoRA path, unchanged). Unit-tested in `tests/test_generator.py`
   (LoRA + no-PuLID, LoRA + PuLID, and no-LoRA-unchanged). The KSampler model and the
   CLIPTextEncode clip inputs are rewired to the LoRA outputs; the VAE is untouched.
2. **Training config** (`lora_config.yaml`): rank 16, alpha 16, attention projections
   (`to_q/to_k/to_v/to_out.0`), 200 epochs, bf16, lr 1e-4, ComfyUI-compatible safetensors
   export.
3. **Training script** (`flux_lora_train.py`): a minimal, config-driven diffusers+peft+
   accelerate FLUX LoRA trainer. Validates the dataset, writes a `training_manifest.json`,
   and runs the loop when the heavy deps are present (returns a clear "deps not installed"
   message otherwise so the orchestrator env stays light).

## Tooling: NeMo vs diffusers+peft

NVIDIA NeMo is the framework for LLM / speech / vision-language model specialization
(Nemotron, Parakeet, etc.). FLUX is a diffusion transformer; its LoRA specialization uses
the HuggingFace stack (`diffusers` + `peft` + `accelerate`) on top of the
NVIDIA-optimized **FLUX-dev-fp8** base checkpoint (Blackwell FP8, the same checkpoint
ComfyUI loads on the GB10). The NVIDIA ecosystem contribution to this leg is therefore:

- the FLUX-dev-fp8 base weights (Blackwell FP8 quantization), and
- the local-first reasoning stack (Nemotron via Ollama) that *drives* the prompts the LoRA
  is trained to render efficiently.

The adapter itself is trained with diffusers+peft (the standard, proven FLUX LoRA path).
`docs/optimization-results.md` records the NeMo install feasibility on this Spark and the
scaling roadmap that maps the same adapter strategy onto a NeMo/Megatron-managed pipeline
for multi-brand specialization at scale.

## NeMo install feasibility (assessed 2026-07-13)

A dry-run resolve through the Clash proxy + Tsinghua PyPI mirror succeeded on this aarch64
Spark:

```
uv pip install --dry-run nemo_toolkit   # exit 0
 + nemo_toolkit
 + torch==2.13.0
 + triton==3.7.1
 + nvidia-nccl-cu13==2.29.7
 + nvidia-cusparse==12.6.3.3
 + scikit-learn==1.9.0   + scipy==1.18.0   + tensorboard==2.20.0   ...
```

So `nemo_toolkit` and its full CUDA-13 dependency tree have aarch64 wheels and are
installable here. The full install (several GB) + a FLUX LoRA training run are time- and
GPU-memory-boxed out for the hackathon window (the GB10's ~120 GiB unified memory is
shared with the live Ollama + ComfyUI demo), so the training leg is shipped as a validated
plan + Generator-side adapter loading rather than a completed run. See
`docs/optimization-results.md` for the partial-results record.

## Dataset strategy

- 5–20 brand-style images per brand (logos, packaging, social squares) placed in
  `nemo/datasets/<brand>/`.
- A `captions.txt` with one caption per image (sorted filename order). Captions embed the
  brand palette hex tokens (e.g. `#4A3728 #C65D3B #F2E8D5`) so the adapter learns the
  palette→style mapping and repeat-brand renders need fewer palette tokens in the prompt.
- The Brand Analyst's `BrandDna.palette` (CP-003) feeds the caption palette tokens — the
  LoRA leg closes the loop between DNA extraction and render-time efficiency.

## Before/after measurement

Render the same `AssetSpec` with `lora_adapter=""` and with the trained adapter, then run
the Critic (CP-006) on both. Record:

- `palette_match` delta (Critic's palette-alignment score, before vs after),
- prompt-token count delta (how many hex tokens can be dropped once the adapter encodes the
  palette),
- render latency delta.

Target: ≥ 1 asset with a positive `palette_match` delta and a reduced prompt-token count.

## Scaling roadmap

1. **Single-brand adapter (this proof):** one LoRA per brand, loaded by the Generator when
   `LORA_ADAPTER` is set. ComfyUI's LoraLoader handles it at render time with no extra
   orchestration.
2. **Multi-brand adapter registry:** store adapters under `nemo/adapters/<brand>/` and have
   the Art Director select the adapter based on `BrandDna.brand_name` — the Generator loads
   the matching adapter per run.
3. **NeMo/Megatron-managed pipeline:** for fleet-scale specialization, move the training
   orchestration onto NeMo (experiment management, distributed training, checkpoint
   versioning) with the diffusers+peft training step as the inner loop. NeMo's role is the
   training-control plane; the model + adapter format stay diffusers/ComfyUI-compatible so
   the inference path (ComfyUI on the GB10) is unchanged.
4. **Adapter cache warming:** pre-load the active brand's adapter into ComfyUI's
   `models/loras/` during the Model Orchestrator's (CP-007) VRAM-swap idle window so the
   first render of a repeat brand pays no adapter-load latency.

## Files

- `lora_config.yaml` — training hyperparameters.
- `flux_lora_train.py` — config-driven trainer (validates dataset, writes manifest, runs
  the loop when heavy deps are present).
- `datasets/<brand>/` — brand-style image set + `captions.txt` (gitignored; the manifest
  records the hash).
- `adapters/<brand>/` — trained LoRA adapters (gitignored; large).
