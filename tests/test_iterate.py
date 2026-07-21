"""Unit tests for iterate_run (CP-019 conversational iteration).

Exercises the real iterate_run with mocked generate/critic/rewrite fns so the
load-prev → rewrite → re-render → copy-unchanged → re-assemble path is covered
without touching GPU/Stepfun.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image

from src.common.schemas import (
    AssetManifest,
    AssetSpec,
    BrandDna,
    CriticResult,
    KitAsset,
    KitManifest,
    OptimizationStats,
    RenderResult,
)
from src.orchestrator.runner import iterate_run

DNA = BrandDna.model_validate(
    {
        "brand_name": "Ember & Oat",
        "palette": [
            {"name": "espresso", "hex": "#3B2417", "rank": "primary"},
            {"name": "oatcream", "hex": "#F3E9D8", "rank": "primary"},
            {"name": "ember", "hex": "#C26B3C", "rank": "accent"},
        ],
        "mood": ["warm", "craft"],
        "typography_class": "serif",
        "typography_pairs": {"headline": "warm serif", "body": "humanist sans"},
        "visual_keywords": ["coffee", "steam"],
        "dos": ["use warm neutrals"],
        "donts": ["neon colors"],
        "personality": "Warm, unhurried, craft-first roaster.",
    }
)


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (60, 40, 20)).save(buf, "PNG")
    return buf.getvalue()


def _spec(aid: str, type_: str = "logo") -> AssetSpec:
    return AssetSpec(
        id=aid,
        type=type_,  # type: ignore[arg-type]
        size=[1024, 1024],
        seed=hash(aid) % 1000,
        flux_prompt=f"{aid} #3B2417 #F3E9D8 Ember & Oat",
        negative_prompt="neon",
        composition="centered",
        uses_pulid=False,
    )


def _write_prev_run(runs_root: Path, prev_id: str, approved: list[str]) -> None:
    """Lay down a complete prev run dir: brand_dna.json, asset_manifest.json, kit_manifest.json, kit pngs."""
    prev = runs_root / prev_id
    (prev / "brand_kit").mkdir(parents=True, exist_ok=True)
    (prev / "assets").mkdir(parents=True, exist_ok=True)
    # brand_dna
    (prev / "brand_dna.json").write_text(DNA.model_dump_json(indent=2))
    # asset_manifest
    specs = [_spec(aid) for aid in approved]
    (prev / "asset_manifest.json").write_text(
        AssetManifest(run_id=prev_id, assets=specs).model_dump_json(indent=2)
    )
    # kit_manifest + kit pngs
    kit_assets = [
        KitAsset(
            id=aid,
            type="logo",
            path=f"brand_kit/{aid}.png",
            status="approved",
            final_score=80,
            error=None,
        )
        for aid in approved
    ]
    for aid in approved:
        (prev / "brand_kit" / f"{aid}.png").write_bytes(_png_bytes())
    kit = KitManifest(
        run_id=prev_id,
        brand_name=DNA.brand_name,
        status="complete",
        assets=kit_assets,
        palette=[c.hex for c in DNA.palette],
        generated_at=datetime.now(UTC),
        total_latency_s=10,
        optimization_stats=OptimizationStats(),
    )
    (prev / "brand_kit" / "kit_manifest.json").write_text(kit.model_dump_json(indent=2))


class _MockOllama:
    async def stop(self, model: str) -> None:
        pass

    async def aclose(self) -> None:
        pass


class _MockComfyUI:
    async def health(self) -> bool:
        return True

    async def aclose(self) -> None:
        pass


def _make_fns(rerender_pass: bool = True):
    """Mocked generate/critic/rewrite for iterate_run."""
    rewrite_calls: list[str] = []

    async def generate(spec, run_dir, attempt, *, settings, client, restart_fn=None):
        p = run_dir.asset_path(spec.id, attempt)
        p.write_bytes(_png_bytes())
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
        return CriticResult.model_validate(
            {
                "run_id": run_dir.run_id,
                "asset_id": spec.id,
                "attempt": attempt,
                "png_path": str(png_path),
                "pass": rerender_pass,
                "score": 85 if rerender_pass else 50,
                "palette_match": 0.9,
                "mood_match": 0.9,
                "legibility": 0.9,
                "on_brand": 0.9,
                "feedback": "" if rerender_pass else "fix palette",
            }
        )

    async def rewrite(spec, feedback, *, settings, client):
        rewrite_calls.append(spec.id)
        return spec.model_copy(update={"flux_prompt": spec.flux_prompt + " revised"})

    return generate, critic, rewrite, rewrite_calls


def _run_iterate(tmp_path, fake_settings, prev_id, new_id, request, fns):
    generate, critic, rewrite, _ = fns
    fake_settings.runs_root = str(tmp_path / "runs")
    return iterate_run(
        prev_id,
        request,
        new_run_id=new_id,
        settings=fake_settings,
        ollama_client=_MockOllama(),
        comfyui_client=_MockComfyUI(),
        generate_fn=generate,
        critic_fn=critic,
        rewrite_fn=rewrite,
    )


@pytest.mark.asyncio
async def test_iterate_rerenders_all_approved(fake_settings, tmp_path) -> None:
    """Iterate with empty assets list → re-renders all approved assets."""
    runs = tmp_path / "runs"
    _write_prev_run(runs, "prev-001", approved=["logo", "hero_banner"])
    fns = _make_fns(rerender_pass=True)
    from src.common.schemas import IterateRequest

    kit = await _run_iterate(
        tmp_path,
        fake_settings,
        "prev-001",
        "new-001",
        IterateRequest(feedback="make it more minimalist"),
        fns,
    )
    assert isinstance(kit, KitManifest)
    assert kit.run_id == "new-001"
    # both assets re-rendered and approved
    statuses = {a.id: a.status for a in kit.assets}
    assert statuses == {"logo": "approved", "hero_banner": "approved"}
    assert kit.status == "complete"
    # rewrite was called for each approved asset
    _, _, rewrite, rewrite_calls = fns
    assert sorted(rewrite_calls) == ["hero_banner", "logo"]
    # new run dir has the re-rendered kit pngs
    new_kit_png = runs / "new-001" / "brand_kit" / "logo.png"
    assert new_kit_png.exists()


@pytest.mark.asyncio
async def test_iterate_copies_unchanged_assets(fake_settings, tmp_path) -> None:
    """Iterate requesting only `logo` → hero_banner is copied unchanged from prev run."""
    runs = tmp_path / "runs"
    _write_prev_run(runs, "prev-002", approved=["logo", "hero_banner"])
    fns = _make_fns(rerender_pass=True)
    from src.common.schemas import IterateRequest

    kit = await _run_iterate(
        tmp_path,
        fake_settings,
        "prev-002",
        "new-002",
        IterateRequest(feedback="redo the logo", assets=["logo"]),
        fns,
    )
    statuses = {a.id: a.status for a in kit.assets}
    # logo re-rendered (approved), hero_banner copied from prev (approved, score 80)
    assert statuses == {"logo": "approved", "hero_banner": "approved"}
    by_id = {a.id: a for a in kit.assets}
    assert by_id["logo"].final_score == 85  # re-rendered score
    assert by_id["hero_banner"].final_score == 80  # preserved from prev
    # hero_banner png was copied into the new run dir
    assert (runs / "new-002" / "brand_kit" / "hero_banner.png").exists()
    # rewrite only called for logo (the re-rendered one)
    _, _, rewrite, rewrite_calls = fns
    assert rewrite_calls == ["logo"]


@pytest.mark.asyncio
async def test_iterate_missing_prev_raises(fake_settings, tmp_path) -> None:
    """Iterate on a non-existent prev run raises FileNotFoundError."""
    (tmp_path / "runs").mkdir()
    from src.common.schemas import IterateRequest

    with pytest.raises(FileNotFoundError):
        await _run_iterate(
            tmp_path,
            fake_settings,
            "no-such-run",
            "new-003",
            IterateRequest(feedback="test"),
            _make_fns(),
        )


@pytest.mark.asyncio
async def test_iterate_partial_when_rerender_fails(fake_settings, tmp_path) -> None:
    """If a re-rendered asset fails critic, the kit is partial but unchanged assets stay approved."""
    runs = tmp_path / "runs"
    _write_prev_run(runs, "prev-004", approved=["logo", "hero_banner"])
    # logo fails critic, hero_banner is copied unchanged
    fns_logo_fail = _make_fns(rerender_pass=False)
    from src.common.schemas import IterateRequest

    kit = await _run_iterate(
        tmp_path,
        fake_settings,
        "prev-004",
        "new-004",
        IterateRequest(feedback="redo the logo", assets=["logo"]),
        fns_logo_fail,
    )
    statuses = {a.id: a.status for a in kit.assets}
    assert statuses == {"logo": "failed", "hero_banner": "approved"}
    assert kit.status == "partial"
