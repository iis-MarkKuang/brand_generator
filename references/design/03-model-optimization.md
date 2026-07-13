# 03 — Model Optimization Design

> This is the differentiated story for judging criterion 2 (Agent integration & model
> optimization depth, 25%). Every item here must be **observable** in
> `orchestrator_log.json` + `run.log` so the docs/demo can prove it.

## O1 — GPU unified-memory scheduling agent (the centerpiece)

**Problem:** The DGX Spark's GB10 is a Grace-Blackwell **integrated GPU** with **~120 GiB
of unified memory** shared between CPU and GPU (verified on-spark: Ollama reports
`total 119.7 GiB / available 111.9 GiB`; `nvidia-smi` reports memory as `[N/A]` because
it is unified, not discrete VRAM). A large resident LLM (Nemotron) and FLUX cannot both
hold big chunks of that pool at the same time — the workshop itself runs
`ollama models unloaded (free GPU memory for ComfyUI)` before each render, and the bundle
serves Ollama with `OLLAMA_KEEP_ALIVE=5s` so an idle model releases memory within 5 s.

**Solution:** The **Model Orchestrator agent** owns a small state machine:

```
state: IDLE ──reason_needed──► REASONING (Ollama loaded)
                                   │
                              reason done
                                   ▼
                              GENERATING (Ollama unloaded, ComfyUI hot)
                                   │
                              render done
                                   ▼
                              REASONING ... (loop)
```

- `request_vram("ollama")` → `ollama stop <model> --keepalive 0` equivalent, poll
  `nvidia-smi` until VRAM < threshold, return ok.
- `request_vram("comfyui")` → ensure Ollama unloaded, confirm ComfyUI health on :8200.
- Decisions are **predictive**: the Art Director declares its next stage
  (`next_stage: generate`), so the Orchestrator pre-swaps during the critic call
  (network-bound) instead of serially blocking.

**Evidence:** `orchestrator_log.json` records every swap with VRAM before/after and
latency; the demo video shows the swap log streaming alongside renders.

## O2 — FLUX fp8 on Blackwell Tensor Cores

- ComfyUI launched with `--fast` (Blackwell FP8 Tensor Core path, per workshop bundle).
- Exposed tunables the Art Director/Critic can influence: `steps` (default 24, drop to
  18 on retry to save time), `cfg`, `size`. The Critic's `legibility` score can trigger
  a step bump on the next attempt.
- Documented trade-off table in the project doc (quality vs. latency vs. VRAM).

## O3 — Reasoning-effort routing for the VLM

`step-3.7-flash` exposes `reasoning_effort: low|medium|high`. The Orchestrator sets it
per call:

| Call | Effort | Rationale |
|---|---|---|
| Brand Analyst (once) | high | one-shot deep extraction |
| Critic, first attempt | medium | fair assessment |
| Critic, re-checks | low | fast boolean re-check |

`optimization_stats` in `kit_manifest.json` counts each tier to prove the routing ran.

## O4 — Brand-DNA caching

- Cache key = `sha1(brief + reference_image_bytes)`.
- On a cache hit, skip the Brand Analyst VLM call entirely → saves ~20s and a cloud
  call on repeat/iterate runs (e.g. "tweak the banner" reuses the DNA).
- Cache stored in `cache/brand_dna/<hash>.json`; `brand_dna_cache_hit` reported in
  manifest.

## O5 — Bounded critic loop with smart retry

- `max_retries_per_asset` (default 2). Critic feedback is fed back to the Art Director
  to **rewrite the prompt** (not blindly re-render the same prompt).
- Repeated identical fails → accept-with-caveat (avoids infinite loop; logged).
- On `legibility`-flagged fails, bump `steps`; on `palette_match` fails, the Art
  Director injects explicit hex tokens into the prompt.

## O6 — Local↔cloud model routing (CP-013)

- Default reasoning = local Nemotron (Ollama). If Ollama is unavailable/overloaded, the
  Orchestrator routes the Art Director's call to **NVIDIA NIM cloud**
  (`integrate.api.nvidia.com`) using `NVIDIA_API_KEY`, model
  `nvidia/llama-3.3-nemotron-super-49b-v1.5` (verified available on the NIM catalog).
- This demonstrates **NVIDIA SDK breadth** (NemoClaw routed-inference concept) and gives
  a resilience story. Routing decisions logged.

## O7 — (Optimization plan, documented) NeMo LoRA specialization (CP-014)

- Forward-looking: LoRA-fine-tune FLUX on a brand-style dataset via **NVIDIA NeMo** so
  repeat clients get style-locked renders with fewer prompt tokens and higher
  palette-match scores.
- For the hackathon we **implement a minimal proof** (small LoRA, before/after palette-
  match comparison on one brand) and **document the full plan**. `HF_TOKEN` is used here
  to pull base weights/datasets (`HF_HUB_OFFLINE=0` for this leg only).

## Optimization evidence summary (what the docs will cite)

- VRAM swap count + saved blocking time (O1).
- Latency table: effort-low vs effort-high critic calls (O3).
- Cache-hit runs (O4).
- Retry behavior: prompt-rewrite vs blind-retry success rate (O5).
- Local vs cloud routing events (O6).
- LoRA before/after palette-match delta (O7, if executed).
