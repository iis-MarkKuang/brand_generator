"""Unit tests for the Stepfun client + image helpers (mocked transport)."""

from __future__ import annotations

import io
import json
from pathlib import Path

import httpx
import pytest
from PIL import Image

from src.common.exceptions import VlmJsonError
from src.common.stepfun import (
    StepfunClient,
    bytes_to_data_url,
    image_to_data_url,
    resize_for_vlm,
)


def _completion(content: str) -> dict[str, object]:
    return {
        "id": "chatcmpl-x",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


def _client(handler, fake_settings) -> StepfunClient:
    transport = httpx.MockTransport(handler)
    return StepfunClient(fake_settings, httpx.AsyncClient(transport=transport))


@pytest.mark.asyncio
async def test_chat_vlm_parses_json(fake_settings) -> None:
    payload = {"brand_name": "Acme", "tagline": "Build the future"}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        body = json.loads(request.content)
        assert body["model"] == fake_settings.stepfun_vlm_model
        assert body["reasoning_effort"] == "high"
        # image_detail must be injected onto image parts
        for m in body["messages"]:
            for p in (m.get("content") or []) if isinstance(m.get("content"), list) else []:
                if isinstance(p, dict) and p.get("type") == "image_url":
                    assert p["image_url"]["detail"] == "high"
        return httpx.Response(200, json=_completion(json.dumps(payload)))

    c = _client(handler, fake_settings)
    msgs = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Return JSON describing the brand."},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
            ],
        }
    ]
    result = await c.chat_vlm(msgs, reasoning_effort="high", image_detail="high")
    assert result == payload
    await c.aclose()


@pytest.mark.asyncio
async def test_chat_vlm_repair_retry_then_fail(fake_settings) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, json=_completion("Sure! The brand is Acme."))
        return httpx.Response(200, json=_completion("not json either"))

    c = _client(handler, fake_settings)
    with pytest.raises(VlmJsonError):
        await c.chat_vlm([{"role": "user", "content": "give json"}])
    assert calls["n"] == 2  # initial + one repair
    await c.aclose()


@pytest.mark.asyncio
async def test_chat_vlm_recovers_via_repair(fake_settings) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, json=_completion('Here you go: {"k": 1}'))
        return httpx.Response(200, json=_completion('{"k": 1}'))

    c = _client(handler, fake_settings)
    assert await c.chat_vlm([{"role": "user", "content": "give json"}]) == {"k": 1}
    await c.aclose()


def test_resize_for_vlm_downscales(tmp_path: Path) -> None:
    big = tmp_path / "big.png"
    with Image.new("RGB", (4096, 2048), (10, 20, 30)) as im:
        im.save(big, format="PNG")
    out = resize_for_vlm(big, max_side=1024)
    with Image.open(io.BytesIO(out)) as im:
        w, h = im.size
    assert max(w, h) <= 1024
    assert out.startswith(b"\x89PNG")


def test_resize_for_vlm_no_upscale(tmp_path: Path) -> None:
    small = tmp_path / "small.png"
    with Image.new("RGB", (300, 200), (1, 2, 3)) as im:
        im.save(small, format="PNG")
    with Image.open(io.BytesIO(resize_for_vlm(small, max_side=1024))) as im:
        assert im.size == (300, 200)


def test_image_to_data_url(tmp_path: Path) -> None:
    p = tmp_path / "x.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n")
    url = image_to_data_url(p)
    assert url.startswith("data:image/png;base64,")


def test_bytes_to_data_url() -> None:
    assert bytes_to_data_url(b"hi", "image/png") == "data:image/png;base64,aGk="
