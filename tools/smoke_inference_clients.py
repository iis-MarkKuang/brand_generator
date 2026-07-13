#!/usr/bin/env python3
"""CP-002 live smoke — exercise all four inference backends against real services.

Run on the DGX Spark after `ollama-ctl.sh start` and `comfyui-ctl.sh start`:

    PYTHONPATH=. uv run python tools/smoke_inference_clients.py

Exits non-zero if any backend fails to respond. NIM's Nemotron is a reasoning
model: ``message.content`` may be ``None`` with the answer in
``reasoning_content`` — that is expected here (transport check); CP-013 handles
content extraction.
"""

from __future__ import annotations

import asyncio
import io
import sys

from PIL import Image

from src.common.comfyui import ComfyUIClient
from src.common.config import get_settings
from src.common.nvidia_nim import NimClient
from src.common.ollama import OllamaClient
from src.common.stepfun import StepfunClient, bytes_to_data_url


async def main() -> int:
    s = get_settings()
    rc = 0

    try:
        buf = io.BytesIO()
        Image.new("RGB", (64, 64), (200, 30, 30)).save(buf, format="PNG")
        url = bytes_to_data_url(buf.getvalue(), "image/png")
        sc = StepfunClient(s)
        msgs = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": 'Return ONLY JSON: {"dominant_color":"#rrggbb"} for this image.',
                    },
                    {"type": "image_url", "image_url": {"url": url}},
                ],
            }
        ]
        out = await sc.chat_vlm(msgs, reasoning_effort="low", image_detail="low")
        print(f"[stepfun] VLM parsed JSON: {out}")
        await sc.aclose()
    except Exception as e:  # noqa: BLE001
        rc = 1
        print(f"[stepfun] FAILED: {e!r}")

    try:
        oc = OllamaClient(s)
        reply = await oc.chat(
            s.ollama_light_model,
            [{"role": "user", "content": "Reply with exactly: ok"}],
            think=False,
        )
        print(f"[ollama] {s.ollama_light_model!r} -> {reply!r}")
        await oc.aclose()
    except Exception as e:  # noqa: BLE001
        rc = 1
        print(f"[ollama] FAILED: {e!r}")

    try:
        nc = NimClient(s)
        body = await nc.chat(
            messages=[{"role": "user", "content": "Reply with exactly: ok"}], max_tokens=64
        )
        msg = body["choices"][0]["message"]
        content = msg.get("content")
        reasoning = (msg.get("reasoning_content") or "")[:60]
        print(f"[nim] {s.nvidia_nim_model!r} -> content={content!r} reasoning={reasoning!r}")
        await nc.aclose()
    except Exception as e:  # noqa: BLE001
        rc = 1
        print(f"[nim] FAILED: {e!r}")

    try:
        cc = ComfyUIClient(s)
        print(f"[comfyui] health={await cc.health()}")
        await cc.aclose()
    except Exception as e:  # noqa: BLE001
        rc = 1
        print(f"[comfyui] FAILED: {e!r}")

    return rc


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
