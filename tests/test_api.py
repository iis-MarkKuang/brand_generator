"""Unit tests for the FastAPI backend (mocked pipeline, httpx ASGITransport)."""

from __future__ import annotations

import asyncio
import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from PIL import Image

from src.common.config import Settings
from src.common.runs import RunDir
from src.common.schemas import KitAsset, KitManifest, OptimizationStats
from src.orchestrator.api import create_app


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (10, 20, 30)).save(buf, "PNG")
    return buf.getvalue()


def _settings(tmp_path: Path, **over: Any) -> Settings:
    base = dict(
        _env_file=None,
        stepfun_api_key="sk-test",
        nvidia_api_key="nv-test",
        hf_token="hf-test",
        telegram_bot_token="tg-test",
        runs_root=str(tmp_path / "runs"),
        cors_allowed_origins=["http://localhost:5173"],
    )
    base.update(over)
    return Settings(**base)


def _mock_pipeline(sleep_s: float = 0.0, fail: bool = False):
    async def _pipe(run_input, *, settings):
        rd = RunDir(settings.runs_root, run_input.run_id).ensure()
        if sleep_s:
            await asyncio.sleep(sleep_s)
        if fail:
            raise RuntimeError("boom")
        events = [
            {
                "t": "2026-07-13T09:00:00",
                "action": "request_vram:ollama",
                "reason": "plan",
                "vram_before_gb": 80.0,
                "vram_after_gb": 80.0,
                "latency_s": 0.01,
            },
            {
                "t": "2026-07-13T09:00:01",
                "action": "request_vram:comfyui",
                "reason": "render:logo:v1",
                "vram_before_gb": 60.0,
                "vram_after_gb": 84.0,
                "latency_s": 0.02,
            },
            {
                "t": "2026-07-13T09:00:02",
                "action": "request_vram:ollama",
                "reason": "rewrite:logo:v1",
                "vram_before_gb": 84.0,
                "vram_after_gb": 84.0,
                "latency_s": 0.01,
            },
        ]
        rd.orchestrator_log_path().write_text(
            json.dumps({"run_id": run_input.run_id, "events": events})
        )
        rd.asset_path("logo", 1).write_bytes(_png_bytes())
        kit = KitManifest(
            run_id=run_input.run_id,
            brand_name=run_input.brand_name,
            status="partial",
            assets=[
                KitAsset(
                    id="logo",
                    type="logo",
                    path="brand_kit/logo.png",
                    status="failed",
                    final_score=62,
                    error="text garbled",
                )
            ],
            palette=["#3B2417", "#F3E9D8"],
            generated_at=datetime.now(UTC),
            total_latency_s=10,
            optimization_stats=OptimizationStats(vram_swaps=3),
        )
        rd.kit_manifest_path().write_text(kit.model_dump_json(indent=2))
        rd.kit_asset_path("brand_guide.md").write_text("# Brand\n\n## Palette\n| #3B2417 |\n")
        rd.kit_asset_path("logo.png").write_bytes(_png_bytes())
        return kit

    return _pipe


def _client(settings: Settings, pipeline_fn):
    app = create_app(settings=settings, pipeline_fn=pipeline_fn)
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test"), app


@pytest.mark.asyncio
async def test_post_run_then_get_manifest(tmp_path) -> None:
    s = _settings(tmp_path)
    client, app = _client(s, _mock_pipeline())
    try:
        r = await client.post(
            "/api/runs",
            data={
                "brief": "a coffee roaster",
                "brand_name": "Ember & Oat",
                "assets": "logo",
                "max_retries": "1",
            },
            files={"image": ("ref.png", _png_bytes(), "image/png")},
        )
        assert r.status_code == 202
        run_id = r.json()["run_id"]
        # let the task finish
        for _ in range(40):
            g = await client.get(f"/api/runs/{run_id}")
            if g.json().get("stage") == "assembled":
                break
            await asyncio.sleep(0.05)
        g = await client.get(f"/api/runs/{run_id}")
        assert g.status_code == 200
        body = g.json()
        assert body["stage"] == "assembled"
        assert body["manifest"]["run_id"] == run_id
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_concurrent_post_returns_409(tmp_path) -> None:
    s = _settings(tmp_path)
    client, app = _client(s, _mock_pipeline(sleep_s=1.0))
    try:
        r1 = await client.post(
            "/api/runs",
            data={"brief": "b1", "brand_name": "B1"},
            files={"image": ("r.png", _png_bytes(), "image/png")},
        )
        assert r1.status_code == 202
        r2 = await client.post(
            "/api/runs",
            data={"brief": "b2", "brand_name": "B2"},
            files={"image": ("r.png", _png_bytes(), "image/png")},
        )
        assert r2.status_code == 409
        assert "active_run_id" in str(r2.json())
        # drain
        await asyncio.sleep(1.2)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_path_traversal_blocked(tmp_path) -> None:
    s = _settings(tmp_path)
    client, app = _client(s, _mock_pipeline())
    try:
        r = await client.post(
            "/api/runs", data={"brief": "b"}, files={"image": ("r.png", _png_bytes(), "image/png")}
        )
        run_id = r.json()["run_id"]
        await asyncio.sleep(0.1)
        for bad in ("..%2F..%2F.env", "..\\..\\env", "foo.txt", "logo.png/../../../env"):
            rr = await client.get(f"/api/runs/{run_id}/assets/{bad}")
            assert rr.status_code in (400, 404), f"{bad} -> {rr.status_code}"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_oversize_and_non_image(tmp_path) -> None:
    s = _settings(tmp_path, max_upload_mb=1)
    client, app = _client(s, _mock_pipeline())
    try:
        big = b"\x00" * (2 * 1024 * 1024)
        r = await client.post(
            "/api/runs", data={"brief": "b"}, files={"image": ("big.png", big, "image/png")}
        )
        assert r.status_code == 413
        r2 = await client.post(
            "/api/runs",
            data={"brief": "b"},
            files={"image": ("not.txt", b"not an image", "image/png")},
        )
        assert r2.status_code == 400
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_cors_allowlist_only(tmp_path) -> None:
    s = _settings(tmp_path)
    client, app = _client(s, _mock_pipeline())
    try:
        ok = await client.get("/api/health", headers={"Origin": "http://localhost:5173"})
        assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
        bad = await client.get("/api/health", headers={"Origin": "http://evil.com"})
        assert bad.headers.get("access-control-allow-origin") != "http://evil.com"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_kit_zip_valid(tmp_path) -> None:
    s = _settings(tmp_path)
    client, app = _client(s, _mock_pipeline())
    try:
        r = await client.post(
            "/api/runs", data={"brief": "b"}, files={"image": ("r.png", _png_bytes(), "image/png")}
        )
        run_id = r.json()["run_id"]
        await asyncio.sleep(0.2)
        z = await client.get(f"/api/runs/{run_id}/kit.zip")
        assert z.status_code == 200
        assert z.headers["content-type"] == "application/zip"
        zf = zipfile.ZipFile(io.BytesIO(z.content))
        names = zf.namelist()
        assert "brand_guide.md" in names and "logo.png" in names
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_health_reports_deps(tmp_path) -> None:
    s = _settings(tmp_path)
    client, app = _client(s, _mock_pipeline())
    try:
        r = await client.get("/api/health")
        assert r.status_code == 200
        deps = r.json()["deps"]
        assert set(deps.keys()) == {"ollama", "comfyui", "stepfun"}
        assert deps["stepfun"] is True  # api key present
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_sse_streams_events_then_closes(tmp_path) -> None:
    s = _settings(tmp_path)
    client, app = _client(s, _mock_pipeline())
    try:
        r = await client.post(
            "/api/runs", data={"brief": "b"}, files={"image": ("r.png", _png_bytes(), "image/png")}
        )
        run_id = r.json()["run_id"]
        await asyncio.sleep(0.1)
        got = []
        async with client.stream("GET", f"/api/runs/{run_id}/events") as resp:
            assert resp.status_code == 200
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    got.append(json.loads(line[6:]))
                if got and got[-1].get("event") == "done":
                    break
        assert len(got) >= 3
        assert got[-1]["event"] == "done"
    finally:
        await client.aclose()
