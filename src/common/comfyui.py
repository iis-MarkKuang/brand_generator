"""Async ComfyUI client — submit a workflow, poll history, fetch outputs.

This is transport only: it does not build workflows (CP-005) nor parse node
graphs. Callers pass a serialized ComfyUI prompt graph (dict of node_id ->
node_spec) and receive back the rendered image bytes.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, cast

import httpx
import structlog

from src.common._http import retry_transient
from src.common.config import Settings
from src.common.exceptions import ComfyUIError

__all__ = ["ComfyUIClient"]

_log = structlog.get_logger(__name__)

_PNG_SIG = b"\x89PNG\r\n\x1a\n"


class ComfyUIClient:
    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._s = settings
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(30.0))
        self._owns_client = client is None
        self._log = _log.bind(backend="comfyui")

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def health(self) -> bool:
        try:
            r = await self._client.get(f"{self._s.comfyui_host}/api/system_stats")
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    async def submit(self, workflow: dict[str, Any]) -> str:
        """POST /prompt -> return the ``prompt_id`` assigned by ComfyUI."""
        url = f"{self._s.comfyui_host}/prompt"

        async def _call() -> httpx.Response:
            r = await self._client.post(url, json={"prompt": workflow})
            r.raise_for_status()
            return r

        try:
            resp = await retry_transient(_call, retries=2, label="comfyui.submit", log=self._log)
        except httpx.HTTPError as exc:
            raise ComfyUIError(f"comfyui submit failed: {exc}") from exc
        body = cast(dict[str, Any], resp.json())
        pid = body.get("prompt_id")
        if not pid:
            raise ComfyUIError(f"comfyui submit returned no prompt_id: {body!r}")
        self._log.info("comfyui.submit.ok", prompt_id=pid, nodes=len(workflow))
        return cast(str, pid)

    async def wait(self, prompt_id: str, timeout: float = 300.0) -> dict[str, Any]:
        """Poll /history/{id} until the run's outputs are ready; return the entry.

        Raises ``ComfyUIError`` on backend error or timeout.
        """
        url = f"{self._s.comfyui_host}/history/{prompt_id}"
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            try:
                r = await self._client.get(url)
            except httpx.HTTPError as exc:
                raise ComfyUIError(f"comfyui poll failed: {exc}") from exc
            if r.status_code == 200:
                hist = r.json()
                entry = hist.get(prompt_id)
                if entry is not None:
                    status = (entry.get("status") or {}).get("status_str")
                    if status == "error":
                        msgs = (entry.get("status") or {}).get("messages")
                        raise ComfyUIError(f"comfyui prompt {prompt_id} errored: {msgs!r}")
                    if entry.get("outputs") is not None:
                        self._log.info("comfyui.wait.done", prompt_id=prompt_id)
                        return cast(dict[str, Any], entry)
            await asyncio.sleep(1.0)
        raise ComfyUIError(f"comfyui wait timeout for prompt {prompt_id}")

    async def fetch_image(
        self,
        filename: str,
        subfolder: str = "",
        folder_type: str = "output",
    ) -> bytes:
        """GET /view -> raw image bytes for one output artifact."""
        params = {"filename": filename, "subfolder": subfolder, "type": folder_type}
        try:
            r = await self._client.get(f"{self._s.comfyui_host}/view", params=params)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise ComfyUIError(f"comfyui fetch failed: {exc}") from exc
        data = r.content
        if not data.startswith(_PNG_SIG):
            # ComfyUI may emit JPEG/WebP; we only warn, callers decide.
            self._log.warning(
                "comfyui.fetch.unexpected_format", filename=filename, head=data[:8].hex()
            )
        return data
