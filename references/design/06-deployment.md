# 06 — Deployment on DGX Spark

> How StyleForge is deployed with local compute, and how the models are optimized —
> this maps directly to the hackathon's "Deployment Instructions" requirement.

## Target hardware

- **DGX Spark**, GB10 Grace-Blackwell **iGPU**, ARM64 (aarch64), Ubuntu 24.04 LTS,
  **~120 GiB unified memory** (shared CPU+GPU pool; `nvidia-smi` reports `[N/A]`),
  ~1.5 TB disk.
- Pre-existing workshop bundle at `/home/nvidia/build_a_claw_workshop/` provides:
  Ollama + models, ComfyUI + FLUX/PuLID/InsightFace, OpenClaw, Node 22, a Python venv.

## Process topology (all on the Spark, LAN-accessible)

| Process | Port | Start command (summary) |
|---|---|---|
| Ollama (Nemotron) | 11434 | `ollama serve` (already up in workshop) |
| ComfyUI | 8200 | `scripts/comfyui-ctl.sh start` (`--fast` FP8) |
| OpenClaw Gateway | 3030 | `openclaw` with `OPENCLAW_HOME` set |
| FastAPI orchestrator | 8000 | `uvicorn src.orchestrator.api:app --host 0.0.0.0 --port 8000` |
| Brand Kit Gallery | 5173 | `npm run dev` (Vite) in `frontend/` |
| NemoClaw sandbox | — | `nemoclaw` CLI wraps the OpenClaw agent |
| Telegram bridge | — | NemoClaw Telegram channel wiring |

Access from a laptop on the same LAN: `http://<spark-ip>:5173` (gallery),
`http://<spark-ip>:3030` (OpenClaw chat), `http://<spark-ip>:8000` (API).

## Local model optimization (deployment-time)

1. **Nemotron (Art Director)** served via Ollama using the bundle's binary + GB10 CUDA
   libs (cuda_v13), quantized GGUF. **Dev:** `nemotron-3-nano:30b` (pulled from the
   Ollama registry). **Demo:** `nemotron-3-super:120b` (≈86 GB on disk). The bundle
   serves Ollama with `OLLAMA_KEEP_ALIVE=5s` so an idle model frees unified memory fast.
   - `OLLAMA_REASONING_MODEL=nemotron-3-nano:30b` (dev) / `nemotron-3-super:120b` (demo).
   - `think:false` to keep `message.content` populated (workshop-documented reasoning-model
     quirk).
2. **FLUX.1-dev fp8** in ComfyUI with `--fast` (Blackwell FP8 Tensor Core path).
3. **VRAM scheduling** (see `03-model-optimization.md` O1): Ollama↔ComfyUI swap managed
   by the Model Orchestrator agent so the two never OOM each other.
4. **Optional NIM container** (optimization plan, CP-013/014): serve Nemotron via a local
   NIM container for higher throughput than Ollama; cloud NIM as failover.

## Secrets & config

- All secrets in `.env` (gitignored); loaded via `pydantic-settings` in
  `src/common/config.py`.
- `.env.example` is the public template committed to the repo.
- `HF_HUB_OFFLINE=1` by default (workshop pre-populated `hf-cache/`); flip to `0` only
  for the NeMo LoRA leg (CP-014).

## NemoClaw sandboxing (security/governance)

- The OpenClaw agent runs inside a **NemoClaw OpenShell sandbox**: deny-by-default
  network policy, isolated filesystem, routed inference.
- Network allowlist: `127.0.0.1` (Ollama, ComfyUI, OpenClaw), `api.stepfun.com`,
  `integrate.api.nvidia.com` (only when cloud routing is enabled).
- This is documented and demoed as part of "NVIDIA SDK utilization" (criterion 4).

## One-command bring-up (target)

```bash
# from the repo root on the DGX Spark
cp .env.example .env && $EDITOR .env          # fill keys
set -a; source .env; set +a
make deps        # python deps + frontend npm install
make up          # ensures ollama + comfyui + openclaw + api + gallery
make run-demo    # starts a sample run end-to-end
```

> The `Makefile` is created in CP-001. `make up` is idempotent and health-checks each
> service before declaring ready.

## Teardown / cleanup

- Runs are isolated under `runs/<run_id>/`; delete a run dir to clean it.
- `make down` stops the FastAPI + gallery + OpenClaw processes (leaves Ollama/ComfyUI
  workshop services untouched).
- No writes outside the repo dir + `OPENCLAW_HOME` skills dir (mirrors the workshop's
  "delete dir = uninstall" hygiene).
