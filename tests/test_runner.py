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


@pytest.mark.asyncio
async def test_runner_fail_fast_skips_remaining(fake_settings, tmp_path) -> None:
    """CP-020 fail-fast: if one asset fails, remaining assets are skipped."""
    # logo passes, hero_banner fails (max_retries=0 so 1 attempt), social_square should be skipped
    fns = _make_fns(tmp_path, critic_pass_ids={"logo"})
    kit = await _run(
        _run_input(["logo", "hero_banner", "social_square"], max_retries=0),
        fake_settings,
        tmp_path,
        fns,
    )
    statuses = {a.id: a.status for a in kit.assets}
    assert statuses["logo"] == "approved"
    assert statuses["hero_banner"] == "failed"
    # social_square should be skipped (fail-fast), not processed
    assert statuses["social_square"] == "failed"
    assert "fail-fast" in kit.assets[2].error or "skipped" in kit.assets[2].error
    # Only 2 assets were actually rendered (logo + hero_banner), not social_square
    assert kit.optimization_stats.total_renders == 2


# ---- CP-020: _resolve_reference_indices post-plan hook ------------------ #


def _pulid_spec(aid: str, uses_pulid: bool, ref_idx: int | None = None) -> AssetSpec:
    return AssetSpec(
        id=aid,
        type="logo",  # type: ignore[arg-type]
        size=[1024, 1024],
        seed=1,
        flux_prompt=f"{aid} #3B2417 #F3E9D8 Ember & Oat",
        uses_pulid=uses_pulid,
        reference_index=ref_idx,
    )


def test_resolve_reference_indices_maps_explicit_index() -> None:
    """A uses_pulid asset with reference_index=2 gets pulid_reference = images[1]."""
    from src.orchestrator.runner import _resolve_reference_indices

    manifest = AssetManifest(
        run_id="r1",
        assets=[_pulid_spec("logo", uses_pulid=True, ref_idx=2)],
    )
    out = _resolve_reference_indices(manifest, ["img1.png", "img2.png", "img3.png"])
    assert out.assets[0].pulid_reference == "img2.png"


def test_resolve_reference_indices_defaults_to_first_image() -> None:
    """A uses_pulid asset with no reference_index defaults to the first image."""
    from src.orchestrator.runner import _resolve_reference_indices

    manifest = AssetManifest(
        run_id="r1",
        assets=[_pulid_spec("logo", uses_pulid=True, ref_idx=None)],
    )
    out = _resolve_reference_indices(manifest, ["img1.png", "img2.png"])
    assert out.assets[0].pulid_reference == "img1.png"


def test_resolve_reference_indices_no_pulid_leaves_unset() -> None:
    """A non-PuLID asset with reference_index is left without pulid_reference."""
    from src.orchestrator.runner import _resolve_reference_indices

    manifest = AssetManifest(
        run_id="r1",
        assets=[_pulid_spec("logo", uses_pulid=False, ref_idx=2)],
    )
    out = _resolve_reference_indices(manifest, ["img1.png", "img2.png"])
    assert out.assets[0].pulid_reference is None
    # reference_index is preserved as a semantic annotation
    assert out.assets[0].reference_index == 2


def test_resolve_reference_indices_out_of_range_falls_back() -> None:
    """reference_index beyond the image count falls back to the first image (PuLID)."""
    from src.orchestrator.runner import _resolve_reference_indices

    manifest = AssetManifest(
        run_id="r1",
        assets=[_pulid_spec("logo", uses_pulid=True, ref_idx=5)],
    )
    out = _resolve_reference_indices(manifest, ["img1.png", "img2.png"])
    # index 5 is out of range (only 2 images) → default to first
    assert out.assets[0].pulid_reference == "img1.png"


def test_resolve_reference_indices_empty_images_noop() -> None:
    """No reference images → manifest returned unchanged."""
    from src.orchestrator.runner import _resolve_reference_indices

    manifest = AssetManifest(
        run_id="r1",
        assets=[_pulid_spec("logo", uses_pulid=True, ref_idx=1)],
    )
    out = _resolve_reference_indices(manifest, [])
    assert out.assets[0].pulid_reference is None


# ---- CP-017: consistency wiring in run_pipeline -------------------------- #


@pytest.mark.asyncio
async def test_runner_consistency_check_runs_on_2plus_approved(fake_settings, tmp_path) -> None:
    """When >=2 assets are approved, run_pipeline calls check_consistency and
    embeds the ConsistencyMatrix on the returned KitManifest."""

    from src.common.schemas import ConsistencyMatrix

    consistency_called = {"n": 0}

    async def patched_check_consistency(approved_pairs, dna, *, run_dir, settings, client):
        consistency_called["n"] += 1
        return ConsistencyMatrix(
            overall_score=0.88,
            dimensions=[],
            summary="consistent",
            asset_ids=[a[0] for a in approved_pairs],
        )

    fns = _make_fns(tmp_path, critic_pass_ids={"logo", "hero_banner", "social_square"})
    analyze, plan, generate, critic, rewrite = fns
    fake_settings.runs_root = str(tmp_path / "runs")
    # Patch check_consistency in the runner module
    import src.orchestrator.runner as runner_mod

    orig = runner_mod.check_consistency
    runner_mod.check_consistency = patched_check_consistency  # type: ignore[assignment]
    try:
        kit = await run_pipeline(
            _run_input(["logo", "hero_banner", "social_square"], max_retries=0),
            settings=fake_settings,
            ollama_client=MockOllama(),
            comfyui_client=MockComfyUI(),
            analyze_fn=analyze,
            plan_fn=plan,
            generate_fn=generate,
            critic_fn=critic,
            rewrite_fn=rewrite,
        )
    finally:
        runner_mod.check_consistency = orig  # type: ignore[assignment]

    assert consistency_called["n"] == 1
    assert kit.consistency is not None
    assert kit.consistency.overall_score == pytest.approx(0.88)
    assert kit.consistency.asset_ids == ["logo", "hero_banner", "social_square"]


@pytest.mark.asyncio
async def test_runner_consistency_skipped_on_single_approved(fake_settings, tmp_path) -> None:
    """When only 1 asset is approved, check_consistency is NOT called."""
    consistency_called = {"n": 0}

    async def patched_check_consistency(approved_pairs, dna, *, run_dir, settings, client):
        consistency_called["n"] += 1
        return None  # type: ignore[return-value]

    fns = _make_fns(tmp_path, critic_pass_ids={"logo"})  # only logo passes
    analyze, plan, generate, critic, rewrite = fns
    fake_settings.runs_root = str(tmp_path / "runs")
    import src.orchestrator.runner as runner_mod

    orig = runner_mod.check_consistency
    runner_mod.check_consistency = patched_check_consistency  # type: ignore[assignment]
    try:
        kit = await run_pipeline(
            _run_input(["logo", "hero_banner"], max_retries=0),
            settings=fake_settings,
            ollama_client=MockOllama(),
            comfyui_client=MockComfyUI(),
            analyze_fn=analyze,
            plan_fn=plan,
            generate_fn=generate,
            critic_fn=critic,
            rewrite_fn=rewrite,
        )
    finally:
        runner_mod.check_consistency = orig  # type: ignore[assignment]

    assert consistency_called["n"] == 0
    assert kit.consistency is None
