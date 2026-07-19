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
from src.agents.brand_analyst import analyze_brand, brand_dna_cache_key_multi
from src.agents.consistency import check_consistency
from src.agents.critic import critic_asset
from src.agents.generator import generate_asset
from src.common.aiofs import read_text as aio_read_text
from src.common.aiofs import to_thread
from src.common.aiofs import write_text as aio_write_text
from src.common.brief_parser import BriefTokenError, parse_image_roles, validate_brief_tokens
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
    IterateRequest,
    KitAsset,
    KitManifest,
    OptimizationStats,
    RunInput,
)
from src.common.stepfun import StepfunClient
from src.optimizer.model_orchestrator import ModelOrchestrator, effort_for

__all__ = ["run_pipeline", "iterate_run"]

_log = structlog.get_logger(__name__)

AnalyzeFn = Callable[..., Awaitable[BrandDna]]
PlanFn = Callable[..., Awaitable[AssetManifest]]
GenerateFn = Callable[..., Awaitable[Any]]
CriticFn = Callable[..., Awaitable[Any]]
RewriteFn = Callable[..., Awaitable[AssetSpec]]


def _check_cache_hit(brief: str, images: list[str | Path]) -> bool:
    try:
        all_bytes = [Path(p).read_bytes() for p in images]
        key = brand_dna_cache_key_multi(brief, all_bytes)
        return (Path("cache/brand_dna") / f"{key}.json").exists()
    except OSError:
        return False


def _resolve_reference_indices(
    manifest: AssetManifest, reference_images: list[str]
) -> AssetManifest:
    """CP-020: post-plan hook — resolve reference_index → pulid_reference path.

    For each asset with ``reference_index = N`` (1-based), set ``pulid_reference``
    to ``reference_images[N-1]``. For ``uses_pulid=true`` assets without an explicit
    ``reference_index``, default to the first image.
    """
    if not reference_images:
        return manifest
    updated_assets: list[AssetSpec] = []
    for spec in manifest.assets:
        idx = spec.reference_index
        if idx is not None and 1 <= idx <= len(reference_images):
            ref_path = reference_images[idx - 1]
            # Set pulid_reference only if uses_pulid is true; otherwise the
            # index still serves as a semantic annotation for the critic.
            if spec.uses_pulid and not spec.pulid_reference:
                spec = spec.model_copy(update={"pulid_reference": ref_path})
        elif spec.uses_pulid and not spec.pulid_reference:
            # Default: first image for PuLID when no index specified.
            spec = spec.model_copy(update={"pulid_reference": reference_images[0]})
        updated_assets.append(spec)
    return manifest.model_copy(update={"assets": updated_assets})


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

    # CP-020: validate @N tokens in brief against the number of uploaded images.
    ref_images = run_input.reference_images
    try:
        validate_brief_tokens(run_input.brief, len(ref_images))
    except BriefTokenError:
        raise  # already validated by the API; re-check for direct callers
    image_roles = parse_image_roles(run_input.brief, len(ref_images))

    # Provenance: copy reference images into the run's input dir (best-effort).
    # The API already saved them as reference_N.<ext>; this is a no-op for API runs
    # but matters for CLI runs where the source may be elsewhere.
    with contextlib.suppress(OSError):
        for idx, src in enumerate(ref_images, start=1):
            dst = run_dir.input_dir / f"reference_{idx}{Path(src).suffix or '.png'}"
            if not dst.exists():
                shutil.copyfile(src, dst)

    stats = OptimizationStats()
    kit_assets: list[KitAsset] = []
    dna_cache_hit = await to_thread(_check_cache_hit, run_input.brief, ref_images)
    stats.brand_dna_cache_hit = dna_cache_hit
    dna: BrandDna | None = None
    manifest: AssetManifest | None = None

    try:
        # 1 — Brand Analyst (cloud VLM; no local VRAM swap needed).
        dna = await analyze(
            run_input.brief,
            ref_images,
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
                dna,
                run_input.options.assets,
                run_dir=run_dir,
                settings=s,
                client=router,
                image_roles=image_roles,
                num_images=len(ref_images),
            )
        finally:
            orch.end_reasoning()
        _bump_routing_stats(router, stats)

        # CP-020: post-plan hook — resolve reference_index → pulid_reference.
        manifest = _resolve_reference_indices(manifest, ref_images)

        # 3 — per-asset generate→critique→refine loop.
        # Fail-fast: if any asset fails (after all retries), stop immediately
        # and mark remaining assets as skipped — don't waste GPU time.
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

            kit_asset = await _process_asset(
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
            kit_assets.append(kit_asset)

            # Fail-fast: if this asset failed, skip all remaining assets.
            if kit_asset.status == "failed":
                failed_id = kit_asset.id
                log.warning(
                    "runner.fail_fast",
                    failed_asset=failed_id,
                    skipped=[a.id for a in manifest.assets[idx + 1 :]],
                )
                for rem in manifest.assets[idx + 1 :]:
                    kit_assets.append(
                        KitAsset(
                            id=rem.id,
                            type=rem.type,
                            path="",
                            status="failed",
                            error=f"skipped: asset '{failed_id}' failed (fail-fast)",
                        )
                    )
                break

        # 4 — Assemble the kit (always reached on normal/cap/timeout/cancel paths).
        total_latency = time.perf_counter() - t0
        stats.vram_swaps = sum(1 for e in orch.events if e.action.startswith("request_vram:"))
        if dna is None or manifest is None:
            raise RuntimeError("run_pipeline: dna/manifest missing before assemble_kit")
        kit = await assemble_kit(
            run_dir, manifest, dna, kit_assets, total_latency_s=total_latency, stats=stats
        )

        # 4b — CP-017: VLM cross-asset consistency check (2+ approved assets).
        approved_pairs: list[tuple[str, str | Path]] = [
            (a.id, run_dir.path / a.path) for a in kit_assets if a.status == "approved" and a.path
        ]
        if len(approved_pairs) >= 2:
            try:
                kit.consistency = await check_consistency(
                    approved_pairs,
                    dna,
                    run_dir=run_dir,
                    settings=s,
                    client=sc,
                )
                log.info("runner.consistency", overall=kit.consistency.overall_score)
            except Exception as exc:  # noqa: BLE001 — best-effort, never crash
                log.warning("runner.consistency_skip", error=str(exc)[:120], exc_info=True)
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


async def iterate_run(
    prev_run_id: str,
    request: IterateRequest,
    *,
    new_run_id: str,
    settings: Settings | None = None,
    stepfun_client: StepfunClient | None = None,
    ollama_client: OllamaClient | None = None,
    comfyui_client: ComfyUIClient | None = None,
    orchestrator: ModelOrchestrator | None = None,
    cancel_event: asyncio.Event | None = None,
) -> KitManifest:
    """CP-019: conversational design iteration.

    Loads the previous run's Brand DNA + asset manifest, re-renders the requested
    assets (or all approved) using the user's feedback as the rewrite cue, copies
    unchanged approved assets from the prev run, and assembles a new kit.
    Showcases the multi-turn VLM→LLM→Generator agent loop on DGX Spark.
    """
    s = settings or get_settings()
    log = _log.bind(agent="runner", run_id=new_run_id, prev_run_id=prev_run_id, mode="iterate")
    t0 = time.perf_counter()

    prev_dir = RunDir(Path("runs"), prev_run_id)
    dna_path = prev_dir.path / "brand_dna.json"
    manifest_path = prev_dir.manifest_path()  # asset_manifest.json
    kit_manifest_path = prev_dir.kit_manifest_path()
    if not dna_path.exists() or not manifest_path.exists() or not kit_manifest_path.exists():
        raise FileNotFoundError(
            f"previous run {prev_run_id} missing brand_dna.json / asset_manifest.json / kit_manifest.json"
        )

    dna = BrandDna.model_validate_json(await aio_read_text(dna_path))
    prev_asset_manifest = AssetManifest.model_validate_json(await aio_read_text(manifest_path))
    prev_kit = KitManifest.model_validate_json(await aio_read_text(kit_manifest_path))

    # Map asset_id → prev KitAsset (to know which were approved)
    prev_kit_map = {a.id: a for a in prev_kit.assets}
    # Map asset_id → original AssetSpec
    spec_map = {sp.id: sp for sp in prev_asset_manifest.assets}
    approved_ids = [a.id for a in prev_kit.assets if a.status == "approved"]
    rerender_ids = set(request.assets) if request.assets else set(approved_ids)

    log.info("iterate.loaded", prev_approved=len(approved_ids), rerender=len(rerender_ids))

    run_dir = RunDir(Path("runs"), new_run_id).ensure()
    # Copy the brand DNA to the new run dir (so the assembler + consistency can find it)
    await to_thread(shutil.copyfile, dna_path, run_dir.path / "brand_dna.json")
    stats = OptimizationStats(brand_dna_cache_hit=True)

    owns_stepfun = stepfun_client is None
    owns_ollama = ollama_client is None
    owns_comfyui = comfyui_client is None
    sc = stepfun_client or StepfunClient(s)
    oc = ollama_client or OllamaClient(s)
    cc = comfyui_client or ComfyUIClient(s)
    nim = NimClient(s)
    orch = orchestrator or ModelOrchestrator(run_dir, settings=s, ollama=oc, comfyui=cc)
    router = ReasonRouter(s, ollama=oc, nim=nim, on_routing=orch.record_routing)

    kit_assets: list[KitAsset] = []
    new_specs: list[AssetSpec] = []

    try:
        for aid in approved_ids:
            orig_spec = spec_map.get(aid)
            if orig_spec is None:
                log.warning("iterate.no_spec", asset_id=aid)
                continue

            if aid in rerender_ids:
                # Rewrite the prompt using the user's feedback as the "critique"
                await orch.request_vram("ollama", reason=f"iterate:{aid}")
                orch.begin_reasoning()
                try:
                    new_spec = await rewrite_prompt(
                        orig_spec, request.feedback, settings=s, client=router
                    )
                finally:
                    orch.end_reasoning()
                _bump_routing_stats(router, stats)
                new_specs.append(new_spec)
                log.info("iterate.rewritten", asset_id=aid, feedback=request.feedback[:80])

                # Render + critique (reuse _process_asset)
                kit_assets.append(
                    await _process_asset(
                        new_spec,
                        dna,
                        run_dir,
                        s,
                        orch,
                        sc,
                        router,
                        cc,
                        stats,
                        1,
                        cancel_event,
                        t0,  # max_retries=1 in iteration mode
                        generate_asset,
                        critic_asset,
                        rewrite_prompt,
                        log,
                    )
                )
            else:
                # Copy unchanged approved asset from prev run
                prev_png = prev_dir.path / prev_kit_map[aid].path
                if prev_png.exists():
                    dst = run_dir.kit_asset_path(f"{aid}.png")
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    await to_thread(shutil.copyfile, prev_png, dst)
                    kit_assets.append(
                        KitAsset(
                            id=aid,
                            type=orig_spec.type,
                            path=f"brand_kit/{aid}.png",
                            status="approved",
                            final_score=prev_kit_map[aid].final_score,
                            error=None,
                        )
                    )
                    new_specs.append(orig_spec)
                    log.info("iterate.reused", asset_id=aid)

        # Persist the new asset manifest
        new_manifest = AssetManifest(
            run_id=new_run_id,
            brand_dna_ref="brand_dna.json",
            assets=new_specs,
        )
        await aio_write_text(run_dir.manifest_path(), new_manifest.model_dump_json(indent=2))

        # Assemble the new kit
        total_latency = time.perf_counter() - t0
        stats.vram_swaps = sum(1 for e in orch.events if e.action.startswith("request_vram:"))
        kit = await assemble_kit(
            run_dir, new_manifest, dna, kit_assets, total_latency_s=total_latency, stats=stats
        )

        # Consistency check
        approved_pairs: list[tuple[str, str | Path]] = [
            (a.id, run_dir.path / a.path) for a in kit_assets if a.status == "approved" and a.path
        ]
        if len(approved_pairs) >= 2:
            with contextlib.suppress(Exception):
                kit.consistency = await check_consistency(
                    approved_pairs,
                    dna,
                    run_dir=run_dir,
                    settings=s,
                    client=sc,
                )
    finally:
        if owns_stepfun:
            await sc.aclose()
        if owns_ollama:
            await oc.aclose()
        if owns_comfyui:
            await cc.aclose()
        await nim.aclose()
        if orchestrator is None:
            await orch.aclose()

    log.info(
        "iterate.done",
        status=kit.status,
        total_latency_s=round(total_latency, 1),
        approved=sum(1 for a in kit_assets if a.status == "approved"),
    )
    return kit
