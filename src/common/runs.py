"""Run-directory helper.

Every run is a self-contained directory under ``runs/<run_id>/``. Paths returned by this
helper are guaranteed to stay inside the run directory (path-traversal guard, S1/S7).
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from .schemas import RUN_ID_PATTERN


class RunDir:
    """Filesystem layout for one pipeline run."""

    def __init__(self, root: str | Path, run_id: str) -> None:
        if not re.fullmatch(RUN_ID_PATTERN, str(run_id)):
            raise ValueError(f"invalid run_id: {run_id!r}")
        self.run_id = str(run_id)
        self.root = Path(root).resolve()
        self.path = (self.root / self.run_id).resolve()
        if not str(self.path).startswith(str(self.root)):
            raise ValueError("run path escapes runs root")
        self.assets = self.path / "assets"
        self.brand_kit = self.path / "brand_kit"
        self.input_dir = self.path / "input"

    def ensure(self) -> RunDir:
        self.assets.mkdir(parents=True, exist_ok=True)
        self.brand_kit.mkdir(parents=True, exist_ok=True)
        self.input_dir.mkdir(parents=True, exist_ok=True)
        return self

    def _confined(self, *parts: str) -> Path:
        """Resolve ``parts`` under the run dir and assert no escape."""
        candidate = (self.path.joinpath(*parts)).resolve()
        if not str(candidate).startswith(str(self.path)):
            raise ValueError(f"path escapes run dir: {parts!r}")
        return candidate

    def asset_path(self, asset_id: str, attempt: int) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", asset_id):
            raise ValueError(f"invalid asset_id: {asset_id!r}")
        return self._confined("assets", f"{asset_id}__v{attempt}.png")

    def critic_path(self, asset_id: str, attempt: int) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", asset_id):
            raise ValueError(f"invalid asset_id: {asset_id!r}")
        return self._confined("assets", f"critic__{asset_id}__v{attempt}.json")

    def brand_dna_path(self) -> Path:
        return self._confined("brand_dna.json")

    def manifest_path(self) -> Path:
        return self._confined("asset_manifest.json")

    def orchestrator_log_path(self) -> Path:
        return self._confined("orchestrator_log.json")

    def run_log_path(self) -> Path:
        return self._confined("run.log")

    def kit_asset_path(self, name: str) -> Path:
        # bare basename only — no separators, no leading dot
        if not re.fullmatch(r"[A-Za-z0-9_]+\.(png|md|json)", name):
            raise ValueError(f"invalid kit asset name: {name!r}")
        return self._confined("brand_kit", name)

    def kit_manifest_path(self) -> Path:
        return self._confined("brand_kit", "kit_manifest.json")


def new_run_id() -> str:
    """A sortable, regex-safe run id."""
    return (
        time.strftime("%Y%m%d-%H%M%S", time.localtime())
        + f"-{int(time.time() * 1000) % 100000:05d}"
    )
