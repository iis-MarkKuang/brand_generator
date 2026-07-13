#!/usr/bin/env python3
"""CP-003 live smoke — real Stepfun VLM call on the workshop sample image.

PYTHONPATH=. uv run python tools/smoke_brand_analyst.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from src.agents.brand_analyst import analyze_brand
from src.common.config import get_settings
from src.common.runs import RunDir, new_run_id
from src.common.stepfun import StepfunClient

SAMPLE = Path("/home/Developer/build_a_claw_workshop-bundle/sample/sample_face.jpg")


async def main() -> int:
    if not SAMPLE.exists():
        print(f"sample image not found: {SAMPLE}")
        return 1
    s = get_settings()
    run = RunDir("runs", new_run_id()).ensure()
    sc = StepfunClient(s)
    try:
        dna = await analyze_brand(
            "A modern, friendly personal brand for a developer advocate; "
            "approachable, technical, energetic.",
            SAMPLE,
            "Nova Lin",
            run_dir=run,
            client=sc,
            cache_dir="cache/brand_dna",
        )
    finally:
        await sc.aclose()
    print(f"run_id={run.run_id}")
    print(f"brand_name={dna.brand_name}")
    print(f"typography_class={dna.typography_class}")
    print("palette:", [(c.name, c.hex, c.rank) for c in dna.palette])
    print("mood:", dna.mood)
    print("visual_keywords:", dna.visual_keywords)
    print(f"written: {run.brand_dna_path()}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
