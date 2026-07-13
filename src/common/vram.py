"""Unified-memory (VRAM) probing helpers for the GB10 Grace-Blackwell iGPU.

The GB10 is an integrated GPU sharing ~120 GiB of unified memory with the CPU.
``nvidia-smi`` reports memory as ``[N/A]`` for unified pools, so the reliable free
figure is ``/proc/meminfo MemAvailable``. These helpers centralize that probe so the
Model Orchestrator and the Generator share one source of truth.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["free_vram_mib", "free_vram_gb"]


def free_vram_mib() -> int | None:
    """Free unified memory in MiB, or ``None`` if unreadable."""
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def free_vram_gb() -> float | None:
    mib = free_vram_mib()
    return None if mib is None else round(mib / 1024.0, 2)
