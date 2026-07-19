"""Tests for the @N brief token parser (CP-020)."""

from __future__ import annotations

import pytest

from src.common.brief_parser import (
    BriefTokenError,
    parse_image_roles,
    validate_brief_tokens,
)


class TestParseImageRoles:
    def test_single_image_returns_empty(self) -> None:
        assert parse_image_roles("a coffee brand", 1) == {}

    def test_no_tokens_returns_empty(self) -> None:
        assert parse_image_roles("a coffee brand with no refs", 3) == {}

    def test_extracts_roles_from_sentences(self) -> None:
        brief = "做一个咖啡品牌。@1 是 logo 灵感，@2 是包装色调。hero banner 参考 @2。"
        roles = parse_image_roles(brief, 2)
        assert 1 in roles
        assert 2 in roles
        assert "logo 灵感" in roles[1]
        assert "包装色调" in roles[2]
        # @2 appears in two sentences — they should be joined
        assert "包装色调" in roles[2]
        assert "hero banner 参考 @2" in roles[2]

    def test_ignores_out_of_range_tokens(self) -> None:
        brief = "@1 is logo, @5 is out of range"
        roles = parse_image_roles(brief, 2)
        assert 1 in roles
        assert 5 not in roles  # out-of-range indices are silently ignored here

    def test_english_punctuation(self) -> None:
        brief = "A coffee brand. @1 is the logo inspiration. @2 is the packaging."
        roles = parse_image_roles(brief, 2)
        assert 1 in roles
        assert 2 in roles


class TestValidateBriefTokens:
    def test_valid_tokens_pass(self) -> None:
        validate_brief_tokens("@1 and @2 are fine", 2)  # no exception
        validate_brief_tokens("no tokens at all", 1)  # no exception

    def test_out_of_range_raises(self) -> None:
        with pytest.raises(BriefTokenError, match="@3"):
            validate_brief_tokens("@3 references image 3", 2)

    def test_zero_raises(self) -> None:
        with pytest.raises(BriefTokenError, match="@0"):
            validate_brief_tokens("@0 is invalid", 2)

    def test_single_image_with_at1_passes(self) -> None:
        validate_brief_tokens("@1 is the reference", 1)  # no exception

    def test_single_image_with_at2_raises(self) -> None:
        with pytest.raises(BriefTokenError, match="@2"):
            validate_brief_tokens("@2 is out of range", 1)
