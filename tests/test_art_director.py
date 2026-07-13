"""Unit tests for the Art Director agent (mocked Ollama)."""

from __future__ import annotations

import json

import httpx
import pytest

from src.agents.art_director import _plan_cache_key, brand_hash, plan_assets, rewrite_prompt
from src.common.ollama import OllamaClient
from src.common.runs import RunDir
from src.common.schemas import AssetManifest, AssetSpec, BrandDna

DNA_DICT: dict[str, object] = {
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
    "dos": ["use warm neutrals", "keep whitespace"],
    "donts": ["neon colors", "glassy 3D"],
    "personality": "Warm, unhurried, craft-first small-batch roaster.",
}

ASSET_TYPES = ["logo", "hero_banner", "social_square", "product_mockup", "business_card"]


def _asset_dicts() -> list[dict[str, object]]:
    return [
        {
            "type": "logo",
            "size": [1024, 1024],
            "flux_prompt": "minimalist coffee roaster logo, 'Ember & Oat' wordmark, warm serif, #3B2417 on #F3E9D8, hand-drawn bean, centered",
            "negative_prompt": "photorealistic, 3d, neon, cluttered",
            "composition": "centered",
            "uses_pulid": False,
        },
        {
            "type": "hero_banner",
            "size": [1344, 768],
            "flux_prompt": "coffee roaster hero banner, steam, kraft paper, #3B2417 #C26B3C palette, warm studio light",
            "negative_prompt": "neon, corporate blue",
            "composition": "wide hero",
            "uses_pulid": False,
        },
        {
            "type": "social_square",
            "size": [1024, 1024],
            "flux_prompt": "instagram square, coffee cup top-down, #5B6B47 #F3E9D8, grain texture, handmade",
            "negative_prompt": "cluttered, watermark",
            "composition": "square",
            "uses_pulid": False,
        },
        {
            "type": "product_mockup",
            "size": [1024, 1024],
            "flux_prompt": "kraft coffee bag mockup, 'Ember & Oat' label, #3B2417 #C26B3C, brown-paper table",
            "negative_prompt": "3d render, neon",
            "composition": "product hero",
            "uses_pulid": False,
        },
        {
            "type": "business_card",
            "size": [1024, 576],
            "flux_prompt": "business card, warm serif, #1E1A17 text on #F3E9D8, espresso accent #C26B3C",
            "negative_prompt": "glossy, neon",
            "composition": "card layout",
            "uses_pulid": False,
        },
    ]


def _dna() -> BrandDna:
    return BrandDna.model_validate(DNA_DICT)


def _client(handler, fake_settings) -> OllamaClient:
    return OllamaClient(fake_settings, httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def _ok_handler(payload: dict[str, object]):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["think"] is False
        return httpx.Response(
            200,
            json={"message": {"role": "assistant", "content": json.dumps(payload)}, "done": True},
        )

    return handler


@pytest.mark.asyncio
async def test_plan_assets_valid(fake_settings, tmp_path) -> None:
    c = _client(_ok_handler({"assets": _asset_dicts()}), fake_settings)
    run = RunDir(tmp_path / "runs", "test-ad-001").ensure()
    manifest = await plan_assets(
        _dna(), ASSET_TYPES, run_dir=run, client=c, cache_dir=tmp_path / "c1"
    )
    assert isinstance(manifest, AssetManifest)
    assert [a.type for a in manifest.assets] == ASSET_TYPES
    assert all(a.id == a.type for a in manifest.assets)
    assert all(len(a.flux_prompt) <= 600 for a in manifest.assets)
    # run file written and round-trips
    rt = AssetManifest.model_validate_json(run.manifest_path().read_text())
    assert len(rt.assets) == 5
    await c.aclose()


@pytest.mark.asyncio
async def test_plan_assets_reproducible_seeds(fake_settings, tmp_path) -> None:
    run1 = RunDir(tmp_path / "runs", "test-ad-002a").ensure()
    run2 = RunDir(tmp_path / "runs", "test-ad-002b").ensure()
    c1 = _client(_ok_handler({"assets": _asset_dicts()}), fake_settings)
    m1 = await plan_assets(_dna(), ASSET_TYPES, run_dir=run1, client=c1, cache_dir=tmp_path / "c1")
    c2 = _client(_ok_handler({"assets": _asset_dicts()}), fake_settings)
    m2 = await plan_assets(_dna(), ASSET_TYPES, run_dir=run2, client=c2, cache_dir=tmp_path / "c2")
    assert [a.seed for a in m1.assets] == [a.seed for a in m2.assets]
    await c1.aclose()
    await c2.aclose()


@pytest.mark.asyncio
async def test_plan_assets_repair(fake_settings, tmp_path) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        payload = (
            {"assets": [{"type": "logo", "flux_prompt": "no hex here"}]}
            if calls["n"] == 1
            else {"assets": _asset_dicts()}
        )
        return httpx.Response(200, json={"message": {"content": json.dumps(payload)}, "done": True})

    c = _client(handler, fake_settings)
    run = RunDir(tmp_path / "runs", "test-ad-003").ensure()
    manifest = await plan_assets(
        _dna(), ASSET_TYPES, run_dir=run, client=c, cache_dir=tmp_path / "c"
    )
    assert calls["n"] == 2
    assert len(manifest.assets) == 5
    await c.aclose()


@pytest.mark.asyncio
async def test_plan_assets_cache_hit_skips_ollama(fake_settings, tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Ollama must not be called on a cache hit")

    dna = _dna()
    bd = brand_hash(dna)
    key = _plan_cache_key(bd, ASSET_TYPES)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    cached = AssetManifest(
        run_id="old-run",
        assets=[
            AssetSpec(
                id="logo",
                type="logo",
                size=[1024, 1024],
                seed=42,
                flux_prompt="logo #3B2417 #F3E9D8 Ember & Oat",
                negative_prompt="x",
            )
        ],
    )
    (cache_dir / f"{key}.json").write_text(cached.model_dump_json(), encoding="utf-8")

    c = _client(handler, fake_settings)
    run = RunDir(tmp_path / "runs", "test-ad-004").ensure()
    manifest = await plan_assets(dna, ASSET_TYPES, run_dir=run, client=c, cache_dir=cache_dir)
    assert manifest.run_id == "test-ad-004"  # re-stamped
    assert len(manifest.assets) == 1
    await c.aclose()


@pytest.mark.asyncio
async def test_rewrite_prompt_incorporates_feedback(fake_settings) -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured["messages"] = body["messages"]
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": json.dumps(
                        {
                            "flux_prompt": "minimalist logo, warmer tones, desaturated, #3B2417 #F3E9D8",
                            "negative_prompt": "neon, oversaturated",
                        }
                    )
                },
                "done": True,
            },
        )

    c = _client(handler, fake_settings)
    spec = AssetSpec(
        id="logo",
        type="logo",
        size=[1024, 1024],
        seed=7,
        flux_prompt="logo #3B2417 #F3E9D8",
        negative_prompt="x",
    )
    feedback = "reduce saturation and use warmer tones"
    new_spec = await rewrite_prompt(spec, feedback, client=c)
    assert "warmer" in new_spec.flux_prompt
    assert new_spec.seed == 7  # unchanged
    # the feedback was sent to the model
    sent = json.dumps(captured["messages"])
    assert "reduce saturation and use warmer tones" in sent
    await c.aclose()
