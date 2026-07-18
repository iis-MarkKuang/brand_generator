"""Small HTTP helper: retry transient failures with exponential backoff.

Shared by the Stepfun / Ollama / ComfyUI / NIM clients so they all apply the
same policy on 5xx and timeouts. 4xx responses are never retried — they signal
a caller bug (bad payload, auth, not-found) and must surface immediately.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import structlog

__all__ = ["retry_transient"]

_log = structlog.get_logger(__name__)


async def retry_transient(
    call: Callable[[], Awaitable[httpx.Response]],
    *,
    retries: int = 3,
    base_delay: float = 0.5,
    label: str = "http",
    log: structlog.stdlib.BoundLogger | None = None,
) -> httpx.Response:
    """Await ``call`` and retry on 5xx / timeout, else re-raise immediately.

    ``call`` is expected to raise ``HTTPStatusError`` via ``raise_for_status``
    so that status codes are inspectable here.
    """
    logger = log or _log
    last_exc: BaseException | None = None
    for attempt in range(retries + 1):
        try:
            return await call()
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            status = exc.response.status_code
            if 500 <= status < 600 and attempt < retries:
                delay = base_delay * (2**attempt)
                logger.warning(
                    "http.retry",
                    label=label,
                    attempt=attempt + 1,
                    status=status,
                    delay_s=delay,
                )
                await asyncio.sleep(delay)
                continue
            raise
        except httpx.TimeoutException as exc:
            last_exc = exc
            if attempt < retries:
                delay = base_delay * (2**attempt)
                logger.warning(
                    "http.retry",
                    label=label,
                    attempt=attempt + 1,
                    delay_s=delay,
                )
                await asyncio.sleep(delay)
                continue
            raise
    # Unreachable: the loop either returns or raises on the final attempt.
    if last_exc is not None:
        raise last_exc  # pragma: no cover
    raise RuntimeError("retry_transient: exhausted retries with no exception captured")


def json_body(resp: httpx.Response) -> dict[str, Any]:
    """Parse a JSON object body, raising ``ValueError`` on non-object shapes."""
    data = resp.json()
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object, got {type(data).__name__}")
    return data
