"""Unit tests for the Brand Analyst agent (mocked Stepfun VLM)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from PIL import Image

from src.agents.brand_analyst import analyze_brand, brand_dna_cache_key
from src.common.runs import RunDir
from src.common.schemas import BrandDna
from src.common.stepfun import StepfunClient

VALID_DNA: dict[str, object] = {
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
    "dos": ["use warm neutrals", "keep generous whitespace", "show texture"],
    "donts": ["neon colors", "glassy 3D", "corporate blue"],
    "personality": "Warm, unhurried, craft-first; feels like a small-batch roaster.",
}

INVALID_DNA = {
    **VALID_DNA,
    "palette": [
        {"name": "bad", "hex": "notahex", "rank": "primary"},
        *VALID_DNA["palette"][1:],
    ],
}


def _completion(content: str) -> dict[str, object]:
    return {"choices": [{"index": 0, "message": {"role": "assistant", "content": content}}]}


def _client(handler, fake_settings) -> StepfunClient:
    return StepfunClient(fake_settings, httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def _make_image(tmp_path: Path) -> Path:
    p = tmp_path / "ref.png"
    Image.new("RGB", (256, 256), (80, 120, 60)).save(p, format="PNG")
    return p


@pytest.mark.asyncio
async def test_analyze_brand_valid(fake_settings, tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completion(json.dumps(VALID_DNA)))

    run = RunDir(tmp_path / "runs", "test-run-001").ensure()
    img = _make_image(tmp_path)
    c = _client(handler, fake_settings)
    dna = await analyze_brand(
        "a coffee roaster", img, "Ember & Oat", run_dir=run, client=c, cache_dir=tmp_path / "cache"
    )
    assert dna.brand_name == "Ember & Oat"
    assert len(dna.palette) == 5
    assert dna.typography_class == "serif"
    # run file written and round-trips
    written = BrandDna.model_validate_json(run.brand_dna_path().read_text())
    assert written.palette[0].hex == "#3B2417"
    await c.aclose()


@pytest.mark.asyncio
async def test_analyze_brand_schema_repair(fake_settings, tmp_path) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        payload = INVALID_DNA if calls["n"] == 1 else VALID_DNA
        return httpx.Response(200, json=_completion(json.dumps(payload)))

    run = RunDir(tmp_path / "runs", "test-run-002").ensure()
    img = _make_image(tmp_path)
    c = _client(handler, fake_settings)
    dna = await analyze_brand(
        "brief", img, "Ember & Oat", run_dir=run, client=c, cache_dir=tmp_path / "cache"
    )
    assert calls["n"] == 2  # initial + one schema-repair
    assert dna.palette[0].hex == "#3B2417"
    await c.aclose()


@pytest.mark.asyncio
async def test_analyze_brand_cache_hit_skips_vlm(fake_settings, tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("VLM must not be called on a cache hit")

    run = RunDir(tmp_path / "runs", "test-run-003").ensure()
    img = _make_image(tmp_path)
    key = brand_dna_cache_key("brief", img.read_bytes())
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / f"{key}.json").write_text(json.dumps(VALID_DNA), encoding="utf-8")

    c = _client(handler, fake_settings)
    dna = await analyze_brand(
        "brief", img, "Ember & Oat", run_dir=run, client=c, cache_dir=cache_dir
    )
    assert dna.brand_name == "Ember & Oat"
    # run file still written from cache
    assert run.brand_dna_path().exists()
    await c.aclose()
