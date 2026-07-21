"""Unit tests for the Critic agent (mocked Stepfun VLM)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from PIL import Image

from src.agents.critic import critic_asset
from src.common.runs import RunDir
from src.common.schemas import AssetSpec, BrandDna, CriticResult
from src.common.stepfun import StepfunClient

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
    negative_prompt="neon",
    composition="centered",
    uses_pulid=False,
)


def _png(tmp_path: Path) -> Path:
    p = tmp_path / "logo__v1.png"
    Image.new("RGB", (256, 256), (60, 40, 20)).save(p, "PNG")
    return p


def _completion(content: str) -> dict:
    return {"choices": [{"index": 0, "message": {"role": "assistant", "content": content}}]}


def _client(handler, fake_settings) -> StepfunClient:
    return StepfunClient(fake_settings, httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def _scores(score: int, feedback: str = "drop the blue-grey shadow; thicken strokes.") -> dict:
    return {
        "score": score,
        "palette_match": 0.62,
        "mood_match": 0.80,
        "legibility": 0.55,
        "on_brand": 0.70,
        "feedback": feedback,
    }


@pytest.mark.asyncio
async def test_critic_pass_boundary(fake_settings, tmp_path) -> None:
    png = _png(tmp_path)
    run = RunDir(tmp_path / "runs", "test-critic-001").ensure()

    c_pass = _client(
        lambda r: httpx.Response(200, json=_completion(json.dumps(_scores(70)))), fake_settings
    )
    res70 = await critic_asset(
        png, SPEC, DNA, run_dir=run, attempt=1, settings=fake_settings, client=c_pass
    )
    assert res70.pass_ is True and res70.score == 70
    await c_pass.aclose()

    c_fail = _client(
        lambda r: httpx.Response(200, json=_completion(json.dumps(_scores(69)))), fake_settings
    )
    res69 = await critic_asset(
        png, SPEC, DNA, run_dir=run, attempt=1, settings=fake_settings, client=c_fail
    )
    assert res69.pass_ is False and res69.score == 69
    # critic file written and round-trips with the "pass" alias
    rt = CriticResult.model_validate_json(run.critic_path("logo", 1).read_text())
    assert rt.pass_ is False
    await c_fail.aclose()


@pytest.mark.asyncio
async def test_critic_recheck_uses_low_detail(fake_settings, tmp_path) -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured["messages"] = body["messages"]
        return httpx.Response(200, json=_completion(json.dumps(_scores(72))))

    png = _png(tmp_path)
    run = RunDir(tmp_path / "runs", "test-critic-002").ensure()
    c = _client(handler, fake_settings)
    await critic_asset(png, SPEC, DNA, run_dir=run, attempt=2, settings=fake_settings, client=c)
    # find the image_url part in the captured user message
    user = captured["messages"][-1]["content"]
    img_part = next(p for p in user if p.get("type") == "image_url")
    assert img_part["image_url"]["detail"] == "low"
    await c.aclose()


@pytest.mark.asyncio
async def test_critic_repair_path(fake_settings, tmp_path) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        payload = {"score": 70} if calls["n"] == 1 else _scores(75, "good")
        return httpx.Response(200, json=_completion(json.dumps(payload)))

    png = _png(tmp_path)
    run = RunDir(tmp_path / "runs", "test-critic-003").ensure()
    c = _client(handler, fake_settings)
    res = await critic_asset(
        png, SPEC, DNA, run_dir=run, attempt=1, settings=fake_settings, client=c
    )
    assert calls["n"] == 2
    assert res.score == 75 and res.pass_ is True
    await c.aclose()


@pytest.mark.asyncio
async def test_critic_feedback_nonempty_when_fail(fake_settings, tmp_path) -> None:
    png = _png(tmp_path)
    run = RunDir(tmp_path / "runs", "test-critic-004").ensure()

    c_empty = _client(
        lambda r: httpx.Response(200, json=_completion(json.dumps(_scores(50, "")))), fake_settings
    )
    res = await critic_asset(
        png, SPEC, DNA, run_dir=run, attempt=1, settings=fake_settings, client=c_empty
    )
    assert res.pass_ is False
    assert res.feedback.strip() != ""  # fallback enforced
    await c_empty.aclose()


@pytest.mark.asyncio
async def test_critic_structured_failure_never_crashes(fake_settings, tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # always non-JSON → chat_vlm exhausts its internal repair and raises VlmJsonError
        return httpx.Response(200, json=_completion("not json at all !!"))

    png = _png(tmp_path)
    run = RunDir(tmp_path / "runs", "test-critic-005").ensure()
    c = _client(handler, fake_settings)
    res = await critic_asset(
        png, SPEC, DNA, run_dir=run, attempt=1, settings=fake_settings, client=c
    )
    assert res.pass_ is False
    assert res.score == 0
    assert res.feedback.startswith("critic_failed")
    await c.aclose()


# ---- CP-017: deep reasoning chain ------------------------------------------- #


@pytest.mark.asyncio
async def test_critic_deep_reasoning_enriches_scoring(fake_settings, tmp_path) -> None:
    """When critic_deep_reasoning=True + attempt<2, the 3-step chain runs and the
    visual_description + extracted_palette are attached to the CriticResult."""
    fake_settings.critic_deep_reasoning = True
    call_idx = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_idx["n"] += 1
        # call 1: _deep_describe → returns a description string (JSON-wrapped by chat_vlm)
        # call 2: _deep_extract_palette → returns a JSON array of hex strings
        # call 3: scoring → returns the scores object
        if call_idx["n"] == 1:
            return httpx.Response(
                200,
                json=_completion(json.dumps({"description": "warm earthy tones, serif wordmark"})),
            )
        if call_idx["n"] == 2:
            return httpx.Response(
                200, json=_completion(json.dumps(["#3B2417", "#F3E9D8", "#C26B3C"]))
            )
        return httpx.Response(200, json=_completion(json.dumps(_scores(78, "good palette match"))))

    png = _png(tmp_path)
    run = RunDir(tmp_path / "runs", "test-critic-deep-001").ensure()
    c = _client(handler, fake_settings)
    res = await critic_asset(
        png, SPEC, DNA, run_dir=run, attempt=1, settings=fake_settings, client=c
    )
    assert res.score == 78 and res.pass_ is True
    assert res.visual_description != ""
    assert res.extracted_palette == ["#3B2417", "#F3E9D8", "#C26B3C"]
    assert call_idx["n"] == 3  # describe + palette + score
    await c.aclose()


@pytest.mark.asyncio
async def test_critic_deep_reasoning_skipped_on_recheck(fake_settings, tmp_path) -> None:
    """Deep reasoning only runs on attempt<2; attempt=2 skips the chain (token economy)."""
    fake_settings.critic_deep_reasoning = True
    call_idx = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_idx["n"] += 1
        return httpx.Response(200, json=_completion(json.dumps(_scores(72))))

    png = _png(tmp_path)
    run = RunDir(tmp_path / "runs", "test-critic-deep-002").ensure()
    c = _client(handler, fake_settings)
    res = await critic_asset(
        png, SPEC, DNA, run_dir=run, attempt=2, settings=fake_settings, client=c
    )
    # only the scoring call runs (no describe/palette on recheck)
    assert call_idx["n"] == 1
    assert res.visual_description == ""
    assert res.extracted_palette == []
    await c.aclose()


@pytest.mark.asyncio
async def test_critic_deep_reasoning_survives_step_failure(fake_settings, tmp_path) -> None:
    """If a deep step (describe/palette) fails, scoring still proceeds with empty enrichment."""
    fake_settings.critic_deep_reasoning = True
    call_idx = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_idx["n"] += 1
        if call_idx["n"] <= 2:
            # deep steps return garbage → _deep_* helpers catch and return ""
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json=_completion(json.dumps(_scores(74))))

    png = _png(tmp_path)
    run = RunDir(tmp_path / "runs", "test-critic-deep-003").ensure()
    c = _client(handler, fake_settings)
    res = await critic_asset(
        png, SPEC, DNA, run_dir=run, attempt=1, settings=fake_settings, client=c
    )
    # deep steps failed gracefully; scoring still succeeded
    assert res.score == 74
    assert res.visual_description == ""
    assert res.extracted_palette == []
    await c.aclose()
