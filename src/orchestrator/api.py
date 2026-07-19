"""FastAPI service exposing the StyleForge pipeline (CP-010).

Routes (see ``references/design/05-frontend.md``):
  POST   /api/runs                 start a run (multipart) → {run_id}
  GET    /api/runs/{id}            current manifest + stage
  GET    /api/runs/{id}/events     SSE stream of orchestrator/asset events
  GET    /api/runs/{id}/assets/{name}   serve a PNG
  GET    /api/runs/{id}/brand_guide    serve brand_guide.md
  GET    /api/runs/{id}/kit.zip    zip the brand_kit/ dir
  GET    /api/health               liveness + dependency probes

This service is the **single secrets boundary** (the only component loading ``.env``).
Single-flight: one run at a time on the GB10 (POST returns 409 if a run is active).
All file-serving routes confine paths to ``runs/<run_id>/`` (S1/S7).
"""

from __future__ import annotations

import asyncio
import io
import json
import re
import zipfile
from pathlib import Path
from typing import Annotated, Any, get_args

import httpx
import structlog
from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from PIL import Image, UnidentifiedImageError

from src.common.brief_parser import BriefTokenError, validate_brief_tokens
from src.common.config import Settings, get_settings
from src.common.runs import RunDir, new_run_id
from src.common.schemas import AssetType, HealthResponse, IterateRequest, RunInput, RunOptions
from src.orchestrator.runner import iterate_run, run_pipeline

__all__ = ["create_app"]

_log = structlog.get_logger(__name__)

# SSE event field allowlist (S5) — never streams raw env or full user text.
_SSE_ALLOW = {
    "t",
    "action",
    "reason",
    "vram_before_gb",
    "vram_after_gb",
    "latency_s",
    "backend",
    "event",
    "asset_id",
    "attempt",
    "stage",
    "status",
}


def create_app(
    settings: Settings | None = None, pipeline_fn: Any = None, iterate_fn: Any = None
) -> FastAPI:
    s = settings or get_settings()
    app = FastAPI(title="StyleForge", version="0.1.0")
    app.state.settings = s
    pipeline = pipeline_fn or run_pipeline
    iter_fn = iterate_fn or iterate_run

    class _Registry:
        def __init__(self) -> None:
            self.runs: dict[str, asyncio.Task[Any]] = {}
            self.results: dict[str, Any] = {}

    reg = _Registry()
    pipeline = pipeline_fn or run_pipeline

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(s.cors_allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    runs_root = s.runs_root

    def _run_dir(run_id: str) -> RunDir:
        if not re.fullmatch(s.run_id_regex, run_id):
            raise HTTPException(status_code=400, detail="invalid run_id")
        return RunDir(runs_root, run_id)

    # ------------------------------------------------------------------ #
    @app.get("/api/health", tags=["health"], response_model=HealthResponse)
    async def health() -> dict[str, Any]:
        """Liveness probe — reports orchestrator status and dependency health."""
        return {"status": "ok", "deps": await _probe_deps(s)}

    # ------------------------------------------------------------------ #
    @app.post("/api/runs", tags=["runs"])
    async def start_run(
        brief: Annotated[str, Form(...)],
        image: Annotated[list[UploadFile], File(...)],
        brand_name: Annotated[str, Form(...)] = "Untitled",
        assets: Annotated[
            str, Form(...)
        ] = "logo,hero_banner,social_square,product_mockup,business_card",
        max_retries: Annotated[int, Form(...)] = 1,
    ) -> JSONResponse:
        """Start a new brand-kit generation run (multipart upload). Returns 202 + run_id.

        Accepts one or more ``image`` file parts (CP-020 multi-reference). The brief
        may use ``@1``/``@2``/… tokens to indicate which image serves which purpose.
        """
        active = [rid for rid, t in reg.runs.items() if not t.done()]
        if active:
            raise HTTPException(status_code=409, detail={"active_run_id": active[0]})

        # CP-020: accept 1..max_reference_images images.
        if not image:
            raise HTTPException(status_code=400, detail="at least one image is required")
        if len(image) > s.max_reference_images:
            raise HTTPException(
                status_code=400,
                detail=f"too many images: {len(image)} > max {s.max_reference_images}",
            )

        # Validate @N tokens in brief against the upload count (early fail).
        try:
            validate_brief_tokens(brief, len(image))
        except BriefTokenError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        run_id = new_run_id()
        run_dir = RunDir(runs_root, run_id).ensure()

        # Save each image as reference_<N>.<ext> (preserve original extension).
        ref_paths: list[str] = []
        for idx, img in enumerate(image, start=1):
            raw = await img.read()
            if len(raw) > s.max_upload_mb * 1024 * 1024:
                raise HTTPException(status_code=413, detail=f"image {idx} too large")
            try:
                with Image.open(io.BytesIO(raw)) as im:
                    im.verify()
            except (UnidentifiedImageError, ValueError) as exc:
                raise HTTPException(
                    status_code=400, detail=f"image {idx} is not a valid image"
                ) from exc
            suffix = Path(img.filename or "").suffix or ".png"
            if suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                suffix = ".png"
            ref_path = run_dir.input_dir / f"reference_{idx}{suffix}"
            ref_path.write_bytes(raw)
            ref_paths.append(str(ref_path))

        asset_list = [a.strip() for a in assets.split(",") if a.strip()]
        valid: list[AssetType] = []
        for a in asset_list:
            if a not in get_args(AssetType):
                raise HTTPException(status_code=400, detail=f"invalid asset type: {a}")
            valid.append(a)  # type: ignore[arg-type]
        run_input = RunInput(
            run_id=run_id,
            brand_name=brand_name,
            brief=brief,
            reference_images=ref_paths,
            options=RunOptions(assets=valid, max_retries_per_asset=max_retries),
        )

        async def _runner() -> Any:
            try:
                kit = await pipeline(run_input, settings=s)
                reg.results[run_id] = kit
                return kit
            except Exception as exc:  # noqa: BLE001 — never let the task die silently
                _log.exception("api.run.failed", run_id=run_id)
                reg.results[run_id] = exc
                raise

        task = asyncio.create_task(_runner())
        reg.runs[run_id] = task
        _log.info("api.run.started", run_id=run_id, brand=brand_name, assets=asset_list)
        return JSONResponse({"run_id": run_id}, status_code=202)

    # ------------------------------------------------------------------ #
    @app.post("/api/runs/{prev_run_id}/iterate", tags=["runs"])
    async def iterate_prev_run(
        prev_run_id: str,
        body: IterateRequest,
    ) -> JSONResponse:
        """CP-019: conversational design iteration — re-render with user feedback."""
        # single-flight
        active = [rid for rid, t in reg.runs.items() if not t.done()]
        if active:
            raise HTTPException(status_code=409, detail={"active_run_id": active[0]})

        prev_rd = _run_dir(prev_run_id)
        if not (prev_rd.path / "brand_dna.json").exists():
            raise HTTPException(status_code=404, detail="previous run not found")
        if not prev_rd.kit_manifest_path().exists():
            raise HTTPException(status_code=409, detail="previous run not yet assembled")

        new_id = new_run_id()

        async def _iter_runner() -> Any:
            try:
                kit = await iter_fn(prev_run_id, body, new_run_id=new_id, settings=s)
                reg.results[new_id] = kit
                return kit
            except Exception as exc:  # noqa: BLE001
                _log.exception("api.iterate.failed", new_id=new_id, prev=prev_run_id)
                reg.results[new_id] = exc
                raise

        task = asyncio.create_task(_iter_runner())
        reg.runs[new_id] = task
        _log.info(
            "api.iterate.started", new_id=new_id, prev=prev_run_id, feedback=body.feedback[:80]
        )
        return JSONResponse({"run_id": new_id, "prev_run_id": prev_run_id}, status_code=202)

    # ------------------------------------------------------------------ #
    @app.get("/api/runs", tags=["runs"])
    async def list_runs() -> dict[str, Any]:
        """List all runs (newest-first) with their assembly status."""
        root = Path(runs_root).resolve()
        if not root.exists():
            return {"runs": []}
        dirs = [d for d in root.iterdir() if d.is_dir()]
        # Sort by mtime (newest first), not by name — golden-001/test-run-001
        # would otherwise appear before timestamped runs.
        dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
        out = []
        for d in dirs:
            kit_p = d / "brand_kit" / "kit_manifest.json"
            status = "assembled" if kit_p.exists() else "pending"
            out.append({"run_id": d.name, "status": status, "created_at": int(d.stat().st_mtime)})
        return {"runs": out}

    # ------------------------------------------------------------------ #
    @app.get("/api/runs/{run_id}", tags=["runs"])
    async def get_run(run_id: str) -> dict[str, Any]:
        """Get a run's current stage and manifest (if assembled)."""
        rd = _run_dir(run_id)
        if not rd.path.exists():
            raise HTTPException(status_code=404, detail="run not found")
        manifest = None
        if rd.kit_manifest_path().exists():
            manifest = json.loads(rd.kit_manifest_path().read_text())
        return {"run_id": run_id, "stage": _stage(rd, reg.runs.get(run_id)), "manifest": manifest}

    # ------------------------------------------------------------------ #
    @app.get("/api/runs/{run_id}/brand_dna", tags=["runs"])
    async def brand_dna(run_id: str) -> JSONResponse:
        """Serve the extracted brand DNA JSON for a run."""
        rd = _run_dir(run_id)
        p = rd.brand_dna_path()
        if not p.exists():
            raise HTTPException(status_code=404, detail="brand_dna not ready")
        return JSONResponse(json.loads(p.read_text()))

    # ------------------------------------------------------------------ #
    @app.get("/api/runs/{run_id}/events", tags=["runs"])
    async def events(run_id: str, request: Request) -> StreamingResponse:
        """SSE stream of orchestrator/asset events for a run (real-time progress)."""
        rd = _run_dir(run_id)

        async def gen() -> Any:
            sent_events = 0
            while True:
                if await request.is_disconnected():
                    return
                evs = _read_orchestrator_events(rd)
                for ev in evs[sent_events:]:
                    yield f"data: {json.dumps(_allowlist(ev))}\n\n"
                sent_events = len(evs)
                # asset-ready events
                for png in sorted(rd.assets.glob("*.png")):
                    yield f"data: {json.dumps({'event': 'asset', 'asset_id': png.stem})}\n\n"
                task = reg.runs.get(run_id)
                done = task is not None and task.done()
                if done:
                    status = "complete" if rd.kit_manifest_path().exists() else "failed"
                    yield f"data: {json.dumps({'event': 'done', 'status': status})}\n\n"
                    return
                await asyncio.sleep(0.25)

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ------------------------------------------------------------------ #
    @app.get("/api/runs/{run_id}/assets/{name}", tags=["runs"])
    async def serve_asset(run_id: str, name: str) -> FileResponse:
        """Serve a rendered asset PNG from a run's assets/ directory."""
        rd = _run_dir(run_id)
        if not re.fullmatch(r"[A-Za-z0-9_]+\.(png|md|json)", name):
            raise HTTPException(status_code=400, detail="invalid asset name")
        p = rd._confined("assets", name)  # noqa: SLF001 — confined helper enforces boundary
        if not p.exists():
            raise HTTPException(status_code=404, detail="asset not found")
        return FileResponse(p, media_type="image/png")

    # ------------------------------------------------------------------ #
    @app.get("/api/runs/{run_id}/kit/{name}", tags=["runs"])
    async def serve_kit_file(run_id: str, name: str) -> FileResponse:
        """Serve a file from a run's assembled brand_kit/ directory."""
        rd = _run_dir(run_id)
        if not re.fullmatch(r"[A-Za-z0-9_]+\.(png|md|json)", name):
            raise HTTPException(status_code=400, detail="invalid kit file name")
        p = rd._confined("brand_kit", name)  # noqa: SLF001 — confined helper enforces boundary
        if not p.exists():
            raise HTTPException(status_code=404, detail="kit file not found")
        media = (
            "text/markdown; charset=utf-8"
            if name.endswith(".md")
            else ("application/json" if name.endswith(".json") else "image/png")
        )
        return FileResponse(p, media_type=media)

    # ------------------------------------------------------------------ #
    @app.get("/api/runs/{run_id}/brand_guide", tags=["runs"])
    async def brand_guide(run_id: str) -> FileResponse:
        """Serve the assembled brand guide (markdown) for a run."""
        rd = _run_dir(run_id)
        p = rd.kit_asset_path("brand_guide.md")
        if not p.exists():
            raise HTTPException(status_code=404, detail="brand guide not ready")
        return FileResponse(p, media_type="text/markdown; charset=utf-8")

    # ------------------------------------------------------------------ #
    @app.get("/api/runs/{run_id}/kit.zip", tags=["runs"])
    async def kit_zip(run_id: str) -> StreamingResponse:
        """Download the entire brand kit as a ZIP archive."""
        rd = _run_dir(run_id)
        if not rd.brand_kit.exists():
            raise HTTPException(status_code=404, detail="kit not ready")

        def _zipbuf() -> bytes:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for f in sorted(rd.brand_kit.iterdir()):
                    if f.is_file():
                        zf.write(f, arcname=f.name)
            return buf.getvalue()

        return StreamingResponse(
            io.BytesIO(_zipbuf()),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{run_id}_kit.zip"'},
        )

    return app


# ---------------------------------------------------------------------- #
# helpers
def _stage(rd: RunDir, task: asyncio.Task[Any] | None) -> str:
    if rd.kit_manifest_path().exists():
        return "assembled"
    evs = _read_orchestrator_events(rd)
    if evs:
        last: str = str(evs[-1].get("action", ""))
        if "comfyui" in last:
            return "generating"
        if "ollama" in last:
            return "reasoning"
        return last
    if task is not None and task.done():
        return "failed"
    return "starting"


def _read_orchestrator_events(rd: RunDir) -> list[dict[str, Any]]:
    p = rd.orchestrator_log_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    return list(data.get("events", []))


def _allowlist(ev: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in ev.items() if k in _SSE_ALLOW}


async def _probe_deps(s: Settings) -> dict[str, bool]:
    async def _check(url: str, timeout: float = 3.0) -> bool:
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.get(url)
                return r.status_code < 500
        except httpx.HTTPError:
            return False

    ollama = await _check(f"{s.ollama_host}/api/tags")
    comfyui = await _check(f"{s.comfyui_host}/api/system_stats")
    stepfun = bool(s.stepfun_api_key)
    return {"ollama": ollama, "comfyui": comfyui, "stepfun": stepfun}


# Module-level app for `uvicorn src.orchestrator.api:app`. Built at import so uvicorn
# receives a concrete ASGI callable. Tests use ``create_app(settings=...)`` directly and
# do not touch this singleton.
app = create_app()
