"""Master orchestrator loop — wires the agents into the end-to-end StyleForge pipeline.

``run_pipeline`` drives: analyze_brand → plan_assets → (per asset: request_vram→
generate_asset → critic_asset → rewrite_prompt on fail) → assemble_kit. It enforces the
token/runtime caps (MAX_TOTAL_VLM_CALLS, MAX_TOTAL_RENDERS, RUN_TIMEOUT_S), per-asset
retry bounds, cooperative cancellation, and partial-kit resilience — a single asset
failure never aborts the run. Optimization stats are collected for the kit manifest.
"""

from __future__ import annotations

import asyncio
import contextlib
import shutil
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import structlog

from src.agents.art_director import plan_assets, rewrite_prompt
from src.agents.assembler import assemble_kit
from src.agents.brand_analyst import analyze_brand, brand_dna_cache_key
from src.agents.critic import critic_asset
from src.agents.generator import generate_asset
from src.common.comfyui import ComfyUIClient
from src.common.config import Settings, get_settings
from src.common.nvidia_nim import NimClient
from src.common.ollama import OllamaClient
from src.common.router import ReasonRouter
from src.common.runs import RunDir
from src.common.schemas import (
    AssetManifest,
    AssetSpec,
    BrandDna,
    KitAsset,
    OptimizationStats,
    RunInput,
)
from src.common.stepfun import StepfunClient
from src.optimizer.model_orchestrator import ModelOrchestrator, effort_for

__all__ = ["run_pipeline"]

_log = structlog.get_logger(__name__)

AnalyzeFn = Callable[..., Awaitable[BrandDna]]
PlanFn = Callable[..., Awaitable[AssetManifest]]
GenerateFn = Callable[..., Awaitable[Any]]
CriticFn = Callable[..., Awaitable[Any]]
RewriteFn = Callable[..., Awaitable[AssetSpec]]


def _check_cache_hit(brief: str, image: str | Path) -> bool:
    try:
        key = brand_dna_cache_key(brief, Path(image).read_bytes())
        return (Path("cache/brand_dna") / f"{key}.json").exists()
    except OSError:
        return False


def _bump_routing_stats(router: ReasonRouter, stats: OptimizationStats) -> None:
    """Count the backend that actually served the last reasoning call (CP-013)."""
    if not router.decisions:
        return
    last = router.decisions[-1]
    if last["backend"] == "nim":
        stats.routing_nim_count += 1
    else:
        stats.routing_local_count += 1


async def run_pipeline(
    run_input: RunInput,
    *,
    settings: Settings | None = None,
    stepfun_client: StepfunClient | None = None,
    ollama_client: OllamaClient | None = None,
    comfyui_client: ComfyUIClient | None = None,
    orchestrator: ModelOrchestrator | None = None,
    cancel_event: asyncio.Event | None = None,
    analyze_fn: AnalyzeFn | None = None,
    plan_fn: PlanFn | None = None,
    generate_fn: GenerateFn | None = None,
    critic_fn: CriticFn | None = None,
    rewrite_fn: RewriteFn | None = None,
) -> Any:
    """Run the full StyleForge pipeline. Returns a validated ``KitManifest``."""
    s = settings or get_settings()
    run_dir = RunDir(s.runs_root, run_input.run_id).ensure()
    log = _log.bind(run_id=run_dir.run_id, brand=run_input.brand_name)
    t0 = time.perf_counter()

    owns_stepfun = stepfun_client is None
    owns_ollama = ollama_client is None
    owns_comfyui = comfyui_client is None
    owns_nim = True  # CP-013 router owns the NIM client (not injectable yet)
    sc = stepfun_client or StepfunClient(s)
    oc = ollama_client or OllamaClient(s)
    cc = comfyui_client or ComfyUIClient(s)
    nim = NimClient(s)
    orch = orchestrator or ModelOrchestrator(run_dir, settings=s, ollama=oc, comfyui=cc)
    router = ReasonRouter(s, ollama=oc, nim=nim, on_routing=orch.record_routing)

    analyze = analyze_fn or analyze_brand
    plan = plan_fn or plan_assets
    generate = generate_fn or generate_asset
    critic = critic_fn or critic_asset
    rewrite = rewrite_fn or rewrite_prompt

    # Provenance: copy the reference image into the run's input dir (best-effort).
    with contextlib.suppress(OSError):
        shutil.copyfile(run_input.reference_image, run_dir.input_dir / "reference.png")

    stats = OptimizationStats()
    kit_assets: list[KitAsset] = []
    dna_cache_hit = _check_cache_hit(run_input.brief, run_input.reference_image)
    stats.brand_dna_cache_hit = dna_cache_hit
    dna: BrandDna | None = None
    manifest: AssetManifest | None = None

    try:
        # 1 — Brand Analyst (cloud VLM; no local VRAM swap needed).
        dna = await analyze(
            run_input.brief,
            run_input.reference_image,
            run_input.brand_name,
            run_dir=run_dir,
            settings=s,
            client=sc,
        )
        stats.total_vlm_calls += 1

        # 2 — Art Director plan (local Ollama reasoning, NIM failover via router).
        await orch.request_vram("ollama", reason="plan")
        orch.begin_reasoning()
        try:
            manifest = await plan(
                dna, run_input.options.assets, run_dir=run_dir, settings=s, client=router
            )
        finally:
            orch.end_reasoning()
        _bump_routing_stats(router, stats)

        # 3 — per-asset generate→critique→refine loop.
        for idx, spec in enumerate(manifest.assets):
            bail_reason = ""
            if cancel_event is not None and cancel_event.is_set():
                bail_reason = "cancelled"
            elif time.perf_counter() - t0 > s.run_timeout_s:
                bail_reason = "timeout"
            elif stats.total_renders >= s.max_total_renders:
                bail_reason = "render_cap"
            if bail_reason:
                log.warning("runner.bail", reason=bail_reason, asset_id=spec.id)
                for rem in manifest.assets[idx:]:
                    kit_assets.append(
                        KitAsset(
                            id=rem.id,
                            type=rem.type,
                            path="",
                            status="failed",
                            error=f"skipped: {bail_reason}",
                        )
                    )
                break

            kit_assets.append(
                await _process_asset(
                    spec,
                    dna,
                    run_dir,
                    s,
                    orch,
                    sc,
                    router,
                    cc,
                    stats,
                    run_input.options.max_retries_per_asset,
                    cancel_event,
                    t0,
                    generate,
                    critic,
                    rewrite,
                    log,
                )
            )

        # 4 — Assemble the kit (always reached on normal/cap/timeout/cancel paths).
        total_latency = time.perf_counter() - t0
        stats.vram_swaps = sum(1 for e in orch.events if e.action.startswith("request_vram:"))
        assert dna is not None and manifest is not None
        kit = await assemble_kit(
            run_dir, manifest, dna, kit_assets, total_latency_s=total_latency, stats=stats
        )
    finally:
        if owns_stepfun:
            await sc.aclose()
        if owns_ollama:
            await oc.aclose()
        if owns_nim:
            await nim.aclose()
        if owns_comfyui:
            await cc.aclose()
        if orchestrator is None:
            await orch.aclose()

    log.info(
        "runner.done",
        status=kit.status,
        total_latency_s=round(total_latency, 1),
        approved=sum(1 for a in kit_assets if a.status == "approved"),
        vlm_calls=stats.total_vlm_calls,
        renders=stats.total_renders,
        vram_swaps=stats.vram_swaps,
    )
    return kit


async def _process_asset(
    spec: AssetSpec,
    dna: BrandDna,
    run_dir: RunDir,
    s: Settings,
    orch: ModelOrchestrator,
    sc: StepfunClient,
    router: ReasonRouter,
    cc: ComfyUIClient,
    stats: OptimizationStats,
    max_retries: int,
    cancel_event: asyncio.Event | None,
    t0: float,
    generate: GenerateFn,
    critic: CriticFn,
    rewrite: RewriteFn,
    log: structlog.stdlib.BoundLogger,
) -> KitAsset:
    final_score: int | None = None
    last_error: str | None = None
    approved = False
    cur_spec = spec

    for attempt in range(1, max_retries + 2):  # 1..max_retries+1 attempts
        if cancel_event is not None and cancel_event.is_set():
            break
        if stats.total_vlm_calls >= s.max_total_vlm_calls:
            log.warning("runner.vlm_cap", total_vlm_calls=stats.total_vlm_calls)
            break
        if time.perf_counter() - t0 > s.run_timeout_s:
            break

        # Render (ComfyUI) — swap to generating first.
        await orch.request_vram("comfyui", reason=f"render:{cur_spec.id}:v{attempt}")
        render = await generate(cur_spec, run_dir, attempt, settings=s, client=cc)
        stats.total_renders += 1
        if getattr(render, "error", None):
            last_error = render.error
            log.warning(
                "runner.render_failed", asset_id=cur_spec.id, attempt=attempt, error=last_error
            )
            continue

        # Critique (cloud VLM).
        effort = effort_for("critic", attempt)
        if effort == "low":
            stats.critic_effort_low_count += 1
        elif effort == "medium":
            stats.critic_effort_medium_count += 1
        else:
            stats.critic_effort_high_count += 1
        result = await critic(
            render.png_path, cur_spec, dna, run_dir=run_dir, attempt=attempt, settings=s, client=sc
        )
        stats.total_vlm_calls += 1
        final_score = result.score
        if result.pass_:
            approved = True
            break

        # Failed critique → rewrite prompt for the next attempt (router: local/NIM).
        last_error = result.feedback or "critic failed"
        if attempt <= max_retries:
            await orch.request_vram("ollama", reason=f"rewrite:{cur_spec.id}:v{attempt}")
            orch.begin_reasoning()
            try:
                cur_spec = await rewrite(cur_spec, result.feedback, settings=s, client=router)
            finally:
                orch.end_reasoning()
            _bump_routing_stats(router, stats)

    return KitAsset(
        id=cur_spec.id,
        type=cur_spec.type,
        path=(run_dir.asset_path(cur_spec.id, attempt).as_posix() if approved else ""),
        status="approved" if approved else "failed",
        final_score=final_score,
        error=None if approved else (last_error or "max retries exhausted"),
    )
