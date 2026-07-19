"""Schema tests — validate the design-doc examples and the token-hygiene/security guards."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.common.schemas import (
    AssetManifest,
    AssetSpec,
    BrandDna,
    CriticResult,
    KitManifest,
    OrchestratorEvent,
    RunInput,
)

DESIGN = Path(__file__).resolve().parents[1] / "references" / "design" / "02-data-contracts.md"


def _extract_json_blocks(text: str) -> dict[str, str]:
    """Map each ```json block to the ``## `` heading that precedes it."""
    blocks: dict[str, str] = {}
    current_heading: str | None = None
    in_block = False
    buf: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            current_heading = stripped[3:].strip().replace("`", "")
            continue
        if stripped == "```json":
            in_block = True
            buf = []
            continue
        if in_block and stripped == "```":
            in_block = False
            if current_heading is not None:
                blocks[current_heading] = "\n".join(buf)
            continue
        if in_block:
            buf.append(line)
    return blocks


@pytest.fixture(scope="module")
def blocks() -> dict[str, str]:
    return _extract_json_blocks(DESIGN.read_text())


def _block_named(blocks: dict[str, str], heading: str) -> str:
    try:
        return blocks[heading]
    except KeyError:
        raise AssertionError(f"no JSON block under heading {heading!r} in design doc") from None


def test_brand_dna_example_validates(blocks: dict[str, str]) -> None:
    BrandDna.model_validate_json(_block_named(blocks, "brand_dna.json (Brand Analyst output)"))


def test_asset_manifest_example_validates(blocks: dict[str, str]) -> None:
    AssetManifest.model_validate_json(
        _block_named(blocks, "asset_manifest.json (Art Director output)")
    )


def test_critic_result_example_validates(blocks: dict[str, str]) -> None:
    CriticResult.model_validate_json(
        _block_named(blocks, "critic_result.json (Critic output, per attempt)")
    )


def test_kit_manifest_example_validates(blocks: dict[str, str]) -> None:
    KitManifest.model_validate_json(
        _block_named(blocks, "kit_manifest.json (Assembler output — the Gallery contract)")
    )


def test_orchestrator_event_example_validates(blocks: dict[str, str]) -> None:
    raw = _block_named(blocks, "orchestrator_log.json (Model Orchestrator evidence trail)")
    data = json.loads(raw)
    ev = OrchestratorEvent.model_validate(data["events"][0])
    assert ev.action == "unload_ollama"


def test_run_input_example_validates(blocks: dict[str, str]) -> None:
    RunInput.model_validate_json(_block_named(blocks, "input.json (run input)"))


def test_flux_prompt_length_cap() -> None:
    with pytest.raises(ValidationError):
        AssetSpec(
            id="logo",
            type="logo",
            size=[1024, 1024],
            flux_prompt="x" * 601,
            seed=1,
        )


def test_size_vram_cap() -> None:
    with pytest.raises(ValidationError):
        AssetSpec(
            id="hero",
            type="hero_banner",
            size=[2048, 1024],
            flux_prompt="ok",
            seed=1,
        )


def test_run_id_regex_rejects_traversal() -> None:
    with pytest.raises(ValidationError):
        RunInput(run_id="../../etc", brand_name="x", brief="b", reference_images=["i"])


def test_critic_pass_alias() -> None:
    raw = {
        "run_id": "20260713-104200-a1b2",
        "asset_id": "logo",
        "attempt": 1,
        "png_path": "x.png",
        "pass": False,
        "score": 64,
        "palette_match": 0.62,
        "mood_match": 0.80,
        "legibility": 0.55,
        "on_brand": 0.70,
        "feedback": "fix palette",
    }
    cr = CriticResult.model_validate(raw)
    assert cr.pass_ is False
    assert cr.model_dump(by_alias=True)["pass"] is False


def test_palette_hex_enforced() -> None:
    with pytest.raises(ValidationError):
        BrandDna(
            brand_name="x",
            palette=[{"name": "bad", "hex": "nothex", "rank": "primary"}],
            mood=["warm"],
            typography_class="serif",
        )
