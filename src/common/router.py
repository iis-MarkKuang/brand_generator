"""Local<->cloud reasoning router (CP-013, optimization O6).

Picks a reasoning backend for the Art Director's text-only planning/rewrite calls:
local Ollama (Nemotron) by default, failing over to NVIDIA NIM cloud
(``integrate.api.nvidia.com``) when Ollama is unavailable or overloaded. The
failover is **sticky** for the rest of the run: once Ollama is down we keep
routing to NIM rather than retrying the broken local backend on every call.

Strategy (``ROUTING_STRATEGY``):
- ``local-first``  — Ollama primary, NIM fallback (default; preserves the
  "local compute" hackathon narrative — cloud is *failover*, not the default).
- ``cloud-first``  — NIM primary, Ollama fallback.
- ``local-only``   — Ollama only; no cloud fallback (fails loud).

The router is duck-type-compatible with ``OllamaClient.chat`` so the Art
Director can accept either transparently (see ``ReasonClient`` Protocol). It
records every routing decision (for the evidence trail / ``orchestrator_log.json``
via the Model Orchestrator hook) and never sends images to NIM — reasoning is
text-only; vision stays with Stepfun.

NIM Nemotron reasoning quirk (verified CP-002): ``nvidia/llama-3.3-nemotron-super-49b-v1.5``
is a reasoning model — ``message.content`` is ``null`` and the answer lives in
``message.reasoning_content``. ``_extract_nim_content`` handles both.
"""

from __future__ import annotations

import contextlib
import time
from typing import Any, Protocol, cast

import structlog

from src.common.config import Settings, get_settings
from src.common.exceptions import NimError, OllamaError
from src.common.nvidia_nim import NimClient
from src.common.ollama import OllamaClient

__all__ = ["ReasonRouter", "ReasonClient"]

_log = structlog.get_logger(__name__)


class ReasonClient(Protocol):
    """Minimal chat interface both ``OllamaClient`` and ``ReasonRouter`` satisfy."""

    async def chat(
        self, model: str, messages: list[dict[str, Any]], *, think: bool = False
    ) -> str: ...

    async def aclose(self) -> None: ...


class ReasonRouter:
    """Strategy-driven local<->cloud reasoning router with sticky failover."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        ollama: OllamaClient | None = None,
        nim: NimClient | None = None,
        on_routing: Any = None,
    ) -> None:
        self._s = settings or get_settings()
        self._owns_ollama = ollama is None
        self._owns_nim = nim is None
        self._ollama = ollama or OllamaClient(self._s)
        self._nim = nim or NimClient(self._s)
        self._on_routing = on_routing  # callable(backend, *, ok, reason, failover) | None
        self._sticky: str | None = None
        self.decisions: list[dict[str, Any]] = []
        self._log = _log.bind(component="reason_router")

    async def chat(self, model: str, messages: list[dict[str, Any]], *, think: bool = False) -> str:
        primary, secondary = self._order()
        t0 = time.perf_counter()
        try:
            content, backend = await self._invoke(primary, model, messages, think)
        except (OllamaError, NimError) as exc:
            if secondary is None:
                self._record(primary, ok=False, reason=str(exc)[:160], failover=False)
                raise
            # failover (sticky for the rest of the run)
            self._sticky = secondary
            self._record(primary, ok=False, reason=str(exc)[:160], failover=True)
            self._log.warning(
                "router.failover", primary=primary, secondary=secondary, error=str(exc)[:120]
            )
            content, backend = await self._invoke(secondary, model, messages, think)
            self._record(backend, ok=True, reason="failover", failover=True)
            return content

        self._record(backend, ok=True, failover=False)
        self._log.debug(
            "router.chat", backend=backend, latency_s=round(time.perf_counter() - t0, 3)
        )
        return content

    def _order(self) -> tuple[str, str | None]:
        if self._sticky:
            return self._sticky, None
        strat = self._s.routing_strategy
        if strat == "cloud-first":
            return "nim", "ollama"
        if strat == "local-only":
            return "ollama", None
        return "ollama", "nim"  # local-first

    async def _invoke(
        self, backend: str, model: str, messages: list[dict[str, Any]], think: bool
    ) -> tuple[str, str]:
        if backend == "nim":
            body = await self._nim.chat(messages=messages)
            return self._extract_nim_content(body), "nim"
        return await self._ollama.chat(model, messages, think=think), "ollama"

    @staticmethod
    def _extract_nim_content(body: dict[str, Any]) -> str:
        choices = body.get("choices") or []
        if not choices:
            raise NimError("nim: no choices in response")
        msg = choices[0].get("message") or {}
        content = msg.get("content") or ""
        if not content:
            # reasoning-model quirk: answer in reasoning_content when content is null
            content = msg.get("reasoning_content") or ""
        if not content:
            raise NimError("nim: empty content and reasoning_content")
        return cast(str, content)

    def _record(self, backend: str, *, ok: bool, reason: str = "", failover: bool = False) -> None:
        entry = {"backend": backend, "ok": ok, "reason": reason, "failover": failover}
        self.decisions.append(entry)
        if self._on_routing is not None:
            with contextlib.suppress(Exception):  # evidence trail must never break the run
                self._on_routing(backend, ok=ok, reason=reason, failover=failover)

    @property
    def sticky_backend(self) -> str | None:
        return self._sticky

    async def aclose(self) -> None:
        if self._owns_ollama:
            await self._ollama.aclose()
        if self._owns_nim:
            await self._nim.aclose()
