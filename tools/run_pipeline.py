#!/usr/bin/env python3
"""CP-008 Golden E2E — run the full StyleForge pipeline on a real input.

    PYTHONPATH=. uv run python tools/run_pipeline.py \
        --brand "Ember & Oat" --ref /path/to/reference.jpg \
        --assets logo,social_square --run-id golden-001

Writes runs/<id>/brand_kit/{kit_manifest.json, brand_guide.md, <id>.png} and prints
the manifest. Use --assets to scope the run (default: the full 5-asset kit).
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from src.common.config import get_settings
from src.common.schemas import RunInput, RunOptions
from src.orchestrator.runner import run_pipeline


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand", required=True)
    ap.add_argument("--brief", default="A warm, craft-first small-batch coffee roaster.")
    ap.add_argument("--ref", required=True, help="reference image path")
    ap.add_argument("--assets", default="logo,hero_banner,social_square,product_mockup,business_card")
    ap.add_argument("--run-id", default="golden-001")
    ap.add_argument("--max-retries", type=int, default=1)
    args = ap.parse_args()

    assets = [a.strip() for a in args.assets.split(",") if a.strip()]
    run_input = RunInput(run_id=args.run_id, brand_name=args.brand, brief=args.brief,
                         reference_image=args.ref,
                         options=RunOptions(assets=assets, max_retries_per_asset=args.max_retries))

    async def go() -> int:
        kit = await run_pipeline(run_input, settings=get_settings())
        print(f"\n=== KitManifest ({kit.status}) ===")
        print(f"run_id={kit.run_id} brand={kit.brand_name} total_latency_s={kit.total_latency_s}")
        for a in kit.assets:
            print(f"  {a.id:16} {a.status:8} score={a.final_score} err={a.error or ''}")
        print(f"optimization: vram_swaps={kit.optimization_stats.vram_swaps} "
              f"vlm_calls={kit.optimization_stats.total_vlm_calls} "
              f"renders={kit.optimization_stats.total_renders} "
              f"cache_hit={kit.optimization_stats.brand_dna_cache_hit}")
        print(f"kit: runs/{kit.run_id}/brand_kit/kit_manifest.json")
        return 0 if kit.status in ("complete", "partial") else 1

    return asyncio.run(go())


if __name__ == "__main__":
    sys.exit(main())
