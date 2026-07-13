# StyleForge — Deployment Guide

> How to deploy StyleForge on a single **NVIDIA DGX Spark** using **local computing
> power**, and how the large models are **optimized**. Maps to hackathon submission
> requirement 3 (deployment instructions). A judge should be able to reproduce this
> bring-up from a clean clone + `.env.example`.

## 0. Hardware & OS

- **DGX Spark**, GB10 Grace-Blackwell **integrated GPU**, ARM64 (aarch64), Ubuntu 24.04.
- ~120 GiB **unified memory** shared between CPU and GPU
  (`nvidia-smi` reports memory as `[N/A]` for the iGPU — this is expected; it is unified,
  not discrete VRAM. Ollama reports `total 119.7 GiB / available 111.9 GiB`).
- ~1.5 TB disk. CUDA functional (`nvcc` / `nvidia-smi` driver present).

## 1. Prerequisites (one-time, host)

```bash
# Python 3.12 + uv
sudo apt-get update && sudo apt-get install -y python3.12 python3-pip
pip install uv

# Node 22 (for the frontend gallery + the NemoClaw CLI build)
# (use nvm or your distro's nodejs-22 package)

# Docker (for the NemoClaw sandbox) with CDI GPU support
sudo usermod -aG docker "$USER"      # then re-login
sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml
# /etc/docker/daemon.json must set: { "cgroupns": "host", "registry-mirrors": [...] }
sudo systemctl restart docker
```

## 2. Get the code & install deps

```bash
git clone <your-fork-url> styleforge && cd styleforge
cp .env.example .env
#   fill in: STEPFUN_API_KEY, NVIDIA_NIM_API_KEY, TELEGRAM_BOT_TOKEN (optional)
#   confirm local hosts/ports (Ollama :11434, ComfyUI :8200, OpenClaw :9000)

# Python deps (use the Tsinghua mirror if PyPI is unreachable)
export UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple/
uv sync

# Frontend deps
cd frontend && npm install && cd ..
```

## 3. Start the local model services

The workshop bundle ships a GB10-CUDA-enabled Ollama and a ComfyUI with FLUX-dev-fp8 +
PuLID + InsightFace. Start them with the bundled control scripts:

```bash
# Ollama (local LLM host on :11434)
bash /path/to/build_a_claw_workshop-bundle/ollama-ctl.sh start
ollama pull nemotron-3-nano:30b      # dev reasoning model (~24 GB)
# (demo: pull nemotron-3-super:120b, ~86 GB on disk)

# ComfyUI (FLUX-dev fp8 + PuLID on :8200, Blackwell --fast mode)
bash /path/to/build_a_claw_workshop-bundle/comfyui-ctl.sh start
```

> **Why both?** Reasoning (Nemotron via Ollama) and generation (FLUX via ComfyUI) share
> the GB10's unified memory and **swap** — see Optimization §1 below. They are never
> both fully resident at once; the Model Orchestrator agent manages the handoff.

## 4. Start StyleForge

```bash
set -a; source .env; set +a

# FastAPI orchestrator backend (:8000) — holds the secrets, runs the agent pipeline
uv run uvicorn src.orchestrator.api:app --host 0.0.0.0 --port 8000 &

# Brand Kit Gallery frontend (:5173, proxies /api → :8000)
cd frontend && npm run dev &

# OpenClaw gateway (:9000) — chat-driven co-creation UI
# (started by the workshop bundle's openclaw-ctl.sh)
```

Health check: `curl http://127.0.0.1:8000/api/health` → `{"status":"ok", ...}`.

## 5. (Optional) NemoClaw sandboxed agent + Telegram always-on

```bash
# Build/install the NemoClaw CLI from source (TypeScript) if not already present
# (see nemoclaw-offline/README.md for the offline mirror build)

# Onboard a governed sandbox that uses the local Ollama as its inference provider
NEMOCLAW_PROVIDER=ollama nemoclaw onboard --no-gpu
nemoclaw styleforge skill install ./skills/styleforge
nemoclaw styleforge rebuild --yes

# Telegram always-on bot (token in .env). NOTE: api.telegram.org is regionally
# blocked from some networks; the bot is configured but may require a transparent
# proxy (e.g. mihomo TUN) to come online. See docs/dev-journal.md CP-012.
TELEGRAM_BOT_TOKEN=... nemoclaw styleforge channels add telegram
```

## 6. Run the demo

```bash
# CLI golden run (records tests/golden/golden-001_*)
uv run python tools/run_pipeline.py --brief "..." --ref sample.jpg --assets logo,social_square

# Or via the gallery UI: open http://<spark-ip>:5173 → "New Kit" → upload + start
# Or via OpenClaw chat: http://<spark-ip>:9000 → "design a brand kit for ..."
```

## 7. Model Optimization (local-compute emphasis)

The DGX Spark's GB10 unified memory is the central constraint. Seven levers:

1. **GPU unified-memory scheduling agent.** `src/optimizer/model_orchestrator.py`
   unloads Ollama (`OLLAMA_KEEP_ALIVE=5s`, so an idle LLM releases memory within 5s)
   *before* ComfyUI's `KSampler`, then reloads Nemotron after. Free memory is read from
   `/proc/meminfo`. Eliminates OOM crashes and idle memory. (Implemented.)
2. **FLUX fp8 on Blackwell Tensor Cores.** ComfyUI `--fast` mode uses FP8 Tensor Cores
   (in the workshop bundle); step-count / CFG are tunable. (Implemented.)
3. **VLM reasoning-effort routing.** `step-3.7-flash` `high` for analysis, `low` for
   critic re-checks — cuts VLM latency and cost on easy passes. (Implemented.)
4. **Brand-DNA caching.** sha1-keyed per brief; the N-asset generation + critic loop
   never re-pays for analysis. (Implemented.)
5. **Bounded critic loop with per-asset rewrite.** `MAX_RETRIES_PER_ASSET=1`, early-exit
   on hard fail; only the failing asset's prompt is rewritten, never a full re-plan.
   (Implemented.)
6. **Local↔cloud reasoning routing.** Local Nemotron by default; on Ollama unavailable,
   the `ReasonRouter` (`src/common/router.py`) fails over to NVIDIA NIM cloud
   (`integrate.api.nvidia.com`, `nvidia/llama-3.3-nemotron-super-49b-v1.5`) with sticky
   failover and a logged routing trail. `ROUTING_STRATEGY=local-first` preserves the
   local-compute emphasis. (Implemented, CP-013.)
7. **NeMo / FLUX LoRA specialization.** Generator-side LoRA adapter loading is
   implemented and unit-tested (`LORA_ADAPTER` + `LORA_STRENGTH` inject a ComfyUI
   `LoraLoader` node). A `diffusers`+`peft` training config and script ship in `nemo/`.
   The full NeMo training run is the scaling roadmap (time/GPU-memory-boxed for the
   hackathon). Also planned: serve Nemotron via a **NIM container** for higher local
   throughput than Ollama. (CP-014.)

See `docs/optimization-results.md` for the before/after measurement methodology and the
captured golden run's optimization stats (7 VRAM swaps, 5 VLM calls, 3/3 local routing).

## 8. Verify

```bash
make acceptance    # ruff + mypy + 84 tests + golden + secrets scan (6/6 PASS)
make coverage      # ≥80% on src/ (currently 87%)
make check-secrets # no tracked secrets
```
