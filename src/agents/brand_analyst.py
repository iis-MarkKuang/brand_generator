"""Brand Analyst agent — Stepfun VLM extraction of `BrandDna` from brief + image.

Stage 1 of the pipeline. Caches DNA keyed by `sha1(brief + image_bytes)` so repeat
analyses (same brief + reference) skip the VLM entirely (optimization O4). Always
writes a validated `brand_dna.json` into the run directory for downstream agents.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import structlog
from pydantic import ValidationError

from src.common.aiofs import (
    exists as aio_exists,
)
from src.common.aiofs import (
    read_bytes as aio_read_bytes,
)
from src.common.aiofs import (
    read_text as aio_read_text,
)
from src.common.aiofs import (
    to_thread,
)
from src.common.aiofs import (
    write_text as aio_write_text,
)
from src.common.config import Settings, get_settings
from src.common.runs import RunDir
from src.common.schemas import BrandDna
from src.common.stepfun import StepfunClient, bytes_to_data_url, resize_for_vlm

__all__ = ["analyze_brand", "brand_dna_cache_key"]

_log = structlog.get_logger(__name__)

_PROMPT_PATH = Path(__file__).parent / "prompts" / "analyst.md"
_DEFAULT_CACHE_DIR = Path("cache/brand_dna")


def _load_system_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def brand_dna_cache_key(brief: str, image_bytes: bytes) -> str:
    return hashlib.sha1(brief.encode("utf-8") + image_bytes, usedforsecurity=False).hexdigest()


def _build_messages(brief: str, brand_name: str, image_data_url: str) -> list[dict[str, Any]]:
    user_text = (
        f"Brand brief:\n{brief}\n\n"
        f"Brand name: {brand_name}\n\n"
        "Analyze the reference image and return the brand DNA JSON."
    )
    return [
        {"role": "system", "content": _load_system_prompt()},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ],
        },
    ]


async def analyze_brand(
    brief: str,
    image: str | Path,
    brand_name: str,
    *,
    run_dir: RunDir,
    settings: Settings | None = None,
    client: StepfunClient | None = None,
    cache_dir: str | Path | None = None,
) -> BrandDna:
    """Extract a validated `BrandDna` for the given brief + reference image.

    Caches by `sha1(brief + image_bytes)`; on a hit the VLM is not called. On a
    schema-validation failure, performs one repair retry describing the invalid
    fields, then raises `ValidationError`.
    """
    log = _log.bind(agent="brand_analyst", run_id=run_dir.run_id, brand_name=brand_name)
    image_path = Path(image)
    image_bytes = await aio_read_bytes(image_path)
    key = brand_dna_cache_key(brief, image_bytes)
    cdir = Path(cache_dir) if cache_dir is not None else _DEFAULT_CACHE_DIR
    cache_file = cdir / f"{key}.json"

    # --- Cache hit (O4) ---
    if await aio_exists(cache_file):
        dna = BrandDna.model_validate_json(await aio_read_text(cache_file))
        await to_thread(_persist, run_dir, dna)
        log.info("brand_analyst.done", cache_hit=True, palette=len(dna.palette))
        return dna

    # --- Cache miss: call the VLM ---
    owns_client = client is None
    sc = client or StepfunClient(settings or get_settings())
    try:
        data_url = bytes_to_data_url(resize_for_vlm(image_path, max_side=1024), "image/png")
        messages = await to_thread(_build_messages, brief, brand_name, data_url)

        data = await sc.chat_vlm(messages, reasoning_effort="high", image_detail="high")
        data["brand_name"] = brand_name  # guarantee consistency with the caller
        try:
            dna = BrandDna.model_validate(data)
        except ValidationError as exc:
            log.warning("brand_analyst.schema_repair", errors=_summarize(exc))
            repair = messages + [
                {"role": "assistant", "content": json.dumps(data)},
                {
                    "role": "user",
                    "content": (
                        "The JSON you returned failed schema validation with these errors: "
                        f"{_summarize(exc)}. Return ONLY the corrected JSON object."
                    ),
                },
            ]
            data2 = await sc.chat_vlm(repair, reasoning_effort="high", image_detail="high")
            data2["brand_name"] = brand_name
            dna = BrandDna.model_validate(data2)  # raises if still invalid
    finally:
        if owns_client:
            await sc.aclose()

    await to_thread(_persist, run_dir, dna)
    cdir.mkdir(parents=True, exist_ok=True)
    await aio_write_text(cache_file, dna.model_dump_json(indent=2))
    log.info(
        "brand_analyst.done",
        cache_hit=False,
        palette=len(dna.palette),
        mood=len(dna.mood),
        typography_class=dna.typography_class,
    )
    return dna


def _persist(run_dir: RunDir, dna: BrandDna) -> None:
    run_dir.path.mkdir(parents=True, exist_ok=True)
    run_dir.brand_dna_path().write_text(dna.model_dump_json(indent=2), encoding="utf-8")


def _summarize(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()
    )
