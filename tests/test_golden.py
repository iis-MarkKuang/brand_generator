"""Golden end-to-end run shape-drift tests (CP-015).

The golden run (``tests/golden/golden-001_*``) was captured during CP-008's live
E2E on the DGX Spark with real Stepfun VLM + Ollama nemotron-3-nano:30b + ComfyUI
FLUX-dev-fp8. These tests do NOT re-run the pipeline (that needs live models +
GPU); they lock the captured output *shapes* so any schema drift in
``BrandDna`` / ``KitManifest`` / the optimization stats is caught immediately.

If you intentionally change a schema field, update the golden fixtures alongside
the code and document the reason in ``docs/dev-journal.md``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

GOLDEN = Path(__file__).parent / "golden"


def _load(name: str) -> dict:
    return json.loads((GOLDEN / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def inputs() -> dict:
    return _load("golden-001_inputs.json")


@pytest.fixture(scope="module")
def brand_dna() -> dict:
    return _load("golden-001_brand_dna.json")


@pytest.fixture(scope="module")
def kit_manifest() -> dict:
    return _load("golden-001_kit_manifest.json")


# ---- inputs shape -------------------------------------------------------- #


def test_golden_inputs_shape(inputs) -> None:
    assert inputs["run_id"] == "golden-001"
    assert inputs["brand_name"] == "Ember & Oat"
    assert "brief" in inputs and isinstance(inputs["brief"], str) and inputs["brief"]
    assert set(inputs["options"]) >= {"assets", "max_retries_per_asset"}
    assert inputs["options"]["assets"] == ["logo", "social_square"]
    # models block records the actual stack used (VLM / reasoning / generator)
    assert set(inputs["models"]) == {"vlm", "reasoning", "generator"}
    # result block records the live outcome
    assert inputs["result"]["status"] == "partial"
    assert inputs["result"]["total_vlm_calls"] == 5
    assert inputs["result"]["vram_swaps"] == 7


# ---- BrandDna shape ------------------------------------------------------ #


def test_golden_brand_dna_shape(brand_dna) -> None:
    assert brand_dna["brand_name"] == "Ember & Oat"
    palette = brand_dna["palette"]
    assert isinstance(palette, list) and len(palette) == 5
    for swatch in palette:
        assert set(swatch) == {"name", "hex", "rank"}
        assert swatch["hex"].startswith("#") and len(swatch["hex"]) == 7
        assert swatch["rank"] in {"primary", "accent", "neutral"}
    # primary is Espresso #4A3728 (the dominant brand color)
    assert palette[0]["name"] == "Espresso"
    assert palette[0]["hex"] == "#4A3728"
    assert palette[0]["rank"] == "primary"
    for field in ("mood", "visual_keywords", "dos", "donts"):
        assert isinstance(brand_dna[field], list) and brand_dna[field]
    assert brand_dna["typography_class"] == "serif"
    assert set(brand_dna["typography_pairs"]) == {"headline", "body"}
    assert isinstance(brand_dna["personality"], str) and len(brand_dna["personality"]) > 80


# ---- KitManifest shape --------------------------------------------------- #


def test_golden_kit_manifest_shape(kit_manifest) -> None:
    assert kit_manifest["run_id"] == "golden-001"
    assert kit_manifest["brand_name"] == "Ember & Oat"
    # Golden run was partial (strict critic threshold 70; FLUX garbled wordmark text)
    assert kit_manifest["status"] == "partial"
    assert kit_manifest["brand_dna_ref"] == "brand_dna.json"
    assert kit_manifest["brand_guide"] == "brand_kit/brand_guide.md"
    assets = kit_manifest["assets"]
    assert isinstance(assets, list) and len(assets) == 2
    asset_ids = {a["id"] for a in assets}
    assert asset_ids == {"logo", "social_square"}
    for a in assets:
        assert set(a) >= {"id", "type", "path", "status", "final_score", "error"}
        assert a["status"] in {"approved", "failed"}
        assert isinstance(a["final_score"], int) and 0 <= a["final_score"] <= 100
    # both failed the strict critic (62 / 65, below threshold 70)
    assert all(a["status"] == "failed" for a in assets)
    assert {a["id"]: a["final_score"] for a in assets} == {
        "logo": 62,
        "social_square": 65,
    }


def test_golden_kit_manifest_optimization_stats(kit_manifest) -> None:
    stats = kit_manifest["optimization_stats"]
    # VRAM swap scheduler (CP-007) fired
    assert stats["vram_swaps"] == 7
    # VLM effort routing (CP-007): low for rechecks, medium for first-pass critique
    assert stats["critic_effort_low_count"] + stats["critic_effort_medium_count"] == 4
    assert stats["total_vlm_calls"] == 5
    assert stats["total_renders"] == 4
    # local-first reasoning routing (CP-013): all reasoning served by local Ollama
    assert stats["routing_local_count"] == 3
    assert stats["routing_nim_count"] == 0


# ---- cross-consistency --------------------------------------------------- #


def test_golden_palette_consistency(brand_dna, kit_manifest) -> None:
    dna_hexes = [s["hex"] for s in brand_dna["palette"]]
    assert kit_manifest["palette"] == dna_hexes
    assert kit_manifest["palette"] == [
        "#4A3728",
        "#C65D3B",
        "#F2E8D5",
        "#2D241B",
        "#A69B90",
    ]


def test_golden_brand_guide_is_markdown() -> None:
    guide = (GOLDEN / "golden-001_brand_guide.md").read_text(encoding="utf-8")
    assert guide.strip(), "brand guide must be non-empty"
    # markdown structure: at least one heading + the brand name + a palette section
    assert "#" in guide
    assert "Ember & Oat" in guide
    assert any(token in guide for token in ("#4A3728", "Palette", "palette"))


def test_golden_files_present() -> None:
    expected = [
        "golden-001_inputs.json",
        "golden-001_brand_dna.json",
        "golden-001_kit_manifest.json",
        "golden-001_brand_guide.md",
    ]
    for name in expected:
        assert (GOLDEN / name).is_file(), f"missing golden fixture: {name}"
