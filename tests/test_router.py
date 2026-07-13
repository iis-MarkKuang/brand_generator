"""Acceptance tests for the CP-013 local<->cloud reasoning router."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from src.common.config import Settings
from src.common.exceptions import NimError, OllamaError
from src.common.nvidia_nim import NimClient
from src.common.ollama import OllamaClient
from src.common.router import ReasonRouter


def _settings(strategy: str = "local-first") -> Settings:
    return Settings(
        _env_file=None,
        stepfun_api_key="x",
        nvidia_api_key="nvapi-test",
        hf_token="hf-test",
        telegram_bot_token="tg-test",
        routing_strategy=strategy,
    )


def _ollama_ok(content: str = "OK") -> OllamaClient:
    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, json={"message": {"content": content}})
    )
    s = _settings()
    return OllamaClient(s, client=httpx.AsyncClient(transport=transport))


def _ollama_down() -> OllamaClient:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("ollama down", request=req)

    return OllamaClient(
        _settings(), client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


def _nim_ok(content: str | None, reasoning: str | None = None) -> NimClient:
    msg: dict[str, Any] = {}
    if content is not None:
        msg["content"] = content
    else:
        msg["content"] = None
    if reasoning is not None:
        msg["reasoning_content"] = reasoning
    body = {"choices": [{"message": msg}]}
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=body))
    return NimClient(_settings(), client=httpx.AsyncClient(transport=transport))


def _nim_down() -> NimClient:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nim down", request=req)

    return NimClient(_settings(), client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


@pytest.mark.asyncio
async def test_local_ok_uses_ollama_and_skips_nim() -> None:
    router = ReasonRouter(_settings(), ollama=_ollama_ok("PLAN"), nim=_nim_ok("NIM"))
    out = await router.chat("model", [{"role": "user", "content": "hi"}])
    assert out == "PLAN"
    assert router.decisions[-1] == {
        "backend": "ollama",
        "ok": True,
        "reason": "",
        "failover": False,
    }
    await router.aclose()


@pytest.mark.asyncio
async def test_local_down_fails_over_to_nim_sticky() -> None:
    router = ReasonRouter(
        _settings(), ollama=_ollama_down(), nim=_nim_ok(None, reasoning="NIM_ANSWER")
    )
    out = await router.chat("model", [{"role": "user", "content": "hi"}])
    assert out == "NIM_ANSWER"  # extracted from reasoning_content
    # first decision records the failed local attempt; second records the nim success
    assert router.decisions[0]["backend"] == "ollama" and router.decisions[0]["ok"] is False
    assert router.decisions[0]["failover"] is True
    assert router.decisions[1]["backend"] == "nim" and router.decisions[1]["ok"] is True
    assert router.sticky_backend == "nim"
    await router.aclose()


@pytest.mark.asyncio
async def test_local_only_never_calls_nim() -> None:
    router = ReasonRouter(
        _settings("local-only"), ollama=_ollama_down(), nim=_nim_ok("SHOULD_NOT_HAPPEN")
    )
    with pytest.raises(OllamaError):
        await router.chat("model", [{"role": "user", "content": "hi"}])
    # nim was never consulted — only one (failed) local decision recorded
    assert len(router.decisions) == 1
    assert all(d["backend"] == "ollama" for d in router.decisions)
    await router.aclose()


@pytest.mark.asyncio
async def test_cloud_first_uses_nim_primary() -> None:
    router = ReasonRouter(_settings("cloud-first"), ollama=_ollama_ok("OLLAMA"), nim=_nim_ok("NIM"))
    out = await router.chat("model", [{"role": "user", "content": "hi"}])
    assert out == "NIM"
    assert router.decisions[-1]["backend"] == "nim"
    await router.aclose()


@pytest.mark.asyncio
async def test_nim_content_extracted_from_reasoning_when_null() -> None:
    # reasoning model quirk: content is null, answer in reasoning_content
    body = {"choices": [{"message": {"content": None, "reasoning_content": "THE_ANSWER"}}]}
    assert ReasonRouter._extract_nim_content(body) == "THE_ANSWER"


@pytest.mark.asyncio
async def test_nim_empty_content_and_reasoning_raises() -> None:
    body = {"choices": [{"message": {"content": None, "reasoning_content": None}}]}
    with pytest.raises(NimError):
        ReasonRouter._extract_nim_content(body)


@pytest.mark.asyncio
async def test_routing_recorded_to_orchestrator_log(tmp_path) -> None:
    """orchestrator_log.json carries a `backend` field on reasoning events."""
    from src.common.runs import RunDir
    from src.optimizer.model_orchestrator import ModelOrchestrator

    rd = RunDir(str(tmp_path), "rid").ensure()
    cc_transport = httpx.MockTransport(lambda req: httpx.Response(200, json={"status": "ok"}))
    from src.common.comfyui import ComfyUIClient

    orch = ModelOrchestrator(
        rd,
        settings=_settings(),
        ollama=_ollama_down(),
        comfyui=ComfyUIClient(_settings(), client=httpx.AsyncClient(transport=cc_transport)),
    )
    router = ReasonRouter(
        _settings(),
        ollama=_ollama_down(),
        nim=_nim_ok(None, reasoning="ANS"),
        on_routing=orch.record_routing,
    )
    await router.chat("model", [{"role": "user", "content": "hi"}])
    log = json.loads(rd.orchestrator_log_path().read_text())
    reasoning = [e for e in log["events"] if e["action"].startswith("reasoning")]
    assert reasoning, "no reasoning event recorded"
    assert any(e.get("backend") == "nim" for e in reasoning)
    await router.aclose()
    await orch.aclose()
