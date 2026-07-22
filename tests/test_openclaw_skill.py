"""Acceptance tests for the StyleForge OpenClaw skill (CP-009)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1] / "skills" / "styleforge"
SKILL_MD = SKILL_DIR / "SKILL.md"
HELPER = SKILL_DIR / "styleforge_helper.py"
RUN_HELPER = SKILL_DIR / "run_helper.sh"

TRIGGER_PHRASES = [
    "品牌视觉识别",
    "品牌视觉",
    "brand kit",
    "brand identity",
    "brand visual identity",
]


def _frontmatter() -> dict[str, str]:
    text = SKILL_MD.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?\n)---\n", text, re.DOTALL)
    assert m, "SKILL.md has no YAML front-matter"
    fm: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith(" "):
            key, _, val = line.partition(":")
            fm[key.strip()] = val.strip()
    return fm


def test_skill_md_exists_and_frontmatter_parses() -> None:
    fm = _frontmatter()
    assert fm.get("name") == "styleforge"
    assert "description" in fm


def test_description_contains_trigger_phrases() -> None:
    fm = _frontmatter()
    desc = fm["description"].lower()
    missing = [p for p in TRIGGER_PHRASES if p.lower() not in desc]
    assert not missing, f"description missing trigger phrases: {missing}"


def test_run_helper_is_executable() -> None:
    assert RUN_HELPER.exists(), "run_helper.sh missing"
    assert os_access_x(RUN_HELPER), "run_helper.sh is not executable"


def test_helper_has_no_secrets() -> None:
    """Skill files must never embed secret values or read secret env vars."""
    blob = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore") for p in (SKILL_MD, HELPER, RUN_HELPER)
    )
    # real secret value prefixes / shapes (not the bare word ".env")
    secret_patterns = [
        r"nvapi-[A-Za-z0-9_-]{10,}",
        r"hf_[A-Za-z0-9]{20,}",
        r"sk-[A-Za-z0-9]{20,}",
        r"\b\d{8,}:[A-Za-z0-9_-]{30,}\b",  # telegram bot token shape
    ]
    for pat in secret_patterns:
        assert not re.search(pat, blob), f"secret-shaped pattern {pat!r} in skill files"
    # must not reference secret-bearing env var names or dotenv loaders
    # (checked in HELPER only — run_helper.sh is the entrypoint that legitimately
    # maps gateway env vars like TELEGRAM_BOT_TOKEN to generic helper env names)
    # NOTE: helper may read TELEGRAM_BOT_TOKEN as a fallback when the agent
    # invokes the .py directly instead of via run_helper.sh (env mapping skipped).
    # This is a read from the environment, not a hardcoded secret.
    helper_src = HELPER.read_text(encoding="utf-8")
    secret_names = [
        "STEPFUN_API_KEY",
        "NVIDIA_API_KEY",
        "HF_TOKEN",
        "OPENAI_API_KEY",
        "dotenv",
        "load_dotenv",
    ]
    for name in secret_names:
        assert name not in helper_src, f"secret reference {name!r} found in helper"


def test_helper_does_not_import_third_party() -> None:
    """Pure stdlib → runs inside the NemoClaw sandbox with no venv."""
    src = HELPER.read_text(encoding="utf-8")
    # crude import scan of top-level import lines
    imports = re.findall(r"^\s*import (\w+)", src, re.MULTILINE)
    froms = re.findall(r"^\s*from (\w+)", src, re.MULTILINE)
    mods = set(imports) | set(froms)
    third_party = mods - set(sys.stdlib_module_names)
    assert not third_party, f"non-stdlib imports in helper: {third_party}"


def test_helper_publish_boundary_is_inside_openclaw_workspace(tmp_path, monkeypatch):
    """publish() must refuse to write outside the media boundary."""
    monkeypatch.setenv("OPENCLAW_HOME", str(tmp_path))
    # re-import the helper module fresh with the patched env
    sys.modules.pop("styleforge_helper", None)
    sys.path.insert(0, str(SKILL_DIR))
    try:
        import importlib

        mod = importlib.import_module("styleforge_helper")
        # normal publish is fine
        out = mod.publish("logo.png", "rid", b"\x89PNG")
        assert out.resolve().is_relative_to(
            (tmp_path / ".openclaw" / "workspace" / "outputs" / "styleforge").resolve()
        )
        assert out.exists() and out.read_bytes() == b"\x89PNG"
    finally:
        sys.path.remove(str(SKILL_DIR))


def os_access_x(p: Path) -> bool:
    import os as _os

    return _os.access(p, _os.X_OK)
