"""Brief parser — resolves ``@N`` image-reference tokens in user briefs.

Users can upload multiple reference images and reference them by index in their
brand brief::

    做一个精品咖啡品牌。
    @1 是 logo 灵感参考（极简线条风），
    @2 是我想要的产品包装色调，
    banner 请参考 @2 的氛围，logo 请参考 @1 的风格。

This module extracts the roles (the sentence context around each ``@N``) and
validates that every ``@N`` index is in range ``1..num_images``.
"""

from __future__ import annotations

import re

__all__ = ["parse_image_roles", "validate_brief_tokens", "BriefTokenError"]

_AT_TOKEN_RE = re.compile(r"@(\d+)")
# Split brief into sentences (Chinese + English punctuation aware).
_SENTENCE_RE = re.compile(r"[。！？；\n.!?;]+")


class BriefTokenError(ValueError):
    """Raised when a brief references an out-of-range ``@N`` image index."""


def parse_image_roles(brief: str, num_images: int) -> dict[int, str]:
    """Extract a mapping ``{index: role_description}`` from the brief.

    The "role" is the sentence containing the ``@N`` token, trimmed. If the same
    index appears in multiple sentences, they are joined with ``" | "``.
    Returns an empty dict when ``num_images < 2`` (single-image runs have no
    need for explicit roles — the one image is implicitly "the reference").
    """
    if num_images < 2:
        return {}
    roles: dict[int, list[str]] = {}
    # Split into sentences while keeping the delimiter text attached.
    parts = _SENTENCE_RE.split(brief)
    for sentence in parts:
        for m in _AT_TOKEN_RE.finditer(sentence):
            idx = int(m.group(1))
            if 1 <= idx <= num_images:
                role = sentence.strip()
                if role:
                    roles.setdefault(idx, []).append(role)
    return {k: " | ".join(v) for k, v in sorted(roles.items())}


def validate_brief_tokens(brief: str, num_images: int) -> None:
    """Raise ``BriefTokenError`` if the brief references an out-of-range ``@N``.

    ``@0`` and ``@N`` where ``N > num_images`` are rejected. ``@N`` tokens that
    are in range are left untouched (agents see them as human-readable labels).
    """
    for m in _AT_TOKEN_RE.finditer(brief):
        idx = int(m.group(1))
        if idx < 1 or idx > num_images:
            raise BriefTokenError(
                f"@{idx} references image {idx} but only {num_images} "
                f"image(s) were uploaded (valid range: @1..@{num_images})."
            )
