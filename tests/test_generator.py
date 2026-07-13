"""Unit tests for the Generator agent (mocked ComfyUI)."""

from __future__ import annotations

import io
import json
from pathlib import Path

import httpx
import pytest
from PIL import Image

from src.agents.generator import build_workflow, generate_asset
from src.common.comfyui import ComfyUIClient
from src.common.runs import RunDir
from src.common.schemas import AssetSpec, RenderResult

_PNG_BYTES = Image.new("RGB", (2, 2), (10, 20, 30)).save(io.BytesIO(), "PNG")


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (2, 2), (10, 20, 30)).save(buf, "PNG")
    return buf.getvalue()


def _spec(uses_pulid: bool = False, pulid_ref: str | None = None) -> AssetSpec:
    return AssetSpec(
        id="logo",
        type="logo",
        size=[1024, 1024],
        seed=42125,
        flux_prompt="minimalist logo #3B2417 #F3E9D8 Ember & Oat",
        negative_prompt="neon, 3d",
        composition="centered",
        uses_pulid=uses_pulid,
        pulid_reference=pulid_ref,
    )


def _client(handler, fake_settings) -> ComfyUIClient:
    return ComfyUIClient(fake_settings, httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def _success_history(pid: str, filename: str) -> dict:
    return {
        pid: {
            "status": {"status_str": "success"},
            "outputs": {
                "13": {"images": [{"filename": filename, "subfolder": "", "type": "output"}]}
            },
        }
    }


def _ok_handler(filename: str = "logo__v1_00001_.png"):
    def handler(request: httpx.Request) -> httpx.Response:
        p = request.url.path
        if p == "/prompt":
            return httpx.Response(200, json={"prompt_id": "p1"})
        if p.startswith("/history/"):
            return httpx.Response(200, json=_success_history("p1", filename))
        if p == "/view":
            return httpx.Response(200, content=_png_bytes(), headers={"content-type": "image/png"})
        if p == "/api/system_stats":
            return httpx.Response(200, json={})
        return httpx.Response(404)

    return handler


# ---- build_workflow (PuLID prune) ---------------------------------------- #


def test_build_workflow_prunes_pulid() -> None:
    wf = build_workflow(_spec(uses_pulid=False), attempt=1, steps=24)
    for nid in ("2", "3", "4", "5", "6"):
        assert nid not in wf
    assert wf["11"]["inputs"]["model"] == ["1", 0]
    assert wf["7"]["inputs"]["text"] == _spec().flux_prompt
    assert wf["10"]["inputs"]["batch_size"] == 1
    assert wf["13"]["inputs"]["filename_prefix"] == "logo__v1"


def test_build_workflow_keeps_pulid() -> None:
    wf = build_workflow(
        _spec(uses_pulid=True, pulid_ref="runs/r/input/ref.jpg"), attempt=2, steps=18
    )
    for nid in ("2", "3", "4", "5", "6"):
        assert nid in wf
    assert wf["11"]["inputs"]["model"] == ["6", 0]
    assert wf["5"]["inputs"]["image"] == "runs/r/input/ref.jpg"
    assert wf["11"]["inputs"]["steps"] == 18


# ---- build_workflow (CP-014 LoRA) ---------------------------------------- #


def test_build_workflow_no_lora_is_unchanged() -> None:
    wf = build_workflow(_spec(uses_pulid=False), attempt=1, steps=24)
    assert "100" not in wf  # no LoraLoader injected
    assert wf["7"]["inputs"]["clip"] == ["1", 1]  # clip straight from checkpoint
    assert wf["11"]["inputs"]["model"] == ["1", 0]


def test_build_workflow_lora_inserts_loader_no_pulid() -> None:
    wf = build_workflow(
        _spec(uses_pulid=False),
        attempt=1,
        steps=24,
        lora_adapter="brand_style_lora.safetensors",
        lora_strength=0.85,
    )
    # LoraLoader injected between checkpoint and model/clip consumers
    assert "100" in wf
    assert wf["100"]["class_type"] == "LoraLoader"
    assert wf["100"]["inputs"]["lora_name"] == "brand_style_lora.safetensors"
    assert wf["100"]["inputs"]["strength_model"] == 0.85
    assert wf["100"]["inputs"]["strength_clip"] == 0.85
    assert wf["100"]["inputs"]["model"] == ["1", 0]
    assert wf["100"]["inputs"]["clip"] == ["1", 1]
    # KSampler + CLIPTextEncode rewired to the LoRA outputs
    assert wf["11"]["inputs"]["model"] == ["100", 0]
    assert wf["7"]["inputs"]["clip"] == ["100", 1]
    assert wf["8"]["inputs"]["clip"] == ["100", 1]
    # VAE still comes from the checkpoint (LoRA does not touch the VAE)
    assert wf["12"]["inputs"]["vae"] == ["1", 2]


def test_build_workflow_lora_with_pulid() -> None:
    wf = build_workflow(
        _spec(uses_pulid=True, pulid_ref="runs/r/input/ref.jpg"),
        attempt=1,
        steps=24,
        lora_adapter="brand_style_lora.safetensors",
    )
    assert "100" in wf
    # ApplyPulidFlux takes the LoRA-applied model; KSampler still takes PuLID output
    assert wf["6"]["inputs"]["model"] == ["100", 0]
    assert wf["11"]["inputs"]["model"] == ["6", 0]
    # clip rewired to LoRA
    assert wf["7"]["inputs"]["clip"] == ["100", 1]
    assert wf["8"]["inputs"]["clip"] == ["100", 1]


# ---- generate_asset (valid render) --------------------------------------- #


@pytest.mark.asyncio
async def test_generate_asset_writes_png_and_meta(fake_settings, tmp_path) -> None:
    c = _client(_ok_handler(), fake_settings)
    run = RunDir(tmp_path / "runs", "test-gen-001").ensure()
    result = await generate_asset(_spec(), run, attempt=1, client=c, max_wait_s=10)
    assert isinstance(result, RenderResult)
    assert result.error is None
    assert result.prompt_id == "p1"
    assert result.seed == 42125
    png = Path(result.png_path)
    assert png.exists()
    assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    meta = json.loads((run.path / "assets" / "render_meta__logo__v1.json").read_text())
    assert meta["seed"] == 42125 and meta["steps"] == 24
    await c.aclose()


# ---- generate_asset (CUDA-dirty restart + retry) ------------------------- #


@pytest.mark.asyncio
async def test_generate_asset_cuda_dirty_restarts_once(fake_settings, tmp_path) -> None:
    calls = {"prompt": 0, "restart": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        p = request.url.path
        if p == "/prompt":
            calls["prompt"] += 1
            return httpx.Response(200, json={"prompt_id": f"p{calls['prompt']}"})
        if p.startswith("/history/p1"):
            return httpx.Response(
                200,
                json={
                    "p1": {
                        "status": {
                            "status_str": "error",
                            "messages": ["CUDA error: invalid argument"],
                        }
                    }
                },
            )
        if p.startswith("/history/p2"):
            return httpx.Response(200, json=_success_history("p2", "logo__v1_00001_.png"))
        if p == "/view":
            return httpx.Response(200, content=_png_bytes(), headers={"content-type": "image/png"})
        if p == "/api/system_stats":
            return httpx.Response(200, json={})
        return httpx.Response(404)

    async def restart() -> None:
        calls["restart"] += 1

    c = _client(handler, fake_settings)
    run = RunDir(tmp_path / "runs", "test-gen-002").ensure()
    result = await generate_asset(
        _spec(), run, attempt=1, client=c, max_wait_s=10, restart_fn=restart
    )
    assert calls["restart"] == 1
    assert calls["prompt"] == 2
    assert result.error is None
    assert Path(result.png_path).exists()
    await c.aclose()


@pytest.mark.asyncio
async def test_generate_asset_non_cuda_error_returns_error_result(fake_settings, tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": "p1"})
        if request.url.path.startswith("/history/p1"):
            return httpx.Response(
                200,
                json={
                    "p1": {
                        "status": {
                            "status_str": "error",
                            "messages": ["workflow rejected: bad node"],
                        }
                    }
                },
            )
        return httpx.Response(404)

    c = _client(handler, fake_settings)
    run = RunDir(tmp_path / "runs", "test-gen-003").ensure()
    result = await generate_asset(_spec(), run, attempt=1, client=c, max_wait_s=10)
    assert result.error is not None
    assert result.png_path == ""
    assert "bad node" in result.error
    await c.aclose()
