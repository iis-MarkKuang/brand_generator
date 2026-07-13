"""Async NVIDIA NIM (cloud) client — OpenAI-compatible.

Used by CP-013 local↔cloud routing as the cloud fallback for reasoning when
the local Ollama model is unavailable or the queue is saturated. Held behind
the single secrets boundary: only the orchestrator imports this.
"""

from __future__ import annotations

import time
from typing import Any, cast

import httpx
import structlog

from src.common._http import retry_transient
from src.common.config import Settings
from src.common.exceptions import NimError

__all__ = ["NimClient"]

_log = structlog.get_logger(__name__)


class NimClient:
    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._s = settings
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(60.0))
        self._owns_client = client is None
        self._log = _log.bind(backend="nim")

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def chat(
        self,
        *,
        model: str | None = None,
        messages: list[dict[str, Any]],
        **extra: Any,
    ) -> dict[str, Any]:
        """Raw chat completion against ``integrate.api.nvidia.com``."""
        payload: dict[str, Any] = {
            "model": model or self._s.nvidia_nim_model,
            "messages": messages,
            "stream": False,
            **extra,
        }
        url = f"{self._s.nvidia_nim_base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self._s.nvidia_api_key}"}
        t0 = time.perf_counter()

        async def _call() -> httpx.Response:
            r = await self._client.post(url, json=payload, headers=headers)
            r.raise_for_status()
            return r

        try:
            resp = await retry_transient(_call, retries=3, label="nim.chat", log=self._log)
        except httpx.HTTPError as exc:
            raise NimError(f"nim chat failed: {exc}") from exc

        body = cast(dict[str, Any], resp.json())
        dt = time.perf_counter() - t0
        usage = body.get("usage") or {}
        self._log.info(
            "nim.chat.done",
            model=payload["model"],
            latency_s=round(dt, 3),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )
        return body
