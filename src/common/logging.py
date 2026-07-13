"""Structured logging setup.

Never logs secrets. `sanitize()` strips any value matching the known secret keys so a
stray `**kwargs` never leaks a key into the log stream (defense in depth for S5).
"""

from __future__ import annotations

import logging
import os
from typing import Any

import structlog

_SECRET_KEYS = (
    "STEPFUN_API_KEY",
    "NVIDIA_API_KEY",
    "HF_TOKEN",
    "TELEGRAM_BOT_TOKEN",
    "OLLAMA_API_KEY",
)
_REDACTED = "***REDACTED***"


def sanitize(_logger: Any, _method: Any, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Structlog processor: redact any secret-keyed or secret-valued fields."""
    secret_values = {os.environ.get(k) for k in _SECRET_KEYS}
    secret_values.discard(None)
    for key, value in list(event_dict.items()):
        if (
            key.upper() in _SECRET_KEYS
            or isinstance(value, str)
            and value
            and value in secret_values
        ):
            event_dict[key] = _REDACTED
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(format="%(message)s", level=getattr(logging, level.upper(), logging.INFO))
    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        sanitize,
        structlog.dev.ConsoleRenderer(),
    ]
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
