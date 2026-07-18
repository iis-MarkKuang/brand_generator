"""Async file-system helpers to avoid blocking the event loop.

fastapi-doctor flags sync file I/O inside async functions
(``correctness/sync-io-in-async``). These thin wrappers dispatch
the blocking call to a thread via :func:`asyncio.to_thread`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any


async def read_text(path: str | Path) -> str:
    return await asyncio.to_thread(Path(path).read_text)


async def write_text(path: str | Path, data: str) -> None:
    await asyncio.to_thread(Path(path).write_text, data)


async def read_bytes(path: str | Path) -> bytes:
    return await asyncio.to_thread(Path(path).read_bytes)


async def write_bytes(path: str | Path, data: bytes) -> None:
    await asyncio.to_thread(Path(path).write_bytes, data)


async def exists(path: str | Path) -> bool:
    return await asyncio.to_thread(lambda: Path(path).exists())


async def to_thread[T](func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Run a sync helper in a thread without blocking the event loop."""
    return await asyncio.to_thread(func, *args, **kwargs)
