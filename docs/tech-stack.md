# StyleForge — Tech Stack

> Explicit list of the **NVIDIA SDKs / models** and **Stepfun (阶跃星辰) models** used,
> with the role each plays. Maps to hackathon submission requirement 4 (tech-stack
> description) and judging criterion 4 (platform compatibility, 15%).

## NVIDIA SDKs & models

| Component | What it is | Where used | Role |
|-----------|-----------|------------|------|
| **DGX Spark / GB10 Grace-Blackwell iGPU** | Edge AI box, ~120 GiB unified memory, ARM64, Blackwell Tensor Cores | hardware | The entire pipeline runs locally here; reasoning + generation share unified memory. |
| **Nemotron-3-Nano 30B** (dev) / **Nemotron-3-Super 120B** (demo) | NVIDIA open large language models | local via Ollama | **Art Director** agent — the delegating planner that decomposes brand DNA into an asset manifest and rewrites prompts from critic feedback. |
| **ComfyUI + FLUX.1-dev (fp8) + PuLID + InsightFace** | NVIDIA Blackwell-FP8-optimized diffusion pipeline with face/identity preservation | local | **Generator** agent — renders each brand asset (logo, banner, social, mockup, card). `--fast` mode uses Blackwell FP8 Tensor Cores. PuLID keeps mascot/face identity consistent across the kit. |
| **NemoClaw / OpenShell** | NVIDIA sandboxed, governed agent runtime + routed inference + egress L7 policy | local | Runs the StyleForge agent in a **deny-by-default network sandbox**; the agent reaches the host orchestrator only via `host.openshell.internal:8000` (allowlisted by the `local-inference` preset). Governance + SSRF guard. |
| **NVIDIA NIM (cloud)** | `integrate.api.nvidia.com`, model `nvidia/llama-3.3-nemotron-super-49b-v1.5` | cloud (failover) | `ReasonRouter` failover target for the Art Director when local Ollama is unavailable/overloaded. `local-first` default; sticky failover; routing logged. (CP-013) |
| **NeMo** | NVIDIA specialization / fine-tuning toolkit | local (plan) | FLUX LoRA specialization roadmap: `nemo/lora_config.yaml` + `nemo/flux_lora_train.py` (diffusers+peft+accelerate). Generator-side adapter loading is implemented (CP-014); full training is the scaling plan. |
| **NIM containers** | Higher-throughput local model serving | local (plan) | Planned: serve Nemotron via a NIM container for higher local throughput than Ollama. |
| **NVIDIA CDI** | Container Device Interface for GPU passthrough | local | Docker CDI spec (`nvidia-ctk cdi generate`) enables GPU access inside the NemoClaw sandbox. |

## Stepfun (阶跃星辰) models

| Model | What it is | Where used | Role |
|-------|-----------|------------|------|
| **`step-3.7-flash`** | Flagship multimodal VLM (198B/11B MoE), native image + video understanding, tool calling, OpenAI-compatible API | cloud (`api.stepfun.com/v1`) | Powers the two **perception** agents: (1) **Brand Analyst** — reads the reference image + brief and extracts structured `brand_dna.json` (palette in hex, mood, typography, keywords, dos/don'ts); (2) **Critic** — per-asset visual review against the brand DNA (palette match, mood, legibility, on-brand score) with actionable hex-level feedback. Effort routing (`high` first critique, `low` re-checks) cuts VLM cost. |
| **`step-2-mini`** | Light text model (optional) | cloud (optional) | Fallback for light text tasks. (Optional; not on the critical path.) |

## Agent platform & application stack

| Component | Role |
|-----------|------|
| **OpenClaw** (gateway `:9000`) | Agent platform — the StyleForge skill (`skills/styleforge/`: `SKILL.md` + `run_helper.sh` + `styleforge_helper.py`) renders assets inline in the chat UI via the `MEDIA:` protocol. Skills are YAML front-matter + markdown body + a bash/python helper; the helper is **secrets-free, Python-stdlib-only**. |
| **FastAPI** (`:8000`) | Orchestrator backend — the **single secrets boundary** (only process that loads `.env`). Exposes `POST /api/runs`, SSE event streaming, asset serving, `kit.zip`. Wraps the agent pipeline; single-flight to guard the shared GPU. |
| **React + Vite + TypeScript + Tailwind** (`:5173`) | Brand Kit Gallery — visual surface: New Kit form, live run view (asset lanes + VRAM-swap event log + DNA card), final kit board, run history. TanStack Query + SSE. |
| **Pydantic / Pydantic-Settings** | Typed data contracts (`BrandDna`, `AssetSpec`, `RenderResult`, `CriticResult`, `KitManifest`) between every agent handoff + typed config. |
| **Python (async) + httpx** | All agent client wrappers (Stepfun, Ollama, ComfyUI, NIM) are async with shared retry logic. |

## Local vs. cloud split

- **Local (on the DGX Spark):** all reasoning (Nemotron via Ollama) and all generation
  (FLUX via ComfyUI). The Model Orchestrator agent swaps them in/out of unified memory.
- **Cloud (only perception):** Stepfun `step-3.7-flash` for the two vision stages
  (analysis + critique). Optionally NVIDIA NIM cloud as a reasoning failover (off by
  default — `local-first`).

This split is deliberate: it keeps the heavy, repeatable, GPU-bound work local
(satisfying the "local computing power" requirement) while using the cloud VLM only
for the perception tasks that benefit from a 198B-scale multimodal model.
