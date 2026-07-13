# StyleForge 🎨 — AI Brand Visual-Identity Studio

> A multi-agent, locally-deployed AI studio that turns **one brand brief + one reference
> image** into a **complete, on-brand visual identity kit** (logo, hero banner, social
> posts, product mockup, business card + brand guide).

Built for the **DGX Spark Hackathon** (NVIDIA × Stepfun). Analyzed by a **Stepfun
`step-3.7-flash` VLM**, reasoned by a **local NVIDIA Nemotron-3-Super** art director,
rendered by **ComfyUI FLUX + PuLID**, and quality-gated by a **VLM critic loop** — all
orchestrated by **OpenClaw** on the DGX Spark.

## Why it's different

Existing "AI logo generators" spit out one image with no cross-asset consistency.
StyleForge treats brand identity the way a human art director does: **extract a brand
DNA → plan a coherent asset set → render → critique against the DNA → refine → deliver**.
A model-orchestrator agent also manages the GB10 GPU's shared VRAM (Ollama ↔ ComfyUI
swaps) — a real optimization story, not a wrapper.

## Architecture

See [`docs/architecture.md`](docs/architecture.md) for the full design, agent roles,
model-optimization story, and rubric mapping. Requirements & judging criteria live in
[`docs/hackathon-requirements.md`](docs/hackathon-requirements.md).

```
brief + reference ─► Brand Analyst (Stepfun VLM) ─► brand_dna.json
                        │
                        ▼
              Art Director (Nemotron local) ─► asset_manifest.json
                        │
                        ▼
              Generator (ComfyUI FLUX+PuLID) ─► PNG assets
                        │
                        ▼
              Critic (Stepfun VLM) ─► pass/fail + feedback ── loop back on fail
                        │
                        ▼
              Assembler ─► brand_kit/ + brand_guide.md
```

## Quick start

```bash
# 1. Configure secrets (never commit the real .env)
cp .env.example .env
#   fill in STEPFUN_API_KEY, confirm local hosts/ports

# 2. Load env
set -a; source .env; set +a

# 3. (todo) run the orchestrator + frontend
```

> ⚠️ **Never commit `.env`.** The hackathon code of conduct prohibits leaking API keys.
> `.env` is gitignored; `.env.example` is the public template.

## Tech stack

- **NVIDIA:** NemoClaw/OpenShell (sandboxed agents), Nemotron-3-Super 120B (local
  reasoning via Ollama), ComfyUI FLUX.1-dev fp8 (Blackwell-optimized generation), NeMo
  + NIM (optimization plan).
- **Stepfun (阶跃星辰):** `step-3.7-flash` (multimodal VLM — Brand Analyst & Critic),
  `step-2-mini` (light text fallback).
- **Agent platform:** OpenClaw. **Front-end:** React + Vite gallery + FastAPI backend.

## Status

🚧 Architecture finalized — implementation in progress. See `docs/architecture.md`.
