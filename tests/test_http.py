"""Unit tests for the shared HTTP retry helper (5xx/timeout retry, 4xx no-retry)."""

from __future__ import annotations

import httpx
import pytest

from src.common._http import retry_transient


def _status_handler(statuses: list[int]) -> httpx.MockTransport:
    """Return a transport that responds with statuses[i] on the i-th call."""
    idx = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        i = idx["n"]
        idx["n"] += 1
        s = statuses[i] if i < len(statuses) else statuses[-1]
        return httpx.Response(s, text=f"resp-{i}")

    return httpx.MockTransport(handler)


async def _call(transport: httpx.MockTransport) -> httpx.Response:
    client = httpx.AsyncClient(transport=transport)
    try:

        async def _do() -> httpx.Response:
            r = await client.get("http://test/x")
            r.raise_for_status()
            return r

        return await retry_transient(
            _do,
            retries=3,
            base_delay=0.001,  # keep tests fast
            label="test",
        )
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_retry_succeeds_after_5xx() -> None:
    """A 500 then 200 → retried once, returns the 200 body."""
    transport = _status_handler([500, 200])
    resp = await _call(transport)
    assert resp.status_code == 200
    assert "resp-1" in resp.text


@pytest.mark.asyncio
async def test_retry_exhausts_on_all_5xx() -> None:
    """All 503s → retries `retries` times then re-raises HTTPStatusError."""
    transport = _status_handler([503, 503, 503, 503])
    with pytest.raises(httpx.HTTPStatusError) as exc:
        await _call(transport)
    assert exc.value.response.status_code == 503


@pytest.mark.asyncio
async def test_no_retry_on_4xx() -> None:
    """A 404 is a caller bug → never retried, raised immediately."""
    idx = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        idx["n"] += 1
        return httpx.Response(404, text="not found")

    transport = httpx.MockTransport(handler)
    with pytest.raises(httpx.HTTPStatusError):
        await _call(transport)
    assert idx["n"] == 1  # exactly one attempt, no retry


@pytest.mark.asyncio
async def test_retry_on_timeout_then_success() -> None:
    """A timeout then a 200 → retried, returns 200."""
    idx = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        idx["n"] += 1
        if idx["n"] == 1:
            raise httpx.TimeoutException("timed out")
        return httpx.Response(200, text="ok")

    transport = httpx.MockTransport(handler)
    resp = await _call(transport)
    assert resp.status_code == 200
    assert idx["n"] == 2


@pytest.mark.asyncio
async def test_retry_exhausts_on_timeout() -> None:
    """Always times out → re-raises TimeoutException after `retries` attempts."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out")

    transport = httpx.MockTransport(handler)
    with pytest.raises(httpx.TimeoutException):
        await _call(transport)
