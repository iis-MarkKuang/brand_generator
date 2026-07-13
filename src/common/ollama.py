"""Async Ollama client for the local DGX Spark LLM backend.

Exposes ``chat`` (honouring the workshop ``think=False`` quirk so the answer
lands in ``message.content``), ``stop`` (unloads a model — the unified-memory
swap the Model Orchestrator relies on), ``ps`` (loaded models), and
``vram_probe`` (best-effort memory probe; on the GB10 iGPU ``nvidia-smi``
reports ``[N/A]`` because memory is unified, so callers should treat
``unified=True`` authoritatively).
"""

from __future__ import annotations

import asyncio
import shutil
import time
from typing import Any, cast

import httpx
import structlog

from src.common._http import retry_transient
from src.common.config import Settings
from src.common.exceptions import OllamaError

__all__ = ["OllamaClient"]

_log = structlog.get_logger(__name__)


class OllamaClient:
    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._s = settings
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(120.0))
        self._owns_client = client is None
        self._log = _log.bind(backend="ollama")

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _post(self, path: str, payload: dict[str, Any], *, label: str) -> dict[str, Any]:
        url = f"{self._s.ollama_host}{path}"

        async def _call() -> httpx.Response:
            r = await self._client.post(url, json=payload)
            r.raise_for_status()
            return r

        try:
            resp = await retry_transient(_call, retries=2, label=label, log=self._log)
        except httpx.HTTPError as exc:
            raise OllamaError(f"ollama {label} failed: {exc}") from exc
        return cast(dict[str, Any], resp.json())

    async def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        think: bool = False,
    ) -> str:
        """One-shot chat. With ``think=False`` the answer is in ``message.content``.

        Reasoning models otherwise place output in ``message.thinking`` and leave
        ``content`` empty (workshop §1.3 quirk); agents therefore default to
        ``think=False`` for structured-output calls.
        """
        t0 = time.perf_counter()
        body = await self._post(
            "/api/chat",
            {"model": model, "messages": messages, "stream": False, "think": think},
            label="chat",
        )
        dt = time.perf_counter() - t0
        content = (body.get("message") or {}).get("content", "")
        self._log.info(
            "ollama.chat.done",
            model=model,
            think=think,
            latency_s=round(dt, 3),
            prompt_eval_count=body.get("prompt_eval_count"),
            eval_count=body.get("eval_count"),
        )
        return cast(str, content)

    async def stop(self, model: str) -> None:
        """Unload a model from memory (``keep_alive=0``) — frees unified memory."""
        await self._post("/api/generate", {"model": model, "keep_alive": 0}, label="stop")
        self._log.info("ollama.stop", model=model)

    async def ps(self) -> list[dict[str, Any]]:
        """Return currently loaded models (``/api/ps``)."""
        try:
            r = await self._client.get(f"{self._s.ollama_host}/api/ps")
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise OllamaError(f"ollama ps failed: {exc}") from exc
        return list(r.json().get("models", []))

    async def vram_probe(self) -> dict[str, Any]:
        """Best-effort memory probe.

        On the GB10 Grace-Blackwell iGPU, ``nvidia-smi`` memory queries return
        ``[N/A]`` (memory is unified with the CPU pool). In that case
        ``total_mib``/``free_mib`` are ``None`` and ``unified`` is ``True``;
        callers (the Model Orchestrator) should then drive swaps from ``ps()``
        and the stage state machine rather than raw byte counts.
        """
        loaded = await self.ps()
        total: int | None = None
        free: int | None = None
        smi = shutil.which("nvidia-smi")
        if smi:
            try:
                proc = await asyncio.create_subprocess_exec(
                    smi,
                    "--query-gpu=memory.total,memory.free",
                    "--format=csv,noheader,nounits",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                out, _ = await proc.communicate()
                lines = [
                    ln.strip() for ln in out.decode(errors="replace").splitlines() if ln.strip()
                ]
                if lines:
                    parts = [p.strip() for p in lines[0].split(",")]
                    if (
                        len(parts) >= 2
                        and parts[0] not in ("", "[N/A]")
                        and parts[1] not in ("", "[N/A]")
                    ):
                        total, free = int(parts[0]), int(parts[1])
            except (ValueError, OSError):
                pass
        return {
            "total_mib": total,
            "free_mib": free,
            "unified": total is None,
            "loaded": loaded,
        }
