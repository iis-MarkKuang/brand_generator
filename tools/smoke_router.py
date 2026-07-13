"""Live smoke for the CP-013 reasoning router (manual, run on the Spark).

Proves the local->NIM failover path with the REAL NVIDIA NIM endpoint:
points Ollama at a dead port so the router fails over, then a short planning
prompt must complete via NIM and the decision trail must record the failover.

Run:  uv run python tools/smoke_router.py
"""

from __future__ import annotations

import asyncio
import sys

import httpx

from src.common.config import get_settings
from src.common.nvidia_nim import NimClient
from src.common.ollama import OllamaClient
from src.common.router import ReasonRouter


async def main() -> int:
    s = get_settings()
    # Dead Ollama — forces failover without disturbing the real service.
    s_dead = s.model_copy(update={"ollama_host": "http://127.0.0.1:1"})
    dead_oc = OllamaClient(s_dead, client=httpx.AsyncClient(timeout=httpx.Timeout(5.0)))
    nim = NimClient(s)
    router = ReasonRouter(s, ollama=dead_oc, nim=nim)

    prompt = [
        {
            "role": "system",
            "content": "You are a brand designer. Reply with one short sentence.",
        },
        {"role": "user", "content": "Describe a warm coffee brand palette in one sentence."},
    ]
    print("[smoke] calling router with dead Ollama + real NIM (local-first)…", flush=True)
    try:
        out = await router.chat(s.ollama_reasoning_model, prompt, think=False)
    except Exception as e:  # noqa: BLE001
        print(f"[smoke] FAIL: router raised {type(e).__name__}: {e}", flush=True)
        await router.aclose()
        return 1

    print(f"[smoke] response ({len(out)} chars): {out[:160]}…", flush=True)
    print(f"[smoke] decisions: {router.decisions}", flush=True)
    print(f"[smoke] sticky_backend: {router.sticky_backend}", flush=True)

    ok = (
        router.sticky_backend == "nim"
        and router.decisions[0]["backend"] == "ollama"
        and router.decisions[0]["ok"] is False
        and router.decisions[1]["backend"] == "nim"
        and router.decisions[1]["ok"] is True
        and len(out) > 0
    )
    print(f"[smoke] {'PASS' if ok else 'FAIL'}: local->NIM failover", flush=True)
    await router.aclose()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
