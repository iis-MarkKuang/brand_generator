"""Critic agent — Stepfun VLM review of a rendered asset against the brand DNA.

Closes the generate→critique→refine loop. Returns a ``CriticResult`` (pass/fail +
sub-scores + actionable feedback). Effort/detail step down on re-checks
(``attempt >= 2``) for token economy (T2/T3). On a parse/schema failure, one repair
retry, then a structured ``critic_failed`` result — never crashes the run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import structlog
from pydantic import ValidationError

from src.common.config import Settings, get_settings
from src.common.exceptions import VlmJsonError
from src.common.runs import RunDir
from src.common.schemas import AssetSpec, BrandDna, CriticResult
from src.common.stepfun import StepfunClient, bytes_to_data_url, resize_for_vlm

__all__ = ["critic_asset"]

_log = structlog.get_logger(__name__)
_PROMPT_PATH = Path(__file__).parent / "prompts" / "critic.md"
_FALLBACK_FEEDBACK = "Asset failed brand-fit review; revise palette hex and wordmark legibility."


def _load_system_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _build_messages(dna: BrandDna, spec: AssetSpec, image_data_url: str) -> list[dict[str, Any]]:
    palette = ", ".join(c.hex for c in dna.palette)
    user = (
        "Brand DNA:\n"
        f"{dna.model_dump_json(indent=2)}\n\n"
        f"DNA palette hex tokens to match: {palette}\n\n"
        f"Asset spec:\n{spec.model_dump_json(indent=2)}\n\n"
        "Score the rendered asset (image attached) against this brand DNA."
    )
    return [
        {"role": "system", "content": _load_system_prompt()},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ],
        },
    ]


def _build_result(
    data: dict[str, Any],
    run_dir: RunDir,
    spec: AssetSpec,
    attempt: int,
    png_path: str,
    threshold: int,
) -> CriticResult:
    score = int(data["score"])
    pass_ = score >= threshold
    feedback = str(data.get("feedback", "")).strip()
    if not pass_ and not feedback:
        feedback = _FALLBACK_FEEDBACK
    return CriticResult.model_validate(
        {
            "run_id": run_dir.run_id,
            "asset_id": spec.id,
            "attempt": attempt,
            "png_path": png_path,
            "pass": pass_,
            "score": score,
            "palette_match": float(data["palette_match"]),
            "mood_match": float(data["mood_match"]),
            "legibility": float(data["legibility"]),
            "on_brand": float(data["on_brand"]),
            "feedback": feedback,
        }
    )


def _failed_result(
    run_dir: RunDir, spec: AssetSpec, attempt: int, png_path: str, err: str
) -> CriticResult:
    return CriticResult.model_validate(
        {
            "run_id": run_dir.run_id,
            "asset_id": spec.id,
            "attempt": attempt,
            "png_path": png_path,
            "pass": False,
            "score": 0,
            "palette_match": 0.0,
            "mood_match": 0.0,
            "legibility": 0.0,
            "on_brand": 0.0,
            "feedback": f"critic_failed: {err}",
        }
    )


def _persist(run_dir: RunDir, spec: AssetSpec, attempt: int, result: CriticResult) -> None:
    run_dir.path.mkdir(parents=True, exist_ok=True)
    run_dir.critic_path(spec.id, attempt).write_text(
        result.model_dump_json(by_alias=True, indent=2), encoding="utf-8"
    )


async def critic_asset(
    png_path: str | Path,
    asset_spec: AssetSpec,
    brand_dna: BrandDna,
    *,
    run_dir: RunDir,
    attempt: int = 1,
    settings: Settings | None = None,
    client: StepfunClient | None = None,
) -> CriticResult:
    """Score one rendered asset against the brand DNA. Never raises."""
    s = settings or get_settings()
    detail = s.vlm_image_detail_first if attempt < 2 else s.vlm_image_detail_recheck
    effort = "medium" if attempt < 2 else "low"
    png_str = str(png_path)
    log = _log.bind(agent="critic", run_id=run_dir.run_id, asset_id=asset_spec.id, attempt=attempt)

    owns_client = client is None
    sc = client or StepfunClient(s)
    try:
        data_url = bytes_to_data_url(resize_for_vlm(Path(png_path), max_side=1024), "image/png")
        messages = _build_messages(brand_dna, asset_spec, data_url)
        data: dict[str, Any] | None = None
        try:
            data = await sc.chat_vlm(messages, reasoning_effort=effort, image_detail=detail)
            result = _build_result(
                data, run_dir, asset_spec, attempt, png_str, s.critic_pass_threshold
            )
        except (ValidationError, VlmJsonError, KeyError, ValueError) as exc:
            log.warning("critic.repair", error=str(exc)[:160])
            repair = messages + [
                {"role": "assistant", "content": json.dumps(data) if data else "(no valid JSON)"},
                {
                    "role": "user",
                    "content": (
                        f"The JSON you returned was invalid: {exc}. "
                        "Return ONLY the corrected JSON object with score/palette_match/"
                        "mood_match/legibility/on_brand/feedback."
                    ),
                },
            ]
            try:
                data2 = await sc.chat_vlm(repair, reasoning_effort=effort, image_detail=detail)
                result = _build_result(
                    data2, run_dir, asset_spec, attempt, png_str, s.critic_pass_threshold
                )
            except Exception as exc2:  # structured failure — never crash the run
                result = _failed_result(run_dir, asset_spec, attempt, png_str, str(exc2)[:160])
    finally:
        if owns_client:
            await sc.aclose()

    _persist(run_dir, asset_spec, attempt, result)
    log.info("critic.done", pass_=result.pass_, score=result.score, effort=effort, detail=detail)
    return result
