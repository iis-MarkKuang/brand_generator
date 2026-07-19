"""Art Director agent — local Nemotron planning + prompt rewrite.

The Art Director is the *delegating* agent. In this packet it exposes two standalone
functions — ``plan_assets`` (one-shot kit planning) and ``rewrite_prompt`` (per-asset
critique-driven rewrite) — plus the tool schemas the loop (CP-008) will bind. It runs
on the local Ollama reasoning model with ``think=False`` (workshop quirk) so the answer
lands in ``message.content``. Planning is cached per ``(brand_dna_hash, asset_types)``
so iterate/replay runs skip the slow LLM call (T9). Seeds are deterministic per
``(base_seed, brand_dna_hash, asset_id)`` for reproducible renders.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import structlog
from pydantic import ValidationError

from src.common.aiofs import (
    exists as aio_exists,
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
from src.common.ollama import OllamaClient
from src.common.router import ReasonClient
from src.common.runs import RunDir
from src.common.schemas import AssetManifest, AssetSpec, AssetType, BrandDna

__all__ = ["plan_assets", "rewrite_prompt", "DIRECTOR_TOOLS", "brand_hash"]

_log = structlog.get_logger(__name__)

_PROMPT_PATH = Path(__file__).parent / "prompts" / "director.md"
_DEFAULT_CACHE_DIR = Path("cache/asset_manifest")

_DEFAULT_SIZE: dict[str, list[int]] = {
    "logo": [1024, 1024],
    "social_square": [1024, 1024],
    "product_mockup": [1024, 1024],
    "hero_banner": [1344, 768],
    "business_card": [1024, 576],
}

_HEX_RE = re.compile(r"#[0-9A-Fa-f]{6}")
_JSON_OBJ_RE = re.compile(r"\{.*\}", re.S)


# --------------------------------------------------------------------------- #
# Tool schemas (bound to implementations in CP-005/006/007/008)
# --------------------------------------------------------------------------- #
DIRECTOR_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "analyze_brand",
            "description": "Extract brand DNA from a brief + reference image (Stepfun VLM).",
            "parameters": {
                "type": "object",
                "properties": {
                    "brief": {"type": "string"},
                    "image": {"type": "string", "description": "path to reference image"},
                    "brand_name": {"type": "string"},
                },
                "required": ["brief", "image", "brand_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_asset",
            "description": "Render one asset PNG via ComfyUI FLUX (+PuLID).",
            "parameters": {
                "type": "object",
                "properties": {"asset_spec": {"type": "object"}},
                "required": ["asset_spec"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "critic_asset",
            "description": "Score a rendered PNG against the brand DNA (Stepfun VLM).",
            "parameters": {
                "type": "object",
                "properties": {
                    "png_path": {"type": "string"},
                    "asset_spec": {"type": "object"},
                    "brand_dna": {"type": "object"},
                },
                "required": ["png_path", "asset_spec", "brand_dna"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_vram",
            "description": "Ask the Model Orchestrator to free/reserve unified memory for a backend.",
            "parameters": {
                "type": "object",
                "properties": {"target": {"type": "string", "enum": ["ollama", "comfyui"]}},
                "required": ["target"],
            },
        },
    },
]


def brand_hash(dna: BrandDna) -> str:
    return hashlib.sha1(dna.model_dump_json().encode("utf-8"), usedforsecurity=False).hexdigest()[
        :16
    ]


def _plan_cache_key(bd_hash: str, asset_types: Sequence[AssetType]) -> str:
    return hashlib.sha1(
        f"{bd_hash}:{','.join(asset_types)}".encode(), usedforsecurity=False
    ).hexdigest()


def _seed_for(base_seed: int, bd_hash: str, asset_id: str) -> int:
    h = hashlib.sha1(
        f"{base_seed}:{bd_hash}:{asset_id}".encode(), usedforsecurity=False
    ).hexdigest()
    return int(h[:8], 16) % 1_000_000


def _load_system_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _parse_json_object(text: str) -> dict[str, Any]:
    try:
        v = json.loads(text)
    except json.JSONDecodeError:
        m = _JSON_OBJ_RE.search(text)
        if not m:
            raise
        v = json.loads(m.group(0))
    if not isinstance(v, dict):
        raise ValueError(f"expected JSON object, got {type(v).__name__}")
    return v


def _build_plan_messages(
    dna: BrandDna,
    asset_types: Sequence[AssetType],
    image_roles: dict[int, str] | None = None,
    num_images: int = 1,
) -> list[dict[str, Any]]:
    palette = ", ".join(f"{c.hex} ({c.name})" for c in dna.palette)
    user = (
        "Brand DNA:\n"
        f"{dna.model_dump_json(indent=2)}\n\n"
        f"Palette hex tokens to reuse everywhere: {palette}\n"
        f"Requested asset types (one AssetSpec each, in this order): {list(asset_types)}\n\n"
    )
    if num_images > 1 and image_roles:
        roles_desc = "; ".join(f"@{k}: {v}" for k, v in sorted(image_roles.items()))
        user += (
            f"The user uploaded {num_images} reference images with these roles: {roles_desc}\n"
            "For each asset, set `reference_index` to the 1-based image number that best "
            "matches the user's intent for that asset (from the @N tokens in the brief). "
            "If no specific image is relevant, omit `reference_index`.\n\n"
        )
    user += "Return the asset manifest JSON."
    return [
        {"role": "system", "content": _load_system_prompt()},
        {"role": "user", "content": user},
    ]


def _build_asset(spec_dict: dict[str, Any], atype: str, base_seed: int, bd_hash: str) -> AssetSpec:
    size = spec_dict.get("size") or _DEFAULT_SIZE[atype]
    built: dict[str, Any] = {
        "id": atype,
        "type": atype,
        "size": size,
        "flux_prompt": spec_dict.get("flux_prompt", ""),
        "negative_prompt": spec_dict.get("negative_prompt", ""),
        "composition": spec_dict.get("composition", ""),
        "uses_pulid": bool(spec_dict.get("uses_pulid", False)),
        "seed": _seed_for(base_seed, bd_hash, atype),
    }
    if spec_dict.get("pulid_reference"):
        built["pulid_reference"] = spec_dict["pulid_reference"]
    if spec_dict.get("reference_index") is not None:
        built["reference_index"] = int(spec_dict["reference_index"])
    spec = AssetSpec.model_validate(built)
    if len(_HEX_RE.findall(spec.flux_prompt)) < 2:
        raise ValueError(f"flux_prompt for {atype} must include >=2 palette hex tokens")
    return spec


def _persist(run_dir: RunDir, manifest: AssetManifest) -> None:
    run_dir.path.mkdir(parents=True, exist_ok=True)
    run_dir.manifest_path().write_text(manifest.model_dump_json(indent=2), encoding="utf-8")


async def plan_assets(
    brand_dna: BrandDna,
    asset_types: Sequence[AssetType],
    *,
    run_dir: RunDir,
    base_seed: int = 0,
    settings: Settings | None = None,
    client: ReasonClient | None = None,
    cache_dir: str | Path | None = None,
    image_roles: dict[int, str] | None = None,
    num_images: int = 1,
) -> AssetManifest:
    """Plan a coherent `AssetManifest` (one AssetSpec per requested type).

    Cached per ``(brand_dna_hash, asset_types)``; on a hit the Ollama call is skipped
    and the manifest is re-stamped with the current ``run_id``. On a validation
    failure, one repair retry describing the errors, then raise. ``client`` may be
    an ``OllamaClient`` or a ``ReasonRouter`` (CP-013 local<->cloud routing).

    CP-020: when ``num_images > 1`` and ``image_roles`` is provided, the planning
    prompt describes each image's role so the LLM can set ``reference_index`` per
    asset.
    """
    log = _log.bind(agent="art_director", run_id=run_dir.run_id, n_types=len(asset_types))
    bd_hash = brand_hash(brand_dna)
    cdir = Path(cache_dir) if cache_dir is not None else _DEFAULT_CACHE_DIR
    cache_file = cdir / f"{_plan_cache_key(bd_hash, asset_types)}.json"

    if await aio_exists(cache_file):
        cached = AssetManifest.model_validate_json(await aio_read_text(cache_file))
        manifest = cached.model_copy(update={"run_id": run_dir.run_id})
        await to_thread(_persist, run_dir, manifest)
        log.info("art_director.plan.done", cache_hit=True, assets=len(manifest.assets))
        return manifest

    s = settings or get_settings()
    owns_client = client is None
    oc: ReasonClient = client or OllamaClient(s)
    try:
        messages = await to_thread(
            _build_plan_messages, brand_dna, asset_types, image_roles, num_images
        )
        manifest = await _plan_with_repair(
            oc,
            s.ollama_reasoning_model,
            messages,
            asset_types,
            run_dir.run_id,
            base_seed,
            bd_hash,
            log,
        )
    finally:
        if owns_client:
            await oc.aclose()

    await to_thread(_persist, run_dir, manifest)
    cdir.mkdir(parents=True, exist_ok=True)
    await aio_write_text(cache_file, manifest.model_dump_json(indent=2))
    log.info("art_director.plan.done", cache_hit=False, assets=len(manifest.assets))
    return manifest


async def _plan_with_repair(
    oc: ReasonClient,
    model: str,
    messages: list[dict[str, Any]],
    asset_types: Sequence[AssetType],
    run_id: str,
    base_seed: int,
    bd_hash: str,
    log: structlog.stdlib.BoundLogger,
) -> AssetManifest:
    content = await oc.chat(model, messages, think=False)
    try:
        return _assemble_manifest(content, asset_types, run_id, base_seed, bd_hash)
    except (ValidationError, ValueError, KeyError, json.JSONDecodeError) as exc:
        log.warning("art_director.plan.repair", error=str(exc)[:200])
        repair = messages + [
            {"role": "assistant", "content": content},
            {
                "role": "user",
                "content": (
                    "The manifest you returned was invalid: "
                    f"{exc}. Return ONLY the corrected JSON manifest."
                ),
            },
        ]
        content2 = await oc.chat(model, repair, think=False)
        return _assemble_manifest(content2, asset_types, run_id, base_seed, bd_hash)


def _assemble_manifest(
    content: str,
    asset_types: Sequence[AssetType],
    run_id: str,
    base_seed: int,
    bd_hash: str,
) -> AssetManifest:
    data = _parse_json_object(content)
    entries = data.get("assets")
    if not isinstance(entries, list) or len(entries) < len(asset_types):
        raise ValueError(f"expected {len(asset_types)} assets, got {type(entries).__name__}")
    assets = [
        _build_asset(entries[i], atype, base_seed, bd_hash) for i, atype in enumerate(asset_types)
    ]
    return AssetManifest(run_id=run_id, assets=assets)


async def rewrite_prompt(
    asset_spec: AssetSpec,
    critic_feedback: str,
    *,
    settings: Settings | None = None,
    client: ReasonClient | None = None,
) -> AssetSpec:
    """Rewrite one asset's FLUX prompt in response to critic feedback (text-only)."""
    log = _log.bind(agent="art_director", asset_id=asset_spec.id)
    s = settings or get_settings()
    owns_client = client is None
    oc: ReasonClient = client or OllamaClient(s)
    try:
        user = (
            "Current asset spec:\n"
            f"{asset_spec.model_dump_json(indent=2)}\n\n"
            f"Critic feedback to address: {critic_feedback}\n\n"
            "Return ONLY JSON: "
            '{"flux_prompt": "<=600 chars, keep >=2 palette hex tokens, address the feedback>", '
            '"negative_prompt": "<string>"}.'
        )
        messages = [
            {"role": "system", "content": await to_thread(_load_system_prompt)},
            {"role": "user", "content": user},
        ]
        content = await oc.chat(s.ollama_reasoning_model, messages, think=False)
        data = _parse_json_object(content)
        update = {
            "flux_prompt": str(data.get("flux_prompt", asset_spec.flux_prompt)),
            "negative_prompt": str(data.get("negative_prompt", asset_spec.negative_prompt)),
        }
        new_spec = asset_spec.model_copy(update=update)
        # Re-validate the prompt constraints.
        AssetSpec.model_validate(new_spec.model_dump())
        log.info("art_director.rewrite.done", asset_id=asset_spec.id)
        return new_spec
    finally:
        if owns_client:
            await oc.aclose()
