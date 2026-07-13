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
