"""Model Orchestrator — GB10 unified-memory swap state machine (optimization O1).

Owns the Ollama↔ComfyUI swap, VLM effort routing (O3), and the evidence trail
(``orchestrator_log.json``) that the demo surfaces for the "model optimization depth"
rubric. The Art Director (CP-008) calls ``request_vram`` before each reasoning/render
stage and ``effort_for`` to set the VLM effort per call.

GB10 is a Grace-Blackwell iGPU with ~120 GiB unified memory; ``nvidia-smi`` reports
``[N/A]`` so swaps are driven from ``/proc/meminfo MemAvailable`` (see ``vram.py``).
The bundle serves Ollama with ``OLLAMA_KEEP_ALIVE=5s`` so an idle model frees memory
within 5 s; ``request_vram("comfyui")`` accelerates that with an explicit ``ollama stop``.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from enum import StrEnum

import structlog
from pydantic import BaseModel

from src.common.comfyui import ComfyUIClient
from src.common.config import Settings, get_settings
from src.common.ollama import OllamaClient
from src.common.runs import RunDir
from src.common.schemas import OrchestratorEvent
from src.common.vram import free_vram_gb

__all__ = ["ModelOrchestrator", "Stage", "SwapResult", "effort_for", "cache_key"]

_log = structlog.get_logger(__name__)

VramProbe = Callable[[], float | None]
FreeComfyUI = Callable[[], Awaitable[None]]


class Stage(StrEnum):
    IDLE = "idle"
    REASONING = "reasoning"
    GENERATING = "generating"


class SwapResult(BaseModel):
    ok: bool
    target: str
    vram_before_gb: float | None = None
    vram_after_gb: float | None = None
    latency_s: float = 0.0
    unloaded: bool = False
    reason: str = ""


def effort_for(stage: str, attempt: int = 1) -> str:
    """VLM ``reasoning_effort`` per call (O3)."""
    if stage == "analyze":
        return "high"
    if stage == "plan":
        return "high"
    if stage == "critic":
        return "medium" if attempt < 2 else "low"
    return "medium"


def cache_key(brief: str, image_bytes: bytes) -> str:
    """Brand-DNA cache key (O4) — same algorithm as ``brand_analyst.brand_dna_cache_key``."""
    import hashlib

    return hashlib.sha1(brief.encode("utf-8") + image_bytes).hexdigest()


class ModelOrchestrator:
    """Drives the unified-memory swap state machine and records the evidence trail."""

    def __init__(
        self,
        run_dir: RunDir,
        *,
        settings: Settings | None = None,
        ollama: OllamaClient | None = None,
        comfyui: ComfyUIClient | None = None,
        vram_probe: VramProbe | None = None,
        free_comfyui: FreeComfyUI | None = None,
    ) -> None:
        self._s = settings or get_settings()
        self._run_dir = run_dir
        self._owns_ollama = ollama is None
        self._owns_comfyui = comfyui is None
        self._ollama = ollama or OllamaClient(self._s)
        self._comfyui = comfyui or ComfyUIClient(self._s)
        self._vram_probe = vram_probe or free_vram_gb
        self._free_comfyui = free_comfyui
        self._state = Stage.IDLE
        self._reasoning_in_flight = 0
        self._events: list[OrchestratorEvent] = []
        self._sticky_backend: str | None = None  # CP-013: set when Ollama fails over to NIM
        self._log = _log.bind(agent="model_orchestrator", run_id=run_dir.run_id)

    # -- in-flight guard (never unload while reasoning) ---------------------- #
    def begin_reasoning(self) -> None:
        self._reasoning_in_flight += 1

    def end_reasoning(self) -> None:
        self._reasoning_in_flight = max(0, self._reasoning_in_flight - 1)

    @property
    def state(self) -> Stage:
        return self._state

    @property
    def events(self) -> list[OrchestratorEvent]:
        return list(self._events)

    # -- the swap ------------------------------------------------------------- #
    async def request_vram(self, target: str, *, reason: str = "") -> SwapResult:
        if target not in ("ollama", "comfyui"):
            raise ValueError(f"unknown vram target: {target!r}")
        t0 = time.perf_counter()
        before = self._vram_probe()
        unloaded = False
        ok = True
        block_reason = ""

        if target == "comfyui":
            if self._reasoning_in_flight > 0:
                block_reason = "reasoning in flight; unload deferred"
                self._log.warning(
                    "orchestrator.unload.blocked", in_flight=self._reasoning_in_flight
                )
            else:
                await self._ollama.stop(self._s.ollama_reasoning_model)
                unloaded = True
                await self._wait_free(
                    self._s.vram_free_threshold_gb, self._s.ollama_unload_timeout_s
                )
            ok = await self._comfyui.health()
            self._state = Stage.GENERATING
        else:  # "ollama" — best-effort free ComfyUI, then transition
            if self._free_comfyui is not None:
                try:
                    await self._free_comfyui()
                except Exception as exc:  # noqa: BLE001 — best-effort
                    self._log.warning("orchestrator.comfyui_free.failed", error=str(exc)[:120])
            self._state = Stage.REASONING

        await asyncio.sleep(0)  # yield so memory can settle
        after = self._vram_probe()
        latency = round(time.perf_counter() - t0, 3)
        result = SwapResult(
            ok=ok,
            target=target,
            vram_before_gb=before,
            vram_after_gb=after,
            latency_s=latency,
            unloaded=unloaded,
            reason=block_reason or reason,
        )
        self._record(
            action=f"request_vram:{target}",
            reason=block_reason or reason,
            vram_before_gb=before,
            vram_after_gb=after,
            latency_s=latency,
        )
        self._log.info(
            "orchestrator.swap",
            target=target,
            ok=ok,
            unloaded=unloaded,
            before_gb=before,
            after_gb=after,
            latency_s=latency,
        )
        return result

    async def _wait_free(self, threshold_gb: float, timeout_s: int) -> None:
        deadline = time.perf_counter() + timeout_s
        while time.perf_counter() < deadline:
            free = self._vram_probe()
            if free is not None and free >= threshold_gb:
                return
            await asyncio.sleep(1.0)
        self._log.warning("orchestrator.wait_free.timeout", threshold_gb=threshold_gb)

    # -- evidence trail ------------------------------------------------------- #
    def on_ollama_unavailable(self, *, reason: str = "") -> None:
        """CP-013: mark Ollama down — switch reasoning to NIM (sticky) for the run."""
        self._sticky_backend = "nim"
        self._record(action="reasoning:failover", backend="nim", reason=reason[:160])
        self._log.warning("orchestrator.ollama_unavailable", reason=reason[:120])

    def record_routing(
        self, backend: str, *, ok: bool, reason: str = "", failover: bool = False
    ) -> None:
        """Append a reasoning routing decision to the evidence trail (CP-013)."""
        action = "reasoning:failover" if failover else "reasoning"
        self._record(
            action=action,
            backend=backend,
            reason=reason[:160],
        )

    @property
    def sticky_backend(self) -> str | None:
        return self._sticky_backend

    def _record(
        self,
        *,
        action: str,
        reason: str = "",
        backend: str = "",
        vram_before_gb: float | None = None,
        vram_after_gb: float | None = None,
        latency_s: float | None = None,
    ) -> None:
        self._events.append(
            OrchestratorEvent(
                t=datetime.now(UTC),
                action=action,
                reason=reason,
                backend=backend,
                vram_before_gb=vram_before_gb,
                vram_after_gb=vram_after_gb,
                latency_s=latency_s,
            )
        )
        self._persist()

    def _persist(self) -> None:
        self._run_dir.path.mkdir(parents=True, exist_ok=True)
        payload = {
            "run_id": self._run_dir.run_id,
            "events": [e.model_dump(mode="json") for e in self._events],
        }
        import json

        self._run_dir.orchestrator_log_path().write_text(
            json.dumps(payload, indent=2, default=str), encoding="utf-8"
        )

    async def aclose(self) -> None:
        if self._owns_ollama:
            await self._ollama.aclose()
        if self._owns_comfyui:
            await self._comfyui.aclose()
