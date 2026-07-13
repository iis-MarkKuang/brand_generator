#!/usr/bin/env python3
"""CP-007 live smoke — a real Ollama↔ComfyUI unified-memory swap cycle on the Spark.

    PYTHONPATH=. uv run python tools/smoke_model_orchestrator.py

Loads nemotron-3-nano:30b (occupies unified memory), then request_vram("comfyui")
unloads it and confirms ComfyUI health, recording VRAM before/after to
runs/<id>/orchestrator_log.json.
"""

from __future__ import annotations

import asyncio
import sys

from src.common.config import get_settings
from src.common.ollama import OllamaClient
from src.common.runs import RunDir, new_run_id
from src.optimizer.model_orchestrator import ModelOrchestrator


async def main() -> int:
    s = get_settings()
    run = RunDir("runs", new_run_id()).ensure()
    # Warm Ollama so the model occupies unified memory, then hand the same client to
    # the orchestrator so `before` is measured while the model is still resident
    # (before OLLAMA_KEEP_ALIVE frees it).
    warm = OllamaClient(s)
    try:
        print(f"warming {s.ollama_reasoning_model} ...")
        await warm.chat(
            s.ollama_reasoning_model, [{"role": "user", "content": "Say OK."}], think=False
        )
        from src.common.vram import free_vram_gb
        print(f"free unified mem right after warm (model resident): {free_vram_gb()} GB")
        orch = ModelOrchestrator(run, settings=s, ollama=warm)
        try:
            res = await orch.request_vram("comfyui", reason="pre-generate")
            print(f"swap target={res.target} ok={res.ok} unloaded={res.unloaded}")
            print(
                f"vram_before_gb={res.vram_before_gb} vram_after_gb={res.vram_after_gb} "
                f"latency_s={res.latency_s}"
            )
            if res.vram_before_gb is not None and res.vram_after_gb is not None:
                print(f"freed delta: {round(res.vram_after_gb - res.vram_before_gb, 2)} GB")
            print(f"state={orch.state.value} events={len(orch.events)}")
            print(f"written: {run.orchestrator_log_path()}")
            return 0 if res.ok else 1
        finally:
            await orch.aclose()
    finally:
        await warm.aclose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
