#!/usr/bin/env python3
"""CP-004 live smoke — real local reasoning model plans a kit from a sample BrandDna.

    PYTHONPATH=. uv run python tools/smoke_art_director.py

Uses OLLAMA_REASONING_MODEL (nemotron-3-nano:30b when ready, else qwen3.6:35b) with
think=False. Writes runs/<id>/asset_manifest.json.
"""

from __future__ import annotations

import asyncio
import sys

from src.agents.art_director import plan_assets
from src.common.config import get_settings
from src.common.ollama import OllamaClient
from src.common.runs import RunDir, new_run_id
from src.common.schemas import BrandDna

DNA = BrandDna.model_validate(
    {
        "brand_name": "Nova Lin",
        "palette": [
            {"name": "Obsidian", "hex": "#0D0D0F", "rank": "primary"},
            {"name": "Nova Teal", "hex": "#00D4AA", "rank": "accent"},
            {"name": "Pure White", "hex": "#FFFFFF", "rank": "neutral"},
            {"name": "Cloud Gray", "hex": "#F2F2F7", "rank": "neutral"},
            {"name": "Cool Gray", "hex": "#8E8E93", "rank": "neutral"},
        ],
        "mood": ["approachable", "technical", "energetic", "modern", "reliable"],
        "typography_class": "sans",
        "typography_pairs": {"headline": "geometric sans", "body": "humanist sans"},
        "visual_keywords": [
            "headshot",
            "minimalist",
            "tech-casual",
            "monochrome",
            "studio-lit",
            "professional",
            "crisp",
            "geometric",
        ],
        "dos": ["generous whitespace", "teal accent"],
        "donts": ["neon", "cluttered"],
        "personality": "Approachable, technical, energetic developer advocate.",
    }
)

TYPES = ["logo", "hero_banner", "social_square", "product_mockup", "business_card"]


async def main() -> int:
    s = get_settings()
    run = RunDir("runs", new_run_id()).ensure()
    oc = OllamaClient(s)
    try:
        manifest = await plan_assets(
            DNA, TYPES, run_dir=run, client=oc, cache_dir="cache/asset_manifest"
        )
    finally:
        await oc.aclose()
    print(f"run_id={run.run_id} model={s.ollama_reasoning_model}")
    for a in manifest.assets:
        print(f"  {a.id:16} size={a.size} seed={a.seed} pulid={a.uses_pulid}")
        print(f"    prompt: {a.flux_prompt}")
        print(f"    neg:    {a.negative_prompt}")
    print(f"written: {run.manifest_path()}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
