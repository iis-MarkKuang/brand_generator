# 00 — StyleForge Architecture Overview

> Single source of truth for the system design. All other `references/design/*.md`
> files elaborate a slice of this. The coding-agent harness (`AGENTS.md`,
> `.cursor/rules/`, `specs/`) must stay consistent with this document.

## 1. One-paragraph product definition

StyleForge is a **multi-agent, locally-deployed AI studio** that turns one brand brief
+ one reference image into a complete, on-brand visual-identity kit (logo lockups, hero
banner, social square, product mockup, business card + a written brand guide). A
**Stepfun `step-3.7-flash` VLM** extracts the brand DNA, a **local NVIDIA Nemotron-3-Super**
acts as art director and planner, **ComfyUI FLUX + PuLID** renders each asset, and a
**VLM critic loop** quality-gates every output against the brand DNA — all orchestrated
by **OpenClaw** on the DGX Spark, with a **model-orchestrator agent** managing the GB10
GPU's shared VRAM between Ollama and ComfyUI.

## 2. Top-level architecture diagram

```
                          ┌──────────────────────────────────────────────────┐
   User (chat / web / TG) │  OpenClaw Gateway :3030  (NemoClaw OpenShell      │
                          │  sandbox, routed inference, policy)               │
                          │  Master Skill: "styleforge"                       │
                          └──────────────────────┬───────────────────────────┘
                                                 │ brief + reference image
                          ┌──────────────────────▼───────────────────────────┐
                          │  Orchestrator Service  (FastAPI :8000)            │
                          │  holds run state, drives the agent loop           │
                          └──────────────────────┬───────────────────────────┘
                                                 │
   ┌─────────────────────────────────────────────┼──────────────────────────┐
   │                                             │                          │
   ▼                                             ▼                          ▼
┌─────────────────┐                  ┌──────────────────────┐     ┌──────────────────┐
│ Brand Analyst   │                  │ Art Director         │     │ Model            │
│ (Stepfun VLM)   │                  │ (Nemotron local)     │     │ Orchestrator     │
│ → brand_dna.json│                  │ → asset_manifest.json│     │ (GPU swap        │
│ cloud           │                  │ local                │     │  scheduler)      │
└────────┬────────┘                  └──────────┬───────────┘     └────────┬─────────┘
         │                                      │                          │
         │                                      ▼                          │
         │                         ┌──────────────────────────┐            │
         │                         │ Generator (ComfyUI       │◄───────────┘
         │                         │ FLUX+PuLID, Blackwell    │  pre-swap VRAM
         │                         │ fp8 fast) → PNG assets   │
         │                         └──────────┬───────────────┘
         │                                    │
         │                         ┌──────────▼───────────────┐
         │                         │ Critic (Stepfun VLM)     │
         │                         │ pass/fail + feedback     │
         │                         │ vs brand_dna             │
         │                         └──────────┬───────────────┘
         │                                    │ fail → refined prompt (max N)
         │                                    ▼
         │                         ┌──────────────────────────┐
         └────────────────────────►│ loop until all pass      │
                                   └──────────┬───────────────┘
                                              ▼
                                   ┌──────────────────────────┐
                                   │ Assembler → brand_kit/   │
                                   │ + brand_guide.md         │
                                   └──────────┬───────────────┘
                                              ▼
                                   Brand Kit Gallery (React :5173)
                                   + OpenClaw Web UI MEDIA: preview
                                   + Telegram (always-on)
```

## 3. Component inventory

| Component | Location | Tech | Port | Change packet |
|---|---|---|---|---|
| OpenClaw Gateway | local | OpenClaw | 3030 | CP-009 |
| NemoClaw sandbox | local | OpenShell | — | CP-012 |
| Orchestrator service | local | FastAPI | 8000 | CP-010 |
| Brand Kit Gallery | local | React + Vite | 5173 | CP-011 |
| Brand Analyst agent | cloud | Stepfun `step-3.7-flash` | — | CP-003 |
| Art Director agent | local | Nemotron-3-Super (Ollama) | 11434 | CP-004 |
| Generator agent | local | ComfyUI FLUX+PuLID | 8200 | CP-005 |
| Critic agent | cloud | Stepfun `step-3.7-flash` | — | CP-006 |
| Model Orchestrator | local | Python scheduler | — | CP-007 |
| Master loop + Assembler | local | Python | — | CP-008 |
| NVIDIA NIM router | cloud | `integrate.api.nvidia.com` | — | CP-013 |
| NeMo LoRA leg | local | NVIDIA NeMo | — | CP-014 |
| Telegram bridge | cloud→local | NemoClaw Telegram | — | CP-012 |

## 4. End-to-end runtime sequence

1. User submits `{brief: str, reference_image: path|url, brand_name: str}` via the
   Gallery, OpenClaw chat, or Telegram.
2. Orchestrator starts a **run** (unique `run_id`, working dir `runs/<run_id>/`).
3. **Brand Analyst** (VLM) reads the reference image + brief → writes `brand_dna.json`.
4. **Art Director** (Nemotron) reads `brand_dna.json` → writes `asset_manifest.json`
   (list of asset specs, each with FLUX prompt + composition + size + `uses_pulid`).
5. **Model Orchestrator** unloads Ollama models → frees VRAM for ComfyUI.
6. For each asset: **Generator** runs the ComfyUI workflow → PNG. **Critic** (VLM)
   scores it vs `brand_dna`. Fail → Art Director rewrites that asset's prompt → re-render
   (bounded to `max_retries` per asset, default 2).
7. **Model Orchestrator** reloads Nemotron when reasoning is needed between renders.
8. When all assets pass (or retries exhausted), **Assembler** writes
   `brand_kit/{logo,banner,social,mockup,card}.png` + `brand_guide.md` + `kit_manifest.json`.
9. Gallery polls/SSE the run and renders the board; OpenClaw chat emits `MEDIA:` lines;
   Telegram sends the kit back to the chat.

## 5. Design principles

- **Local-first, cloud for vision.** Reasoning + generation stay on the DGX Spark (data
  privacy, no per-token cost for the heavy loop); only the VLM understanding/critique
  steps use Stepfun cloud.
- **Delegation, not a script.** The Art Director is a real delegating agent — it calls
   Analyst/Generator/Critic as tools and decides retry strategy from critic feedback.
- **Optimization is a first-class agent.** The Model Orchestrator is an agent whose job
  is GPU/VRAM/model-load scheduling — this is the differentiated "model optimization"
  story for the rubric, not an afterthought.
- **Strict data contracts.** Every inter-agent handoff is a validated JSON file
  (`brand_dna.json`, `asset_manifest.json`, `critic_result.json`, `kit_manifest.json`).
  See `02-data-contracts.md`.
- **Reproducible runs.** Every run is a self-contained directory with inputs, every
  intermediate JSON, every rendered PNG (incl. failed attempts), and a `run.log`.

## 6. Non-functional requirements

- **Latency:** a full 5-asset kit ≤ ~6 min on the DGX Spark (analysis ~20s, manifest ~15s,
  5 renders × ~40s, 5+ critic checks × ~8s, retries amortized).
- **Privacy:** reference images and briefs never leave the Spark except to Stepfun VLM
  for analysis/critique (documented in `brand_guide`-style data flow). NemoClaw sandbox
  enforces deny-by-default network policy.
- **Resilience:** a single asset failure never aborts the run; partial kits are still
  delivered with a failure report.
- **Observability:** every agent call logged with model, latency, token/step count, and
  VRAM snapshot — feeds the "model optimization depth" evidence in the docs.
