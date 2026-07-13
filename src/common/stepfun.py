"""Async Stepfun (阶跃星辰) client — OpenAI-compatible VLM + text.

Agents call ``chat_vlm`` to get a parsed JSON object back from the vision
model; the client enforces strict-JSON prompting and one repair retry. Image
helpers pre-resize and encode images so callers never handle raw bytes and we
can bound the number of tokens sent upstream (token-budget control T3, see
``references/design/07-security-and-tokens.md``).
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import time
from pathlib import Path
from typing import Any, cast

import httpx
import structlog
from PIL import Image

from src.common._http import retry_transient
from src.common.config import Settings
from src.common.exceptions import StepfunError, VlmJsonError

__all__ = [
    "StepfunClient",
    "image_to_data_url",
    "bytes_to_data_url",
    "resize_for_vlm",
]

_log = structlog.get_logger(__name__)

_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


# --------------------------------------------------------------------------- #
# Image helpers
# --------------------------------------------------------------------------- #
def bytes_to_data_url(data: bytes, mime: str = "image/png") -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def image_to_data_url(path: str | Path) -> str:
    """Encode an on-disk image as a ``data:`` URL (no resizing)."""
    p = Path(path)
    mime = _MIME.get(p.suffix.lower(), "application/octet-stream")
    return bytes_to_data_url(p.read_bytes(), mime)


def resize_for_vlm(path: str | Path, max_side: int = 1024) -> bytes:
    """Downscale an image so its longest side is ``max_side`` px; return PNG bytes.

    Upscaling is never performed. Used before encoding to bound VLM tokens (T3).
    """
    with Image.open(path) as raw:
        im: Image.Image = raw.convert("RGB")
        w, h = im.size
        scale = max_side / max(w, h)
        if scale < 1.0:
            im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))))
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        return buf.getvalue()


def _image_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:12]


def _ensure_image_detail(messages: list[dict[str, Any]], detail: str) -> list[dict[str, Any]]:
    """Set ``image_url.detail`` on every vision part that did not specify one."""
    out: list[dict[str, Any]] = []
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            new_parts: list[dict[str, Any]] = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    iu = dict(part.get("image_url", {}))
                    iu.setdefault("detail", detail)
                    new_parts.append({**part, "image_url": iu})
                else:
                    new_parts.append(part)
            out.append({**msg, "content": new_parts})
        else:
            out.append(msg)
    return out


def _extract_content(body: dict[str, Any]) -> str:
    try:
        msg = body["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as err:
        raise StepfunError(f"stepfun response missing choices/message: {body!r}") from err
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"
        )
    return ""


_OBJ_RE = re.compile(r"\{.*\}", re.S)


def _parse_json_object(text: str) -> dict[str, Any] | None:
    try:
        v = json.loads(text)
    except json.JSONDecodeError:
        m = _OBJ_RE.search(text)
        if not m:
            return None
        try:
            v = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return v if isinstance(v, dict) else None


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #
class StepfunClient:
    """Async OpenAI-compatible client for Stepfun (VLM + text)."""

    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._s = settings
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(60.0))
        self._owns_client = client is None
        self._log = _log.bind(backend="stepfun")

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        reasoning_effort: str | None = "high",
        **extra: Any,
    ) -> dict[str, Any]:
        """Raw chat completion. Returns the parsed JSON response body."""
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            **extra,
        }
        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort
        url = f"{self._s.stepfun_base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self._s.stepfun_api_key}"}
        t0 = time.perf_counter()

        async def _call() -> httpx.Response:
            r = await self._client.post(url, json=payload, headers=headers)
            r.raise_for_status()
            return r

        try:
            resp = await retry_transient(_call, retries=3, label="stepfun.chat", log=self._log)
        except httpx.HTTPError as exc:
            raise StepfunError(f"stepfun chat failed: {exc}") from exc

        body = cast(dict[str, Any], resp.json())
        dt = time.perf_counter() - t0
        usage = body.get("usage") or {}
        # Never log image bytes; log a content hash + size instead (constraint).
        self._log.info(
            "stepfun.chat.done",
            model=model,
            latency_s=round(dt, 3),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )
        return body

    async def chat_vlm(
        self,
        messages: list[dict[str, Any]],
        *,
        reasoning_effort: str = "high",
        image_detail: str = "high",
    ) -> dict[str, Any]:
        """Send a VLM request and return the parsed JSON object from the reply.

        Ensures every image part carries a ``detail`` tier (token-budget T3),
        then asks the model for strict JSON. If the first reply is not parseable
        JSON, performs a single low-effort repair retry before raising
        ``VlmJsonError``.
        """
        enriched = _ensure_image_detail(messages, image_detail)
        body = await self.chat(
            model=self._s.stepfun_vlm_model,
            messages=enriched,
            reasoning_effort=reasoning_effort,
        )
        content = _extract_content(body)
        parsed = _parse_json_object(content)
        if parsed is not None:
            return parsed

        self._log.warning("stepfun.vlm.json_repair", content_preview=content[:200])
        repair = enriched + [
            {"role": "assistant", "content": content},
            {
                "role": "user",
                "content": "Return ONLY valid minified JSON. No prose, no code fences.",
            },
        ]
        body2 = await self.chat(
            model=self._s.stepfun_vlm_model,
            messages=repair,
            reasoning_effort="low",
            image_detail="low",
        )
        parsed = _parse_json_object(_extract_content(body2))
        if parsed is None:
            raise VlmJsonError("stepfun VLM did not return parseable JSON")
        return parsed
