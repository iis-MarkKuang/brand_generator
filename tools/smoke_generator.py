#!/usr/bin/env python3
"""CP-005 live smoke — render a 1024x1024 logo via the real ComfyUI FLUX pipeline.

PYTHONPATH=. uv run python tools/smoke_generator.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from src.agents.generator import generate_asset
from src.common.config import get_settings
from src.common.runs import RunDir, new_run_id
from src.common.schemas import AssetSpec

SPEC = AssetSpec(
    id="logo",
    type="logo",
    size=[1024, 1024],
    seed=42125,
    flux_prompt="minimalist coffee roaster logo, 'Ember & Oat' warm serif wordmark, "
    "#3B2417 espresso on #F3E9D8 oat-cream, hand-drawn bean motif, centered, "
    "generous whitespace, flat vector, high contrast",
    negative_prompt="photorealistic, 3d, neon, cluttered, gradient mesh, watermark, text errors",
    composition="centered, square-safe",
    uses_pulid=False,
)


async def main() -> int:
    s = get_settings()
    run = RunDir("runs", new_run_id()).ensure()
    result = await generate_asset(SPEC, run, attempt=1, settings=s, max_wait_s=180)
    print(f"run_id={run.run_id}")
    print(f"prompt_id={result.prompt_id} seed={result.seed} steps={result.steps}")
    print(f"latency_s={result.latency_s} vram_free_mib={result.vram_free_mib}")
    if result.error:
        print(f"ERROR: {result.error}")
        return 1
    print(f"png: {result.png_path} ({Path(result.png_path).stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
