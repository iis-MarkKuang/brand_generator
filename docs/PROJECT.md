# StyleForge — Project Documentation

> Submission document for the DGX Spark Hackathon (NVIDIA × Stepfun). Word count:
> `wc -w docs/PROJECT.md` ≥ 600. Covers the five required topics: project
> characteristics, core highlights, detailed technical implementation, architectural
> design, and optimization plans.

---

## 1. Project Characteristics

**StyleForge** is a multi-agent, locally-deployed AI brand visual-identity studio.
Given a single brand brief ("a warm, craft-first small-batch coffee roaster; hand-drawn
serif, earthy palette") and one reference image, it produces a **complete, on-brand
visual identity kit**: logo, hero banner, social-square, product mockup, business card,
and a human-readable brand guide. It runs end-to-end on a single **NVIDIA DGX Spark**
edge box — no cloud GPU is required for generation, and the only cloud dependency is
Stepfun's multimodal VLM for the perception stages (analysis and critique).

The target users are small businesses, indie creators, and early-stage startups that
cannot afford a design agency (typically $2k–$20k for a brand identity) and lack the
design literacy to produce a *coherent* identity themselves. Existing "AI logo
generators" emit a single image with no cross-asset consistency. StyleForge's defining
characteristic is that it treats brand identity as a **constrained, multi-asset
co-creation pipeline** where every asset is checked against an extracted "brand DNA"
before delivery — the same loop a human art director runs, but automated and local.

Two interaction surfaces are provided: a **chat-driven** co-creation flow inside the
OpenClaw Web UI (a StyleForge skill renders assets inline via the `MEDIA:` protocol),
and a **visual** Brand Kit Gallery (React + Vite) backed by a FastAPI orchestrator that
streams live progress over Server-Sent Events.

## 2. Core Highlights

- **Five collaborating agents with a delegating director.** The Art Director
  (NVIDIA Nemotron) is not a linear step — it holds plan state, calls Brand Analyst,
  Generator, and Critic as tools, and rewrites prompts from critic feedback in an
  iterate-until-quality-bar loop. This is genuine agent-to-agent delegation.
- **A model-orchestrator agent that schedules GPU memory.** On the GB10 Grace-Blackwell
  iGPU (~120 GiB unified memory), a large LLM and FLUX cannot both be fully resident.
  A dedicated agent pre-swaps Ollama ↔ ComfyUI before each render, eliminating OOM
  crashes and idle memory — a real optimization story, not a wrapper.
- **VLM quality gate.** A Stepfun `step-3.7-flash` critic scores each asset against the
  brand DNA (palette match, mood, legibility) with actionable hex-level feedback, and
  only approved assets ship.
- **Local-first reasoning with cloud failover.** Reasoning is served by local Nemotron
  by default; on Ollama unavailability the router transparently fails over to NVIDIA
  NIM cloud (`integrate.api.nvidia.com`), with sticky failover and a logged routing trail.
- **Sandboxed, governed execution.** The agent runs inside a NemoClaw/OpenShell sandbox
  with deny-by-default network egress, so the agent cannot exfiltrate data or hit
  arbitrary endpoints.

## 3. Detailed Technical Implementation

The pipeline is a typed, async Python service (`src/`) with Pydantic data contracts
between every agent handoff (`BrandDna`, `AssetSpec`, `RenderResult`, `CriticResult`,
`KitManifest`). Each agent has a thin client wrapper over its backend:

- **Brand Analyst** (`src/agents/brand_analyst.py`) calls Stepfun `step-3.7-flash` with
  the reference image as a data URL and a strict-JSON system prompt, producing
  `BrandDna` (palette with hex codes + ranks, mood, typography class & pairs, visual
  keywords, dos/don'ts, personality). Extraction is sha1-keyed cached per brief so the
  generation + critic loop never re-pays for analysis. Schema-repair retry handles
  malformed JSON.
- **Art Director** (`src/agents/art_director.py`) uses a local reasoning client
  (Ollama Nemotron, routed through `ReasonRouter` for NIM failover) to decompose the
  DNA into an `AssetManifest` — each `AssetSpec` carries a FLUX prompt (≤600 chars),
  composition, size, and a `uses_pulid` flag. Deterministic seeding keeps renders
  reproducible; `rewrite_prompt` rewrites only the failing asset from critic feedback.
- **Generator** (`src/agents/generator.py`) loads a parameterized ComfyUI workflow
  (`src/comfyui/brand_workflow.json`, FLUX-dev fp8 + PuLID), dynamically prunes PuLID
  nodes when `uses_pulid=false`, and injects a `LoraLoader` node when a LoRA adapter is
  configured (CP-014). It detects CUDA-dirty errors and auto-restarts ComfyUI once via
  `comfyui-ctl.sh` before retrying. Assets are emitted via the `MEDIA:` protocol.
- **Critic** (`src/agents/critic.py`) calls Stepfun VLM per asset, with effort/detail
  routing (`high` first critique, `low` re-checks) to cut VLM cost, and validates the
  `CriticResult` schema with repair.
- **Model Orchestrator** (`src/optimizer/model_orchestrator.py`) is the optimization
  brain: it tracks free unified memory via `/proc/meminfo`, enforces a single-flight
  guard, unloads Ollama (keep-alive 5s) before ComfyUI runs, reloads after, routes VLM
  effort, and records an evidence trail in `orchestrator_log.json` (each event tagged
  with its `backend` — `ollama` or `nim`).
- **Master Orchestrator** (`src/orchestrator/runner.py`) wires the agents end-to-end,
  enforces token-explosion caps (`MAX_TOTAL_VLM_CALLS=25`, `MAX_TOTAL_RENDERS=20`,
  `RUN_TIMEOUT_S=600`), supports cancellation, and produces a `KitManifest` plus a
  generated `brand_guide.md`.
- **FastAPI backend** (`src/orchestrator/api.py`) exposes `POST /api/runs`, SSE event
  streaming, asset serving, `kit.zip` download, and health checks. Single-flight
  execution guards the shared GPU; path-traversal protection, CORS allowlist, and
  upload size caps are enforced.
- **OpenClaw skill** (`skills/styleforge/`) is a secrets-free, Python-stdlib-only helper
  that the NemoClaw-sandboxed agent invokes; it calls the host orchestrator over
  `host.openshell.internal:8000` and publishes assets to the sandbox media boundary.

## 4. Architectural Design

The system follows a **delegating-agent topology**: the Art Director is the central
delegating agent; Brand Analyst, Generator, and Critic are its tools. A separate Model
Orchestrator agent owns the GPU. All perception (vision) is cloud VLM (Stepfun); all
reasoning and generation are local (Nemotron + FLUX on Blackwell). Secrets live only in
the FastAPI orchestrator (`:8000`); the OpenClaw skill and the sandboxed agent hold no
keys. The authoritative detailed design lives in `references/design/` (00-overview …
07-security-and-tokens), and `docs/architecture.md` is the high-level summary.

## 5. Optimization Plans

Seven optimization levers are implemented or planned (detailed in
`references/design/03-model-optimization.md` and `docs/optimization-results.md`):

1. **GPU unified-memory scheduling agent (O1)** — Ollama ↔ ComfyUI pre-swaps (done).
2. **FLUX fp8 on Blackwell Tensor Cores (O2)** — ComfyUI `--fast` mode (done).
3. **VLM reasoning-effort routing (O3)** — high for analysis, low for re-checks (done).
4. **Brand-DNA caching (O4)** — sha1-keyed, avoids re-paying for analysis (done).
5. **Bounded critic loop with per-asset rewrite (O5)** — max retries, early-exit (done).
6. **Local↔cloud reasoning routing (O6)** — local-first with NIM cloud failover (done, CP-013).
7. **NeMo/FLUX LoRA specialization (O7)** — Generator-side LoRA adapter loading is
   implemented and unit-tested (CP-014); a `diffusers`+`peft` training config and script
   are provided (`nemo/`); the full NeMo training run is documented as the scaling
   roadmap (time/GPU-memory-boxed for the hackathon). Also planned: serve Nemotron via a
   **NIM container** for higher local throughput than Ollama.

A captured golden end-to-end run (`tests/golden/golden-001_*`) records verified
behavior: 7 VRAM swaps, 5 VLM calls, local-first routing (3/3 local), and the strict
critic correctly flagging FLUX's known wordmark-text limitation with actionable
hex-level feedback.
