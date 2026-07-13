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

> Full bring-up: [`docs/deployment.md`](docs/deployment.md). Summary below.

```bash
# 1. Configure secrets (never commit the real .env)
cp .env.example .env
#   fill in STEPFUN_API_KEY, NVIDIA_NIM_API_KEY, TELEGRAM_BOT_TOKEN (optional)
#   confirm local hosts/ports (Ollama :11434, ComfyUI :8200, OpenClaw :9000)

# 2. Install deps (use the Tsinghua mirror if PyPI is unreachable)
export UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple/
uv sync
cd frontend && npm install && cd ..

# 3. Start local model services (GB10-CUDA Ollama + ComfyUI FLUX-dev fp8)
bash /path/to/build_a_claw_workshop-bundle/ollama-ctl.sh start
ollama pull nemotron-3-nano:30b            # dev reasoning (~24 GB)
bash /path/to/build_a_claw_workshop-bundle/comfyui-ctl.sh start

# 4. Start StyleForge
set -a; source .env; set +a
uv run uvicorn src.orchestrator.api:app --host 0.0.0.0 --port 8000 &
cd frontend && npm run dev &               # Brand Kit Gallery :5173

# 5. Run a kit (CLI) or via the gallery UI at http://<spark-ip>:5173
uv run python tools/run_pipeline.py --brief "..." --ref sample.jpg --assets logo,social_square
```

Verify: `make acceptance` → 6/6 PASS · `make coverage` → 87% on `src/`.

> ⚠️ **Never commit `.env`.** `.env` is gitignored; `.env.example` is the public template.
> `make check-secrets` runs before every commit and in CI.

## Tech stack

See [`docs/tech-stack.md`](docs/tech-stack.md) for the full per-component breakdown.

- **NVIDIA:** DGX Spark (GB10 Grace-Blackwell iGPU, ~120 GiB unified memory),
  NemoClaw/OpenShell (sandboxed agents), Nemotron-3-Nano 30B / Super 120B (local
  reasoning via Ollama), ComfyUI FLUX.1-dev fp8 (Blackwell-optimized generation),
  NVIDIA NIM cloud (reasoning failover), NeMo + NIM containers (LoRA specialization plan).
- **Stepfun (阶跃星辰):** `step-3.7-flash` (multimodal VLM — Brand Analyst & Critic),
  `step-2-mini` (optional light text fallback).
- **Agent platform:** OpenClaw (skills, `MEDIA:` inline-image protocol).
- **App:** FastAPI orchestrator (`:8000`, single secrets boundary) + React/Vite/Tailwind
  Brand Kit Gallery (`:5173`) + Pydantic typed data contracts.

## Status & roadmap

✅ **All 16 change packets complete.** 84 tests (77 unit + 7 golden), 87% coverage,
ruff + mypy clean, CI green. See [`specs/ROADMAP.md`](specs/ROADMAP.md).

| Done | Packet |
|------|--------|
| ✅ | CP-001–CP-008: clients, 4 agents, model orchestrator, orchestrator loop |
| ✅ | CP-009: OpenClaw skill (secrets-free, `MEDIA:` protocol) |
| ✅ | CP-010: FastAPI backend (SSE, single-flight, path-traversal guard) |
| ✅ | CP-011: React Brand Kit Gallery |
| ✅ | CP-012: NemoClaw sandbox (E2E verified) — Telegram LIVE via TUN mode |
| ✅ | CP-013: local↔NIM-cloud reasoning routing (local-first, sticky failover) |
| ✅ | CP-014: FLUX LoRA specialization (Generator loading + training plan) |
| ✅ | CP-015: tests + golden run + acceptance harness + CI |
| ✅ | CP-016: this documentation |

## Docs

- [`docs/PROJECT.md`](docs/PROJECT.md) — submission doc (≥600 words, the 5 required topics)
- [`docs/architecture.md`](docs/architecture.md) — high-level design + rubric mapping
- [`docs/deployment.md`](docs/deployment.md) — local bring-up + model optimization
- [`docs/tech-stack.md`](docs/tech-stack.md) — NVIDIA SDKs + Stepfun models, per role
- [`docs/demo-script.md`](docs/demo-script.md) — shot-by-shot demo video script
- [`docs/optimization-results.md`](docs/optimization-results.md) — the 7-point optimization story
- [`docs/dev-journal.md`](docs/dev-journal.md) — the "Ten-Day Talk" journey
- [`docs/hackathon-requirements.md`](docs/hackathon-requirements.md) — requirements & rubric
- [`references/design/`](references/design/) — authoritative detailed design (00–07)
- [`specs/ROADMAP.md`](specs/ROADMAP.md) — change-packet index

## License

Apache 2.0 — see [`LICENSE`](LICENSE).
