"""Unit tests for the Model Orchestrator (mocked Ollama/ComfyUI/vram)."""

from __future__ import annotations

import json
from collections.abc import Sequence

import pytest

from src.common.runs import RunDir
from src.optimizer.model_orchestrator import ModelOrchestrator, cache_key, effort_for


class MockOllama:
    def __init__(self) -> None:
        self.stops: list[str] = []

    async def stop(self, model: str) -> None:
        self.stops.append(model)

    async def aclose(self) -> None:
        pass


class MockComfyUI:
    def __init__(self, healthy: bool = True) -> None:
        self._h = healthy

    async def health(self) -> bool:
        return self._h

    async def aclose(self) -> None:
        pass


def _probe_seq(values: Sequence[float]):
    it = iter(values)

    def _p() -> float | None:
        try:
            return next(it)
        except StopIteration:
            return values[-1]

    return _p


def _orch(fake_settings, tmp_path, *, ollama=None, comfyui=None, probe=None, free_cf=None):
    run = RunDir(tmp_path / "runs", "test-orch-001").ensure()
    return run, ModelOrchestrator(
        run,
        settings=fake_settings,
        ollama=ollama or MockOllama(),
        comfyui=comfyui or MockComfyUI(),
        vram_probe=probe,
        free_comfyui=free_cf,
    )


@pytest.mark.asyncio
async def test_request_vram_comfyui_unloads_ollama(fake_settings, tmp_path) -> None:
    oll = MockOllama()
    run, orch = _orch(
        fake_settings,
        tmp_path,
        ollama=oll,
        comfyui=MockComfyUI(True),
        probe=_probe_seq([20.0, 96.0]),
    )
    res = await orch.request_vram("comfyui", reason="pre-generate")
    assert res.ok is True
    assert res.unloaded is True
    assert oll.stops == [fake_settings.ollama_reasoning_model]
    assert res.vram_before_gb == 20.0 and res.vram_after_gb == 96.0
    assert orch.state.value == "generating"
    await orch.aclose()


@pytest.mark.asyncio
async def test_request_vram_ollama_transitions_no_stop(fake_settings, tmp_path) -> None:
    oll = MockOllama()
    freed: list[int] = []

    async def free_cf() -> None:
        freed.append(1)

    run, orch = _orch(
        fake_settings, tmp_path, ollama=oll, probe=_probe_seq([96.0, 96.0]), free_cf=free_cf
    )
    res = await orch.request_vram("ollama", reason="post-generate-reason")
    assert res.ok is True
    assert res.unloaded is False
    assert oll.stops == []  # never unload when targeting ollama
    assert freed == [1]  # comfyui freed best-effort
    assert orch.state.value == "reasoning"
    await orch.aclose()


@pytest.mark.asyncio
async def test_inflight_guard_blocks_unload(fake_settings, tmp_path) -> None:
    oll = MockOllama()
    run, orch = _orch(fake_settings, tmp_path, ollama=oll, probe=_probe_seq([20.0, 96.0]))
    orch.begin_reasoning()
    res = await orch.request_vram("comfyui")
    orch.end_reasoning()
    assert oll.stops == []  # no stop issued while reasoning in flight
    assert res.unloaded is False
    assert "in flight" in res.reason
    await orch.aclose()


@pytest.mark.asyncio
async def test_orchestrator_log_records_events(fake_settings, tmp_path) -> None:
    run, orch = _orch(fake_settings, tmp_path, probe=_probe_seq([20.0, 96.0]))
    await orch.request_vram("comfyui", reason="pre-generate")
    data = json.loads(run.orchestrator_log_path().read_text())
    assert data["run_id"] == "test-orch-001"
    ev = data["events"][0]
    assert ev["action"] == "request_vram:comfyui"
    assert ev["vram_before_gb"] == 20.0 and ev["vram_after_gb"] == 96.0
    assert ev["latency_s"] is not None
    assert ev["reason"] == "pre-generate"
    await orch.aclose()


def test_effort_for_routing() -> None:
    assert effort_for("analyze") == "high"
    assert effort_for("plan") == "high"
    assert effort_for("critic", attempt=1) == "medium"
    assert effort_for("critic", attempt=2) == "low"
    assert effort_for("critic", attempt=3) == "low"


def test_cache_key_stable() -> None:
    a = cache_key("brief", b"\x01\x02")
    b = cache_key("brief", b"\x01\x02")
    c = cache_key("brief2", b"\x01\x02")
    assert a == b and a != c
