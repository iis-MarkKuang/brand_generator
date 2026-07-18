"""Cross-asset consistency checker (CP-017).

After all assets are generated, the VLM compares them side-by-side for brand
coherence: palette consistency, typography consistency, mood consistency, and
composition consistency. Returns a :class:`ConsistencyMatrix` that the
orchestrator embeds in the final manifest and the gallery renders as a heatmap.

This showcases the VLM's multi-image reasoning — not just scoring a single
image, but comparing several generated assets against each other and the brand
DNA simultaneously.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import structlog
from pydantic import ValidationError

from src.common.aiofs import write_text as aio_write_text
from src.common.config import Settings, get_settings
from src.common.exceptions import VlmJsonError
from src.common.runs import RunDir
from src.common.schemas import BrandDna, ConsistencyDimension, ConsistencyMatrix
from src.common.stepfun import StepfunClient, bytes_to_data_url, resize_for_vlm

__all__ = ["check_consistency"]

_log = structlog.get_logger(__name__)

_SYSTEM_PROMPT = (
    "You are a brand consistency auditor. You will be shown multiple brand "
    "assets (logo, hero banner, social square, etc.) that were generated for "
    "the same brand. Compare them against each other and the brand DNA for "
    "cross-asset consistency.\n\n"
    "Score each dimension on a 0.0–1.0 scale:\n"
    "- palette: Do the colors across all assets match the brand palette?\n"
    "- typography: Is the typography style consistent across assets?\n"
    "- mood: Is the visual mood/atmosphere coherent?\n"
    "- composition: Are the layout/composition choices harmonious?\n\n"
    "Return ONLY a JSON object:\n"
    "{\n"
    '  "overall_score": 0.0–1.0,\n'
    '  "dimensions": [\n'
    '    {"dimension": "palette", "score": 0.0–1.0, "notes": "..."},\n'
    '    {"dimension": "typography", "score": 0.0–1.0, "notes": "..."},\n'
    '    {"dimension": "mood", "score": 0.0–1.0, "notes": "..."},\n'
    '    {"dimension": "composition", "score": 0.0–1.0, "notes": "..."}\n'
    "  ],\n"
    '  "summary": "one-line overall assessment"\n'
    "}"
)


def _build_multi_image_messages(
    dna: BrandDna,
    asset_images: list[tuple[str, str]],  # (asset_id, data_url)
) -> list[dict[str, Any]]:
    palette = ", ".join(c.hex for c in dna.palette)
    user_text = (
        f"Brand DNA palette: {palette}\n"
        f"Brand mood: {', '.join(dna.mood[:3])}\n"
        f"Typography class: {dna.typography_class}\n\n"
        f"You are shown {len(asset_images)} brand assets. "
        "Compare them for cross-asset consistency."
    )
    content: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
    for aid, url in asset_images:
        content.append({"type": "text", "text": f"Asset: {aid}"})
        content.append({"type": "image_url", "image_url": {"url": url}})
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]


def _build_matrix(data: dict[str, Any], asset_ids: list[str]) -> ConsistencyMatrix:
    dims = []
    for d in data.get("dimensions", []):
        dims.append(
            ConsistencyDimension(
                dimension=str(d.get("dimension", "")),
                score=float(d.get("score", 0.0)),
                notes=str(d.get("notes", "")),
            )
        )
    return ConsistencyMatrix(
        overall_score=float(data.get("overall_score", 0.0)),
        dimensions=dims,
        summary=str(data.get("summary", "")),
        asset_ids=asset_ids,
    )


def _fallback_matrix(asset_ids: list[str], err: str) -> ConsistencyMatrix:
    return ConsistencyMatrix(
        overall_score=0.0,
        dimensions=[],
        summary=f"consistency check failed: {err[:120]}",
        asset_ids=asset_ids,
    )


async def check_consistency(
    approved_assets: list[tuple[str, str | Path]],  # (asset_id, png_path)
    brand_dna: BrandDna,
    *,
    run_dir: RunDir,
    settings: Settings | None = None,
    client: StepfunClient | None = None,
) -> ConsistencyMatrix:
    """VLM cross-asset consistency check. Never raises.

    Sends all approved asset images to the VLM in one call and asks it to
    compare them for brand coherence. Returns a ConsistencyMatrix; on any
    failure, returns a fallback matrix with a note (does not crash the run).
    """
    if len(approved_assets) < 2:
        return ConsistencyMatrix(
            overall_score=1.0,
            dimensions=[],
            summary="single asset — no cross-asset comparison needed",
            asset_ids=[a[0] for a in approved_assets],
        )

    s = settings or get_settings()
    log = _log.bind(agent="consistency", run_id=run_dir.run_id)

    owns_client = client is None
    sc = client or StepfunClient(s)
    try:
        asset_images: list[tuple[str, str]] = []
        for aid, png in approved_assets:
            try:
                data_url = bytes_to_data_url(resize_for_vlm(Path(png), max_side=768), "image/png")
                asset_images.append((aid, data_url))
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "consistency.image_skip", asset_id=aid, error=str(exc)[:120], exc_info=True
                )

        if len(asset_images) < 2:
            return _fallback_matrix([a[0] for a in approved_assets], "not enough loadable images")

        messages = _build_multi_image_messages(brand_dna, asset_images)
        asset_ids = [a[0] for a in asset_images]

        data: dict[str, Any] | None = None
        try:
            data = await sc.chat_vlm(messages, reasoning_effort="medium", image_detail="high")
            matrix = _build_matrix(data, asset_ids)
        except (ValidationError, VlmJsonError, KeyError, ValueError, TypeError) as exc:
            log.warning("consistency.repair", error=str(exc)[:160])
            repair = messages + [
                {
                    "role": "assistant",
                    "content": json.dumps(data) if isinstance(data, dict) else "(invalid)",
                },
                {
                    "role": "user",
                    "content": (
                        f"The JSON was invalid: {exc}. "
                        "Return ONLY the corrected JSON with overall_score, dimensions, summary."
                    ),
                },
            ]
            try:
                data2 = await sc.chat_vlm(repair, reasoning_effort="low", image_detail="low")
                matrix = _build_matrix(data2, asset_ids)
            except Exception as exc2:  # noqa: BLE001
                matrix = _fallback_matrix(asset_ids, str(exc2)[:120])
    finally:
        if owns_client:
            await sc.aclose()

    # Persist
    out = run_dir.path / "consistency_matrix.json"
    await aio_write_text(out, matrix.model_dump_json(indent=2))

    log.info("consistency.done", overall=matrix.overall_score, dims=len(matrix.dimensions))
    return matrix
