"""Unit tests for the cross-asset consistency checker (CP-017)."""

from __future__ import annotations

import json

import httpx
import pytest
from PIL import Image

from src.agents.consistency import check_consistency
from src.common.runs import RunDir
from src.common.schemas import BrandDna
from src.common.stepfun import StepfunClient

DNA = BrandDna.model_validate(
    {
        "brand_name": "TestBrand",
        "palette": [
            {"name": "Green", "hex": "#1A3C2A", "rank": "primary"},
            {"name": "Gold", "hex": "#C9A96E", "rank": "accent"},
        ],
        "mood": ["earthy", "premium"],
        "typography_class": "serif",
        "typography_pairs": {"headline": "Playfair Display", "body": "Inter"},
        "visual_keywords": ["minimalist"],
        "dos": [],
        "donts": [],
        "personality": "refined",
    }
)


def _png(path, size=(200, 200), color=(26, 60, 42)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)


def _completion(text: str) -> dict:
    return {"choices": [{"message": {"content": text}}]}


def _client(handler, fake_settings) -> StepfunClient:
    return StepfunClient(fake_settings, httpx.AsyncClient(transport=httpx.MockTransport(handler)))


@pytest.mark.asyncio
async def test_consistency_single_asset_skips(fake_settings, tmp_path) -> None:
    run = RunDir(tmp_path / "runs", "test-cons-001").ensure()
    png1 = tmp_path / "a.png"
    _png(png1)
    matrix = await check_consistency(
        [("logo", png1)], DNA, run_dir=run, settings=fake_settings,
    )
    assert matrix.overall_score == 1.0
    assert "single asset" in matrix.summary
    await StepfunClient(fake_settings, httpx.AsyncClient()).aclose()


@pytest.mark.asyncio
async def test_consistency_multi_asset_returns_matrix(fake_settings, tmp_path) -> None:
    run = RunDir(tmp_path / "runs", "test-cons-002").ensure()
    png1 = tmp_path / "logo.png"
    png2 = tmp_path / "hero.png"
    _png(png1)
    _png(png2)

    payload = {
        "overall_score": 0.82,
        "dimensions": [
            {"dimension": "palette", "score": 0.9, "notes": "colors match well"},
            {"dimension": "typography", "score": 0.8, "notes": "consistent serif"},
            {"dimension": "mood", "score": 0.75, "notes": "earthy throughout"},
            {"dimension": "composition", "score": 0.83, "notes": "balanced layouts"},
        ],
        "summary": "Strong overall consistency with minor mood drift.",
    }
    c = _client(lambda r: httpx.Response(200, json=_completion(json.dumps(payload))), fake_settings)
    matrix = await check_consistency(
        [("logo", png1), ("hero_banner", png2)], DNA, run_dir=run, client=c,
    )
    assert matrix.overall_score == pytest.approx(0.82)
    assert len(matrix.dimensions) == 4
    assert matrix.dimensions[0].dimension == "palette"
    assert matrix.asset_ids == ["logo", "hero_banner"]
    assert (run.path / "consistency_matrix.json").exists()
    await c.aclose()


@pytest.mark.asyncio
async def test_consistency_never_crashes_on_bad_json(fake_settings, tmp_path) -> None:
    run = RunDir(tmp_path / "runs", "test-cons-003").ensure()
    png1 = tmp_path / "logo.png"
    png2 = tmp_path / "hero.png"
    _png(png1)
    _png(png2)

    c = _client(lambda r: httpx.Response(200, json=_completion("not json!!")), fake_settings)
    matrix = await check_consistency(
        [("logo", png1), ("hero_banner", png2)], DNA, run_dir=run, client=c,
    )
    assert matrix.overall_score == 0.0
    assert "failed" in matrix.summary.lower()
    await c.aclose()
