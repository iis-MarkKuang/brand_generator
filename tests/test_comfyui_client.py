"""Unit tests for the ComfyUI client (mocked transport)."""

from __future__ import annotations

import json

import httpx
import pytest

from src.common.comfyui import ComfyUIClient
from src.common.exceptions import ComfyUIError

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _client(handler, fake_settings) -> ComfyUIClient:
    return ComfyUIClient(fake_settings, httpx.AsyncClient(transport=httpx.MockTransport(handler)))


@pytest.mark.asyncio
async def test_submit_wait_fetch_roundtrip(fake_settings) -> None:
    pid = "p-123"
    history: dict[str, dict[str, object]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/prompt":
            body = json.loads(request.content)
            assert body["prompt"] == {"3": {"class_type": "KSampler"}}
            return httpx.Response(200, json={"prompt_id": pid})
        if path.startswith("/history/"):
            return httpx.Response(200, json=history)
        if path == "/view":
            assert request.url.params["filename"] == "out.png"
            assert request.url.params["type"] == "output"
            return httpx.Response(200, content=_PNG)
        return httpx.Response(404)

    c = _client(handler, fake_settings)
    got_pid = await c.submit({"3": {"class_type": "KSampler"}})
    assert got_pid == pid

    # First poll: empty; second poll: outputs ready.
    history[pid] = {
        "status": {"status_str": "success"},
        "outputs": {"9": {"images": [{"filename": "out.png", "subfolder": "", "type": "output"}]}},
    }
    entry = await c.wait(pid, timeout=5)
    assert entry["outputs"]["9"]["images"][0]["filename"] == "out.png"

    img = await c.fetch_image("out.png")
    assert img.startswith(b"\x89PNG")
    await c.aclose()


@pytest.mark.asyncio
async def test_wait_raises_on_error(fake_settings) -> None:
    pid = "p-err"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/history/"):
            return httpx.Response(
                200,
                json={
                    pid: {"status": {"status_str": "error", "messages": ["boom"]}, "outputs": {}}
                },
            )
        return httpx.Response(404)

    c = _client(handler, fake_settings)
    with pytest.raises(ComfyUIError):
        await c.wait(pid, timeout=5)
    await c.aclose()


@pytest.mark.asyncio
async def test_health(fake_settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/system_stats"
        return httpx.Response(200, json={"system": {"comfyui_version": "0.0.1"}})

    c = _client(handler, fake_settings)
    assert await c.health() is True
    await c.aclose()
