"""Generator agent — runs a ComfyUI FLUX (+PuLID) workflow per AssetSpec.

Single-flight on the GB10 (module-level lock), with CUDA-dirty auto-recovery
(restart comfyui-ctl.sh, wait for health, retry once). Workflow JSON is the API
format derived from the workshop's ``superhero_face_api.json``; the PuLID branch
(nodes 2-6) is pruned and the KSampler rewired to the raw checkpoint when
``uses_pulid`` is false.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import structlog

from src.common.aiofs import to_thread
from src.common.aiofs import write_bytes as aio_write_bytes
from src.common.comfyui import ComfyUIClient
from src.common.config import Settings, get_settings
from src.common.exceptions import ComfyUIError, CudaDirtyError
from src.common.runs import RunDir
from src.common.schemas import AssetSpec, RenderResult
from src.common.vram import free_vram_mib

__all__ = ["generate_asset", "build_workflow", "CUDA_DIRTY_MARKERS"]

_log = structlog.get_logger(__name__)

_WORKFLOW_PATH = Path(__file__).resolve().parent.parent / "comfyui" / "brand_workflow.json"
_PULID_NODES = ("2", "3", "4", "5", "6")
_KSAMPLER = "11"
_SAVEIMAGE = "13"
_POSITIVE = "7"
_NEGATIVE = "8"
_LATENT = "10"
_LOADIMAGE = "5"
_CHECKPOINT = "1"
_APPLY_PULID = "6"
_LORALOADER = "100"  # injected node id for the CP-014 LoRA adapter
_CFG = 1.0
_GUIDANCE = 3.5
_DEFAULT_STEPS = 24
_DEFAULT_MAX_WAIT_S = 180.0

CUDA_DIRTY_MARKERS = ("CUDA error", "illegal memory access", "invalid argument")

# Single-flight: ComfyUI renders one prompt at a time on the GB10.
_RENDER_LOCK = asyncio.Lock()

RestartFn = Callable[[], Awaitable[None]]


def _is_cuda_dirty(msg: str) -> bool:
    low = msg.lower()
    return any(m.lower() in low for m in CUDA_DIRTY_MARKERS)


def build_workflow(
    asset_spec: AssetSpec,
    attempt: int,
    steps: int,
    *,
    lora_adapter: str = "",
    lora_strength: float = 1.0,
) -> dict[str, Any]:
    """Build a ComfyUI API-format graph for one asset, pruning PuLID when unused.

    When ``lora_adapter`` (a ComfyUI lora filename) is set, a ``LoraLoader`` node is
    injected between the checkpoint and the model/clip consumers (CP-014 LoRA
    specialization). The non-LoRA path is unchanged when ``lora_adapter`` is empty.
    """
    wf = json.loads(_WORKFLOW_PATH.read_text(encoding="utf-8"))
    wf = {k: {"class_type": v["class_type"], "inputs": dict(v["inputs"])} for k, v in wf.items()}

    w, h = asset_spec.size
    wf[_POSITIVE]["inputs"]["text"] = asset_spec.flux_prompt
    wf[_NEGATIVE]["inputs"]["text"] = asset_spec.negative_prompt
    wf[_LATENT]["inputs"]["width"] = w
    wf[_LATENT]["inputs"]["height"] = h
    wf[_LATENT]["inputs"]["batch_size"] = 1
    wf[_KSAMPLER]["inputs"]["seed"] = asset_spec.seed
    wf[_KSAMPLER]["inputs"]["steps"] = steps
    wf[_SAVEIMAGE]["inputs"]["filename_prefix"] = f"{asset_spec.id}__v{attempt}"

    # CP-014: inject a LoraLoader between the checkpoint and the model/clip consumers.
    # LoraLoader outputs [model=0, clip=1]; consumers that referenced ["1", 0]/["1", 1]
    # are rewired to ["100", 0]/["100", 1]. The VAE (["1", 2]) is untouched by LoRA.
    if lora_adapter:
        wf[_LORALOADER] = {
            "class_type": "LoraLoader",
            "inputs": {
                "model": [_CHECKPOINT, 0],
                "clip": [_CHECKPOINT, 1],
                "lora_name": lora_adapter,
                "strength_model": lora_strength,
                "strength_clip": lora_strength,
            },
        }
        model_src: list[str | int] = [_LORALOADER, 0]
        clip_src: list[str | int] = [_LORALOADER, 1]
        wf[_POSITIVE]["inputs"]["clip"] = clip_src
        wf[_NEGATIVE]["inputs"]["clip"] = clip_src
    else:
        model_src = [_CHECKPOINT, 0]
        # clip stays as ["1", 1] from the base workflow for the non-LoRA path

    if asset_spec.uses_pulid:
        if not asset_spec.pulid_reference:
            raise ComfyUIError("uses_pulid=true but pulid_reference is unset")
        wf[_LOADIMAGE]["inputs"]["image"] = asset_spec.pulid_reference
        # ApplyPulidFlux takes the (possibly LoRA-applied) model; its model input is
        # rewired from ["1", 0] to the LoRA model output when LoRA is active.
        wf[_APPLY_PULID]["inputs"]["model"] = model_src
        # KSampler model comes from ApplyPulidFlux (["6", 0]) — unchanged
    else:
        for nid in _PULID_NODES:
            wf.pop(nid, None)
        wf[_KSAMPLER]["inputs"]["model"] = model_src  # raw or LoRA-applied checkpoint
    return wf


def _extract_output(entry: dict[str, Any]) -> dict[str, str]:
    outputs = entry.get("outputs") or {}
    node = outputs.get(_SAVEIMAGE) or {}
    images = node.get("images") or []
    if not images:
        raise ComfyUIError(f"no SaveImage output in history entry: {entry!r}")
    img = images[0]
    return {
        "filename": str(img["filename"]),
        "subfolder": str(img.get("subfolder", "")),
        "type": str(img.get("type", "output")),
    }


def _vram_free_mib() -> int | None:
    return free_vram_mib()


def _write_render_meta(run_dir: RunDir, asset_id: str, attempt: int, result: RenderResult) -> None:
    meta = result.model_dump(exclude={"png_path"})
    meta["png_path"] = result.png_path
    out = run_dir.path / "assets" / f"render_meta__{asset_id}__v{attempt}.json"
    out.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def _emit_media(abs_path: str) -> None:
    sys.stdout.write(f"MEDIA:{abs_path}\n")
    sys.stdout.flush()


async def _default_restart(settings: Settings) -> None:
    if not settings.comfyui_ctl_script:
        raise ComfyUIError("comfyui_ctl_script not configured; cannot restart ComfyUI")
    proc = await asyncio.create_subprocess_exec(
        "bash",
        settings.comfyui_ctl_script,
        "restart",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    await proc.wait()


async def _wait_health(cc: ComfyUIClient, timeout: float = 90.0) -> None:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        if await cc.health():
            return
        await asyncio.sleep(2.0)
    raise ComfyUIError("comfyui did not return to health after restart")


async def _render_once(
    asset_spec: AssetSpec,
    run_dir: RunDir,
    attempt: int,
    steps: int,
    settings: Settings,
    client: ComfyUIClient | None,
    max_wait_s: float,
) -> RenderResult:
    owns = client is None
    cc = client or ComfyUIClient(settings)
    t0 = time.perf_counter()
    try:
        wf = await to_thread(
            build_workflow,
            asset_spec,
            attempt,
            steps,
            lora_adapter=settings.lora_adapter,
            lora_strength=settings.lora_strength,
        )
        pid = await cc.submit(wf)
        try:
            entry = await cc.wait(pid, timeout=max_wait_s)
        except ComfyUIError as exc:
            if _is_cuda_dirty(str(exc)):
                raise CudaDirtyError(str(exc)) from exc
            raise
        out = _extract_output(entry)
        png = await cc.fetch_image(out["filename"], out["subfolder"], out["type"])
        out_path = run_dir.asset_path(asset_spec.id, attempt)
        await aio_write_bytes(out_path, png)
        latency = time.perf_counter() - t0
        result = RenderResult(
            asset_id=asset_spec.id,
            attempt=attempt,
            png_path=str(out_path),
            prompt_id=pid,
            seed=asset_spec.seed,
            steps=steps,
            cfg=_CFG,
            guidance=_GUIDANCE,
            uses_pulid=asset_spec.uses_pulid,
            latency_s=round(latency, 3),
            vram_free_mib=_vram_free_mib(),
        )
        await to_thread(_write_render_meta, run_dir, asset_spec.id, attempt, result)
        _emit_media(str(out_path))
        _log.info(
            "generator.render.done",
            asset_id=asset_spec.id,
            attempt=attempt,
            latency_s=result.latency_s,
            prompt_id=pid,
        )
        return result
    finally:
        if owns:
            await cc.aclose()


def _error_result(asset_spec: AssetSpec, attempt: int, steps: int, error: str) -> RenderResult:
    return RenderResult(
        asset_id=asset_spec.id,
        attempt=attempt,
        png_path="",
        prompt_id="",
        seed=asset_spec.seed,
        steps=steps,
        cfg=_CFG,
        guidance=_GUIDANCE,
        latency_s=0.0,
        error=error,
    )


async def generate_asset(
    asset_spec: AssetSpec,
    run_dir: RunDir,
    attempt: int,
    *,
    settings: Settings | None = None,
    client: ComfyUIClient | None = None,
    steps: int | None = None,
    max_wait_s: float = _DEFAULT_MAX_WAIT_S,
    restart_fn: RestartFn | None = None,
) -> RenderResult:
    """Render one asset. Single-flight; auto-restarts ComfyUI once on a CUDA-dirty error.

    On any non-recoverable error, returns a ``RenderResult`` with ``error`` set and an
    empty ``png_path`` (does not raise) so the Art Director loop can mark the asset
    failed and continue.
    """
    s = settings or get_settings()
    n_steps = steps or asset_spec.steps or _DEFAULT_STEPS
    async with _RENDER_LOCK:
        try:
            return await _render_once(asset_spec, run_dir, attempt, n_steps, s, client, max_wait_s)
        except CudaDirtyError as exc:
            _log.warning("generator.cuda_dirty", asset_id=asset_spec.id, error=str(exc)[:160])
            restart = restart_fn or (lambda: _default_restart(s))
            try:
                await restart()
                cc = client or ComfyUIClient(s)
                try:
                    await _wait_health(cc)
                finally:
                    if client is None:
                        await cc.aclose()
            except ComfyUIError as rerr:
                return _error_result(asset_spec, attempt, n_steps, f"restart failed: {rerr}")
            try:
                return await _render_once(
                    asset_spec, run_dir, attempt, n_steps, s, client, max_wait_s
                )
            except (CudaDirtyError, ComfyUIError) as exc2:
                return _error_result(
                    asset_spec, attempt, n_steps, f"cuda dirty after restart: {exc2}"
                )
        except ComfyUIError as exc:
            return _error_result(asset_spec, attempt, n_steps, f"comfyui error: {exc}")
