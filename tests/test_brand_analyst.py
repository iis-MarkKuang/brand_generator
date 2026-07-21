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


def _make_image_at(path: Path, color: tuple[int, int, int] = (80, 120, 60)) -> Path:
    """Create a test image at an explicit path with a given color."""
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (256, 256), color).save(path, format="PNG")
    return path


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


# ---- CP-020: multi-image branch ----------------------------------------- #


@pytest.mark.asyncio
async def test_analyze_brand_multi_image_builds_labeled_messages(fake_settings, tmp_path) -> None:
    """Multiple reference images → the user message contains 'Image @1:' / 'Image @2:' labels."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured["messages"] = body["messages"]
        return httpx.Response(200, json=_completion(json.dumps(VALID_DNA)))

    run = RunDir(tmp_path / "runs", "test-run-multi-001").ensure()
    img1 = _make_image_at(tmp_path / "ref1.png", (80, 120, 60))
    img2 = _make_image_at(tmp_path / "ref2.png", (200, 100, 40))
    c = _client(handler, fake_settings)
    dna = await analyze_brand(
        "a coffee brand. @1 is logo, @2 is packaging",
        [img1, img2],
        "Ember & Oat",
        run_dir=run,
        client=c,
        cache_dir=tmp_path / "cache",
    )
    assert dna.brand_name == "Ember & Oat"
    # The user message content should contain Image @1: and Image @2: labels
    user_content = captured["messages"][-1]["content"]
    labels = [p["text"] for p in user_content if p.get("type") == "text"]
    assert any("@1" in lbl for lbl in labels), f"missing @1 label in {labels}"
    assert any("@2" in lbl for lbl in labels), f"missing @2 label in {labels}"
    # Two image_url parts present
    imgs = [p for p in user_content if p.get("type") == "image_url"]
    assert len(imgs) == 2
    await c.aclose()


@pytest.mark.asyncio
async def test_analyze_brand_single_image_uses_simple_message(fake_settings, tmp_path) -> None:
    """Single image → the simple (non-labeled) message branch is used."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured["messages"] = body["messages"]
        return httpx.Response(200, json=_completion(json.dumps(VALID_DNA)))

    run = RunDir(tmp_path / "runs", "test-run-single-001").ensure()
    img = _make_image(tmp_path)
    c = _client(handler, fake_settings)
    await analyze_brand(
        "a coffee roaster", img, "Ember & Oat", run_dir=run, client=c, cache_dir=tmp_path / "cache"
    )
    user_content = captured["messages"][-1]["content"]
    # single-image branch: exactly one text part + one image part, no "Image @N:" labels
    labels = [p["text"] for p in user_content if p.get("type") == "text"]
    assert not any("@1" in lbl for lbl in labels)
    imgs = [p for p in user_content if p.get("type") == "image_url"]
    assert len(imgs) == 1
    await c.aclose()


@pytest.mark.asyncio
async def test_analyze_brand_multi_image_cache_key_is_composite(fake_settings, tmp_path) -> None:
    """The cache key for multi-image is composite over all image bytes (brand_dna_cache_key_multi)."""
    from src.agents.brand_analyst import brand_dna_cache_key_multi

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completion(json.dumps(VALID_DNA)))

    run = RunDir(tmp_path / "runs", "test-run-multi-cache").ensure()
    img1 = _make_image_at(tmp_path / "ref1.png", (80, 120, 60))
    img2 = _make_image_at(tmp_path / "ref2.png", (200, 100, 40))
    cache_dir = tmp_path / "cache"
    c = _client(handler, fake_settings)

    # First call populates the cache
    await analyze_brand(
        "brief", [img1, img2], "Ember & Oat", run_dir=run, client=c, cache_dir=cache_dir
    )
    # The cache file should exist under the composite key
    key = brand_dna_cache_key_multi("brief", [img1.read_bytes(), img2.read_bytes()])
    assert (cache_dir / f"{key}.json").exists()

    # Reordering the images produces a different key (order matters)
    key_rev = brand_dna_cache_key_multi("brief", [img2.read_bytes(), img1.read_bytes()])
    assert key != key_rev
    await c.aclose()
