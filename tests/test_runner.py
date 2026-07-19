"""Unit tests for the master orchestrator loop (fully mocked agents)."""

from __future__ import annotations

import asyncio
import io
from pathlib import Path

import pytest
from PIL import Image

from src.common.schemas import (
    AssetManifest,
    AssetSpec,
    BrandDna,
    CriticResult,
    KitManifest,
    OptimizationStats,
    RenderResult,
    RunInput,
    RunOptions,
)
from src.orchestrator.runner import run_pipeline

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
        "personality": "Warm, unhurried, craft-first roaster.",
    }
)


class MockOllama:
    async def stop(self, model: str) -> None:
        pass

    async def aclose(self) -> None:
        pass


class MockComfyUI:
    async def health(self) -> bool:
        return True

    async def aclose(self) -> None:
        pass


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (2, 2), (60, 40, 20)).save(buf, "PNG")
    return buf.getvalue()


def _spec(type_: str) -> AssetSpec:
    return AssetSpec(
        id=type_,
        type=type_,
        size=[1024, 1024],
        seed=hash(type_) % 1000,
        flux_prompt=f"{type_} #3B2417 #F3E9D8 Ember & Oat",
        negative_prompt="neon",
        composition="centered",
        uses_pulid=False,
    )


def _run_input(
    assets: list[str], *, max_retries: int = 1, run_id: str = "test-run-001"
) -> RunInput:
    return RunInput(
        run_id=run_id,
        brand_name="Ember & Oat",
        brief="a coffee roaster",
        reference_images=["x.png"],
        options=RunOptions(assets=assets, max_retries_per_asset=max_retries),
    )


def _make_fns(
    tmp_path: Path,
    *,
    critic_pass_ids: set[str] | None = None,
    always_fail: bool = False,
    slow: bool = False,
    cancel_event: asyncio.Event | None = None,
):
    """Build mocked analyze/plan/generate/critic/rewrite callables."""
    critic_pass_ids = critic_pass_ids if critic_pass_ids is not None else set()

    async def analyze(brief, images, brand_name, *, run_dir, settings, client):
        return DNA

    async def plan(dna, assets, *, run_dir, settings, client, **kwargs):
        return AssetManifest(run_id=run_dir.run_id, assets=[_spec(t) for t in assets])

    async def generate(spec, run_dir, attempt, *, settings, client, restart_fn=None):
        if slow:
            await asyncio.sleep(0.6)
        p = run_dir.asset_path(spec.id, attempt)
        p.write_bytes(_png_bytes())
        if cancel_event is not None and spec.id == "logo":
            cancel_event.set()
        return RenderResult(
            asset_id=spec.id,
            attempt=attempt,
            png_path=str(p),
            prompt_id="p",
            seed=spec.seed,
            steps=24,
            cfg=1.0,
            latency_s=0.01,
        )

    async def critic(png_path, spec, dna, *, run_dir, attempt, settings, client):
        passed = (not always_fail) and (spec.id in critic_pass_ids)
        return CriticResult.model_validate(
            {
                "run_id": run_dir.run_id,
                "asset_id": spec.id,
                "attempt": attempt,
                "png_path": str(png_path),
                "pass": passed,
                "score": 88 if passed else 60,
                "palette_match": 0.9,
                "mood_match": 0.9,
                "legibility": 0.9,
                "on_brand": 0.9,
                "feedback": "" if passed else "fix the palette",
            }
        )

    async def rewrite(spec, feedback, *, settings, client):
        return spec.model_copy(update={"flux_prompt": spec.flux_prompt + " revised"})

    return analyze, plan, generate, critic, rewrite


def _run(run_input, fake_settings, tmp_path, fns, *, cancel_event=None, ollama=None, comfyui=None):
    analyze, plan, generate, critic, rewrite = fns
    fake_settings.runs_root = str(tmp_path / "runs")  # isolate each test's run dir
    return run_pipeline(
        run_input,
        settings=fake_settings,
        ollama_client=ollama or MockOllama(),
        comfyui_client=comfyui or MockComfyUI(),
        cancel_event=cancel_event,
        analyze_fn=analyze,
        plan_fn=plan,
        generate_fn=generate,
        critic_fn=critic,
        rewrite_fn=rewrite,
    )


@pytest.mark.asyncio
async def test_runner_partial_kit_2_approved_1_failed(fake_settings, tmp_path) -> None:
    fns = _make_fns(tmp_path, critic_pass_ids={"logo", "hero_banner"})
    kit = await _run(
        _run_input(["logo", "hero_banner", "social_square"]), fake_settings, tmp_path, fns
    )
    assert isinstance(kit, KitManifest)
    statuses = {a.id: a.status for a in kit.assets}
    assert statuses == {"logo": "approved", "hero_banner": "approved", "social_square": "failed"}
    assert kit.status == "partial"
    # brand guide has all palette hex + asset list
    guide = (tmp_path / "runs" / "test-run-001" / "brand_kit" / "brand_guide.md").read_text()
    for hexc in ("#3B2417", "#F3E9D8", "#C26B3C", "#5B6B47", "#1E1A17"):
        assert hexc in guide
    assert "logo" in guide and "social_square" in guide
    # kit manifest validates and has optimization stats
    assert kit.optimization_stats.vram_swaps >= 1
    assert kit.optimization_stats.total_vlm_calls >= 3
    assert kit.optimization_stats.critic_effort_medium_count >= 1


@pytest.mark.asyncio
async def test_runner_vlm_cap_no_runaway(fake_settings, tmp_path) -> None:
    fake_settings.max_total_vlm_calls = 3  # analyze(1) + 2 critic calls, then stop
    fns = _make_fns(tmp_path, always_fail=True)
    kit = await _run(
        _run_input(["logo", "hero_banner", "social_square"], max_retries=1),
        fake_settings,
        tmp_path,
        fns,
    )
    assert kit.status == "partial"
    assert kit.optimization_stats.total_vlm_calls <= 3
    assert all(a.status == "failed" for a in kit.assets)


@pytest.mark.asyncio
async def test_runner_timeout_partial(fake_settings, tmp_path) -> None:
    fake_settings.run_timeout_s = 1
    fns = _make_fns(tmp_path, critic_pass_ids={"logo", "hero_banner", "social_square"}, slow=True)
    kit = await _run(
        _run_input(["logo", "hero_banner", "social_square"], max_retries=0),
        fake_settings,
        tmp_path,
        fns,
    )
    # at least one asset unprocessed due to timeout -> partial
    assert kit.status == "partial"
    approved = sum(1 for a in kit.assets if a.status == "approved")
    assert 0 < approved < 3


@pytest.mark.asyncio
async def test_runner_cancellation(fake_settings, tmp_path) -> None:
    cancel = asyncio.Event()
    fns = _make_fns(
        tmp_path, critic_pass_ids={"logo", "hero_banner", "social_square"}, cancel_event=cancel
    )
    kit = await _run(
        _run_input(["logo", "hero_banner", "social_square"], max_retries=0),
        fake_settings,
        tmp_path,
        fns,
        cancel_event=cancel,
    )
    assert kit.status == "partial"
    # only the first asset (logo) was processed before cancellation
    approved = [a.id for a in kit.assets if a.status == "approved"]
    assert approved == ["logo"]


@pytest.mark.asyncio
async def test_runner_kit_manifest_validates(fake_settings, tmp_path) -> None:
    fns = _make_fns(tmp_path, critic_pass_ids={"logo"})
    kit = await _run(
        _run_input(["logo", "hero_banner"], max_retries=0), fake_settings, tmp_path, fns
    )
    assert kit.run_id == "test-run-001"
    mp = tmp_path / "runs" / "test-run-001" / "brand_kit" / "kit_manifest.json"
    rt = KitManifest.model_validate_json(mp.read_text())
    assert rt.run_id == "test-run-001"
    assert rt.optimization_stats.vram_swaps >= 1
    assert isinstance(rt.optimization_stats, OptimizationStats)
