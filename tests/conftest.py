"""Shared pytest fixtures.

``fake_settings`` builds a ``Settings`` instance without touching ``.env`` so
unit tests stay isolated from real secrets. Live smoke scripts (run manually
on the Spark) load the real ``.env`` via ``get_settings()`` instead.
"""

from __future__ import annotations

import pytest

from src.common.config import Settings


@pytest.fixture
def fake_settings() -> Settings:
    return Settings(
        _env_file=None,
        stepfun_api_key="sk-test-key",
        nvidia_api_key="nv-test-key",
        hf_token="hf-test-key",
        telegram_bot_token="tg-test-key",
        critic_deep_reasoning=False,  # CP-017: disable deep chain in unit tests
    )
