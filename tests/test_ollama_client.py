"""Unit tests for the Ollama client (mocked transport)."""

from __future__ import annotations

import json

import httpx
import pytest

from src.common.ollama import OllamaClient


def _client(handler, fake_settings) -> OllamaClient:
    return OllamaClient(fake_settings, httpx.AsyncClient(transport=httpx.MockTransport(handler)))


@pytest.mark.asyncio
async def test_chat_think_false_returns_content(fake_settings) -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        body = json.loads(request.content)
        captured["think"] = body["think"]
        captured["model"] = body["model"]
        return httpx.Response(
            200,
            json={
                "model": body["model"],
                "message": {"role": "assistant", "content": "hello world"},
                "done": True,
                "prompt_eval_count": 8,
                "eval_count": 2,
            },
        )

    c = _client(handler, fake_settings)
    out = await c.chat("qwen3.6:35b", [{"role": "user", "content": "hi"}], think=False)
    assert out == "hello world"
    assert captured["think"] is False
    assert captured["model"] == "qwen3.6:35b"
    await c.aclose()


@pytest.mark.asyncio
async def test_stop_sends_keep_alive_zero(fake_settings) -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/generate"
        body = json.loads(request.content)
        captured["keep_alive"] = body["keep_alive"]
        captured["model"] = body["model"]
        return httpx.Response(200, json={"done": True})

    c = _client(handler, fake_settings)
    await c.stop("nemotron-3-nano:30b")
    assert captured["keep_alive"] == 0
    assert captured["model"] == "nemotron-3-nano:30b"
    await c.aclose()


@pytest.mark.asyncio
async def test_ps_lists_loaded(fake_settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/ps"
        return httpx.Response(200, json={"models": [{"name": "qwen3.6:35b", "size_vram": 1234}]})

    c = _client(handler, fake_settings)
    loaded = await c.ps()
    assert loaded == [{"name": "qwen3.6:35b", "size_vram": 1234}]
    await c.aclose()


# ---- vram_probe (nvidia-smi subprocess + /api/ps) ------------------------ #


@pytest.mark.asyncio
async def test_vram_probe_parses_nvidia_smi(fake_settings, monkeypatch) -> None:
    """When nvidia-smi reports real numbers, vram_probe returns total/free in MiB."""
    import asyncio as _aio

    async def fake_create_subprocess_exec(*args, **kwargs):
        class _P:
            async def communicate(self):
                return (b"24576, 12000\n", b"")

        return _P()

    monkeypatch.setattr(_aio, "create_subprocess_exec", fake_create_subprocess_exec)
    # nvidia-smi must be "found" by shutil.which
    monkeypatch.setattr(
        "shutil.which", lambda name: "/usr/bin/nvidia-smi" if name == "nvidia-smi" else None
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/ps"
        return httpx.Response(200, json={"models": []})

    c = _client(handler, fake_settings)
    probe = await c.vram_probe()
    assert probe["total_mib"] == 24576
    assert probe["free_mib"] == 12000
    assert probe["unified"] is False
    assert probe["loaded"] == []
    await c.aclose()


@pytest.mark.asyncio
async def test_vram_probe_unified_when_smi_na(fake_settings, monkeypatch) -> None:
    """When nvidia-smi reports [N/A] (GB10 unified memory), probe returns None + unified=True."""
    import asyncio as _aio

    async def fake_create_subprocess_exec(*args, **kwargs):
        class _P:
            async def communicate(self):
                return (b"[N/A], [N/A]\n", b"")

        return _P()

    monkeypatch.setattr(_aio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(
        "shutil.which", lambda name: "/usr/bin/nvidia-smi" if name == "nvidia-smi" else None
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": [{"name": "x"}]})

    c = _client(handler, fake_settings)
    probe = await c.vram_probe()
    assert probe["total_mib"] is None
    assert probe["free_mib"] is None
    assert probe["unified"] is True
    assert probe["loaded"] == [{"name": "x"}]
    await c.aclose()


@pytest.mark.asyncio
async def test_vram_probe_unified_when_no_smi(fake_settings, monkeypatch) -> None:
    """When nvidia-smi is not installed, probe returns None + unified=True."""
    monkeypatch.setattr("shutil.which", lambda name: None)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": []})

    c = _client(handler, fake_settings)
    probe = await c.vram_probe()
    assert probe["total_mib"] is None
    assert probe["free_mib"] is None
    assert probe["unified"] is True
    await c.aclose()
