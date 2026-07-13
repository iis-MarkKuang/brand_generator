#!/usr/bin/env python3
"""CP-006 live smoke — real Stepfun VLM critique of a rendered PNG.

    PYTHONPATH=. uv run python tools/smoke_critic.py

Uses the most recent runs/*/assets/logo__v1.png (or a path arg) + the Ember & Oat DNA.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from src.agents.critic import critic_asset
from src.common.config import get_settings
from src.common.runs import RunDir, new_run_id
from src.common.schemas import AssetSpec, BrandDna

DNA = BrandDna.model_validate(
    {
        "brand_name": "Ember & Oat",
        "palette": [
            {"name": "espresso", "hex": "#3B2417", "rank": "primary"},
            {"name": "oatcream", "hex": "#F3E9D8", "rank": "primary"},
            {"name": "ember", "hex": "#C26B3C", "rank": "accent"},
            {"name": "moss", "hex": "#5B6B47", "rank": "accent"},
            {"name": "ink", "hex": "#1E1A17", "rank": "neutral"},
        ],
        "mood": ["warm", "craft", "earthy", "calm", "handmade"],
        "typography_class": "serif",
        "typography_pairs": {"headline": "warm serif", "body": "humanist sans"},
        "visual_keywords": [
            "coffee",
            "steam",
            "brown-paper",
            "grain",
            "hand-drawn",
            "roaster",
            "kettle",
            "wood",
        ],
        "dos": ["use warm neutrals"],
        "donts": ["neon colors"],
        "personality": "Warm, unhurried, craft-first small-batch roaster.",
    }
)

SPEC = AssetSpec(
    id="logo",
    type="logo",
    size=[1024, 1024],
    seed=42125,
    flux_prompt="minimalist logo #3B2417 #F3E9D8 Ember & Oat",
    negative_prompt="neon, 3d",
    composition="centered",
    uses_pulid=False,
)


def _find_png() -> Path | None:
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    if arg:
        return Path(arg)
    cands = sorted(Path("runs").glob("*/assets/logo__v1.png"))
    return cands[-1] if cands else None


async def main() -> int:
    png = _find_png()
    if not png or not png.exists():
        print("no PNG found (run tools/smoke_generator.py first, or pass a path arg)")
        return 1
    s = get_settings()
    run = RunDir("runs", new_run_id()).ensure()
    res = await critic_asset(png, SPEC, DNA, run_dir=run, attempt=1, settings=s)
    print(f"png={png}")
    print(f"pass={res.pass_} score={res.score}")
    print(
        f"palette_match={res.palette_match} mood_match={res.mood_match} "
        f"legibility={res.legibility} on_brand={res.on_brand}"
    )
    print(f"feedback: {res.feedback}")
    print(f"written: {run.critic_path('logo', 1)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
