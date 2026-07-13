# StyleForge — Architecture & Technical Design

> **Tagline:** A multi-agent, locally-deployed AI studio that turns one brand brief +
> one reference image into a complete, on-brand visual identity kit — analyzed by a
> Stepfun VLM, reasoned by a local NVIDIA Nemotron director, rendered by ComfyUI FLUX,
> and quality-gated by a VLM critic loop.
>
> **Source of truth:** this file is the high-level summary. The authoritative detailed
> design lives in `references/design/` (00-overview … 07-security-and-tokens). If this
> file and `references/design/` disagree, **`references/design/` wins**; update this file
> to match. The change-packet roadmap is `specs/ROADMAP.md`.

---

## 1. The Pain Point & Industry Value

Small businesses, indie creators, and early-stage startups cannot afford a design
agency (often $2k–$20k for a brand identity) and lack the design literacy to produce
a coherent visual identity themselves. Existing AI "logo generators" produce a single
image with **no brand consistency** across assets (logo, banner, social, mockup all
look unrelated).

**StyleForge** solves this by treating brand identity as a **constrained, multi-asset
co-creation pipeline** where every asset is checked against an extracted "brand DNA"
before delivery — the same loop a human art director runs, but automated and local.

Industry landing: marketing/creative services, e-commerce storefronts, content
creator tooling, SMB branding. Clear monetization path (SaaS / one-shot packs).

---

## 2. System Architecture

```
                          ┌─────────────────────────────────────────────┐
   User (chat / web UI) ─►│  OpenClaw Gateway :3030  (NemoClaw sandbox) │
                          │  Master Orchestrator Skill: "styleforge"     │
                          └───────────────────┬─────────────────────────┘
                                              │ brand brief + reference image
                          ┌───────────────────▼─────────────────────────┐
                          │  1. BRAND ANALYST  (Stepfun step-3.7-flash)  │  cloud VLM
                          │     → brand_dna.json                         │
                          │       {palette[hex], mood, typography,       │
                          │        visual_keywords, dos, donts}          │
                          └───────────────────┬─────────────────────────┘
                                              │ brand_dna
                          ┌───────────────────▼─────────────────────────┐
                          │  2. ART DIRECTOR  (NVIDIA Nemotron-3-Super)  │  local LLM
                          │     → asset_manifest.json                   │
                          │       [{asset, flux_prompt, composition,     │
                          │         size, uses_pulid}]                   │
                          └───────────────────┬─────────────────────────┘
                                              │ manifest
            ┌─────────────────────────────────┼──────────────────────────┐
            │                                 │                          │
   ┌────────▼─────────┐   ┌──────────────────▼─────────────┐   ┌────────▼────────┐
   │ 3a. MODEL         │   │ 3. GENERATOR  (ComfyUI FLUX    │   │ 3b. GPU SWAP    │
   │  ORCHESTRATOR     │   │  + PuLID, Blackwell FP8 fast)  │   │  (unload Ollama │
   │  (local scheduler)│   │  → PNG assets via MEDIA:       │   │  → ComfyUI,     │
   │  schedules loads  │   │                               │   │  reload after)  │
   └────────┬─────────┘   └──────────────────┬─────────────┘   └─────────────────┘
            │                                 │
            │            ┌────────────────────▼────────────────┐
            │            │ 4. CRITIC  (Stepfun step-3.7-flash)  │  cloud VLM
            │            │    per-asset: pass/fail + feedback   │
            │            │    vs brand_dna (palette, mood,      │
            │            │    legibility, on-brand)             │
            │            └────────────────────┬────────────────┘
            │                                 │ fail? refined prompt
            │                                 ▼  (loop, max N)
            │            ┌──────────────────────────────────────┐
            └────────────►│  loop back to 3 until critic passes  │
                         └──────────────────┬───────────────────┘
                                            │ all pass
                         ┌──────────────────▼───────────────────┐
                         │ 5. ASSEMBLER → brand_kit/             │
                         │    logo, banner, social, mockup,      │
                         │    business_card + brand_guide.md     │
                         └──────────────────┬───────────────────┘
                                            ▼
                         Brand Kit Gallery (React front-end :5173)
                         + OpenClaw Web UI inline MEDIA: preview
```

---

## 3. Agent Roles (multi-agent collaboration — scoring criterion 2)

| # | Agent | Model | Location | Responsibility |
|---|-------|-------|----------|----------------|
| 1 | **Brand Analyst** | Stepfun `step-3.7-flash` (VLM) | cloud | Reads reference image + text brief, extracts structured `brand_dna.json` (color palette in hex, mood board words, typography class, visual keywords, explicit dos/don'ts). Uses VLM's native image understanding — no separate vision model. |
| 2 | **Art Director** | NVIDIA Nemotron-3-Super 120B | local (Ollama) | Holds plan state. Decomposes `brand_dna` into an `asset_manifest`: list of assets, each with a detailed FLUX prompt + composition spec + size + whether PuLID identity (mascot/face) is needed. Decides retry strategy from critic feedback. |
| 3 | **Generator** | ComfyUI FLUX.1-dev + PuLID | local (Blackwell FP8) | Executes the ComfyUI workflow per asset. Mascot/face assets use PuLID for identity consistency across the kit. Emits `MEDIA:<path>` lines. |
| 3a | **Model Orchestrator** | lightweight local scheduler | local | The optimization brain: unloads Ollama models to free GPU VRAM before ComfyUI runs, reloads Nemotron after generation completes. Picks reasoning-effort (`low/medium/high`) per task. Caches `brand_dna` to avoid re-calling the VLM. |
| 4 | **Critic / QA** | Stepfun `step-3.7-flash` (VLM) | cloud | Per-asset visual review against `brand_dna`: palette match, mood conformance, logo legibility, on-brand score. Returns `{pass: bool, score, feedback}`. Fail → refined prompt back to Generator (bounded loop). |
| 5 | **Assembler** | local helper | local | Collects approved assets into `brand_kit/`, writes a human-readable `brand_guide.md` (palette, fonts, usage rules) and a manifest for the gallery front-end. |

**Collaboration topology:** the Art Director (Nemotron) is the *delegating* agent — it
calls Analyst, Generator, and Critic as tools in an iterate-until-quality-bar loop.
This is genuine agent-to-agent delegation, not a linear script.

---

## 4. Model Optimization Story (scoring criterion 2 — 25%)

This is what differentiates us from a "wrapper":

1. **GPU VRAM scheduling agent.** The DGX Spark's GB10 is a Grace-Blackwell **integrated
   GPU with ~120 GiB of unified memory** shared between CPU and GPU (not discrete VRAM —
   `nvidia-smi` reports memory as `[N/A]`; Ollama reports `total 119.7 GiB / available
   111.9 GiB`). A large LLM (Nemotron) and FLUX cannot both be fully resident in that pool
   at once. The Model Orchestrator agent **predicts** which stage runs next and pre-swaps:
   `ollama stop` (the bundle runs with `OLLAMA_KEEP_ALIVE=5s`, so an idle LLM releases
   memory back to the pool within 5 s) before ComfyUI `KSampler`, then reloads Nemotron
   after. Eliminates OOM crashes and idle memory.
2. **FLUX fp8 on Blackwell Tensor Cores.** ComfyUI `--fast` mode uses Blackwell FP8
   Tensor Cores (already in the workshop bundle) — we expose and document the
   step-count / CFG trade-off as a tunable the Critic can influence.
3. **Reasoning-effort routing.** `step-3.7-flash` exposes `low/medium/high` effort; the
   Orchestrator routes *analysis* → `high`, *critic pass-checks* → `low`, cutting VLM
   latency and cost on the easy re-checks.
4. **Brand-DNA caching.** The VLM extraction (stage 1) is cached per brief so the
   N-asset generation + critic loop never re-pays for analysis.
5. **Bounded critic loop with early-exit.** Max retries per asset (default 2); on a
   hard-fail the Art Director rewrites the prompt instead of blindly retrying. Per-asset
   rewrite only — never re-plan the whole manifest in the loop.
6. **Local↔cloud model routing (O6).** Default reasoning = local Nemotron; on Ollama
   unavailable/overloaded, the Model Orchestrator routes the Art Director's call to
   NVIDIA NIM cloud (`integrate.api.nvidia.com`). `local-first` default preserves the
   "local compute" emphasis; routing decisions logged.
7. **(Optimization plan, documented) NeMo LoRA specialization (O7).** LoRA-fine-tune
   FLUX on a brand-style dataset via NVIDIA NeMo for repeat clients; ship a minimal
   proof + before/after palette-match delta, and document the full plan. Also: serve
   Nemotron via a **NIM container** for higher local throughput than Ollama.

> Full detail + the evidence trail each item emits: `references/design/03-model-optimization.md`.

---

## 5. Tech Stack (scoring criterion 4 — platform compatibility)

**NVIDIA SDKs / models (mandatory):**
- **NemoClaw / OpenShell** — sandboxed, governed agent runtime + routed inference.
- **NVIDIA Nemotron-3-Super 120B** — local reasoning (Art Director) via Ollama.
- **ComfyUI + FLUX.1-dev fp8** — NVIDIA Blackwell-optimized image generation.
- **NeMo** — (optimization plan) LoRA specialization of FLUX.
- **NIM containers** — (optimization plan) higher-throughput local Nemotron serving.

**Stepfun (阶跃星辰) models (mandatory):**
- **`step-3.7-flash`** — flagship multimodal VLM, native image understanding, tool
  calling. Powers **Brand Analyst** and **Critic** agents.
- **`step-2-mini`** — (optional) light text tasks / fallback.

**Agent platform:** OpenClaw (skills = YAML front-matter + markdown body + bash/python
helper, `MEDIA:` inline-image protocol).

**Front-end:** React + Vite "Brand Kit Gallery" (`:5173`) backed by a FastAPI orchestrator
service (`:8000`) that wraps the agent calls; OpenClaw Web UI (`:3030`) for chat-driven
co-creation. Both run on the DGX Spark, accessed over LAN.

---

## 6. Repository Layout

```
game/
├── AGENTS.md                   # coding-agent operating manual
├── .cursor/rules/*.mdc         # persistent rules (architecture, workflow, secrets, security, style)
├── .env / .env.example         # secrets (gitignored) + public template
├── .gitignore
├── README.md
├── docs/
│   ├── hackathon-requirements.md
│   ├── architecture.md         # this file (high-level summary)
│   └── dev-journal.md          # "Ten-Day Talk" essay
├── references/
│   ├── design/                 # authoritative detailed design (00–07)
│   └── workshop-Copy1.ipynb     # DGX Spark workshop reference
├── specs/                      # change packets + ROADMAP.md + _template.md
├── tools/                      # new-change-packet.sh, validate-env.sh, check-secrets.sh
├── src/
│   ├── common/                 # config, schemas, client wrappers, logging, runs
│   ├── agents/                 # brand_analyst, art_director, generator, critic, assembler
│   ├── optimizer/              # model_orchestrator (GPU swap scheduler)
│   ├── comfyui/                # brand_workflow.json
│   └── orchestrator/           # runner, cli, api (FastAPI)
├── skills/styleforge/          # OpenClaw SKILL.md + run_helper.sh
├── frontend/                   # React + Vite Brand Kit Gallery
└── tests/                      # unit + acceptance + golden
```

---

## 9. Security & Token Budget

**Single secrets boundary:** only the FastAPI orchestrator (`:8000`) loads `.env` and
holds API keys. The OpenClaw skill and the NemoClaw-sandboxed agent call the orchestrator
over `localhost:8000` — they hold no secrets. (Consequence: CP-009 depends on CP-010;
ROADMAP updated.)

**Security mitigations (selected):**
- Path-traversal protection on all `/api/runs/{id}/**` routes (regex `run_id`, basename
  `name`, confined path resolution). **Never serve files outside `runs/<id>/`.**
- CORS restricted to `CORS_ALLOWED_ORIGINS` (never `*`); upload size capped
  (`MAX_UPLOAD_MB`, default 10) with Pillow MIME validation.
- Telegram bot honors `TELEGRAM_ALLOWED_CHAT_IDS` allowlist to prevent unauthorized GPU
  drain; NemoClaw sandbox has deny-by-default network egress (verified by a negative test).
- No secrets in logs; SSE tailer allowlists event fields; `tools/check-secrets.sh` before
  every commit and in CI.

**Token-explosion caps (enforced in CP-008):** `MAX_TOTAL_VLM_CALLS` (25),
`MAX_TOTAL_RENDERS` (20), `RUN_TIMEOUT_S` (600). VLM `image_url.detail` tiers — `high`
for first critique, `low` for re-checks; source images pre-resized to ≤1024px before
encoding. The Art Director's tool-calling context is **text-only** (no images) and
appends only the failing asset's feedback — per-asset `rewrite_prompt`, never a full
re-plan. `AssetSpec.flux_prompt` ≤ 600 chars.

> Full detail: `references/design/07-security-and-tokens.md`. Rule: `.cursor/rules/security.mdc`.

---

## 7. End-to-end Demo Flow (for the video — scoring criterion 5)

1. User opens the Brand Kit Gallery, types a brief ("cozy specialty coffee roaster,
   warm and craft, target: young urban professionals") and drops a mood reference image.
2. **Brand Analyst** streams the extracted brand DNA (palette swatches, mood words).
3. **Art Director** shows the asset manifest it planned (logo / banner / social / cup
   mockup / business card).
4. **Generator** renders each asset; the GPU-swap log shows Ollama→ComfyUI handoff.
5. **Critic** rejects one asset (palette off) → Director rewrites prompt → re-render →
   pass. The loop is visible.
6. Final **Brand Kit** board assembles with all approved assets + an auto-generated
   `brand_guide.md`. Downloadable.

---

## 8. Mapping to the Judging Rubric

| Criterion | Weight | How StyleForge scores |
|-----------|--------|-----------------------|
| Practicality / industry value / innovation | 25% | Real SMB branding pain point; novel "VLM-analyze → local-reason → local-generate → VLM-critic loop" + agent-driven GPU scheduling (not a wrapper). |
| Agent integration & model-optimization depth | 25% | 5 collaborating agents + delegating Art Director loop; 7-point optimization story (O1 VRAM scheduling, O2 FP8, O3 effort routing, O4 caching, O5 bounded loop, O6 NIM routing, O7 NeMo LoRA). |
| Project completeness | 20% | OpenClaw chat UI + custom React gallery + FastAPI backend + full docs + smooth demo. |
| Platform compatibility | 15% | NemoClaw + Nemotron (local) + ComfyUI/FLUX (Blackwell) + NeMo/NIM (plan) **and** Stepfun `step-3.7-flash` VLM. |
| Demo effect | 10% | Highly visual: live brand-kit board assembly + visible critic loop. |
| Event essay | 5% | "Ten-Day Talk" dev journal in `docs/dev-journal.md`. |
