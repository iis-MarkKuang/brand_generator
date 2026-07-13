"""Pydantic data contracts for every inter-agent handoff.

Mirrors references/design/02-data-contracts.md exactly. All JSON files written and read
by agents validate against these models. Token-hygiene constraints (T7) and run-id
validation (S1) are enforced here so they cannot be bypassed.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

# Default run-id pattern (mirrored in Settings.run_id_regex; kept here so schemas do not
# import config, avoiding a circular dependency).
RUN_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
HEX_PATTERN = r"^#[0-9A-Fa-f]{6}$"

RunId = Annotated[str, StringConstraints(pattern=RUN_ID_PATTERN)]
HexColor = Annotated[str, StringConstraints(pattern=HEX_PATTERN)]
# Token hygiene (T7): keep FLUX prompts within CLIP's useful range.
FluxPrompt = Annotated[str, StringConstraints(max_length=600)]
NegativePrompt = Annotated[str, StringConstraints(max_length=300)]
Rank = Literal["primary", "accent", "neutral"]
TypographyClass = Literal["serif", "sans", "display", "mono"]
AssetType = Literal["logo", "hero_banner", "social_square", "product_mockup", "business_card"]
AssetStatus = Literal["approved", "failed"]


class PaletteColor(BaseModel):
    name: str
    hex: HexColor
    rank: Rank


class BrandDna(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brand_name: str
    palette: list[PaletteColor] = Field(min_length=1, max_length=8)
    mood: list[str] = Field(min_length=1, max_length=12)
    typography_class: TypographyClass
    typography_pairs: dict[str, str] = Field(default_factory=dict)
    visual_keywords: list[str] = Field(default_factory=list, max_length=16)
    dos: list[str] = Field(default_factory=list)
    donts: list[str] = Field(default_factory=list)
    personality: str


class AssetSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: AssetType
    size: list[int] = Field(min_length=2, max_length=2)
    flux_prompt: FluxPrompt
    negative_prompt: NegativePrompt = ""
    composition: str = ""
    uses_pulid: bool = False
    pulid_reference: str | None = None
    seed: int
    steps: int | None = None

    @field_validator("size")
    @classmethod
    def _size_within_vram(cls, v: list[int]) -> list[int]:
        if max(v) > 1344:
            raise ValueError("asset size longest side must be <= 1344 (VRAM headroom)")
        return v

    @field_validator("pulid_reference")
    @classmethod
    def _pulid_only_when_used(cls, v: str | None, info) -> str | None:  # type: ignore[no-untyped-def]
        if v is not None and not info.data.get("uses_pulid", False):
            raise ValueError("pulid_reference set but uses_pulid is false")
        return v


class AssetManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: RunId
    brand_dna_ref: str = "brand_dna.json"
    assets: list[AssetSpec] = Field(min_length=1)


class CriticResult(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    run_id: RunId
    asset_id: str
    attempt: int = Field(ge=1)
    png_path: str
    # `pass` is a Python keyword → field name `pass_` with JSON alias "pass".
    pass_: bool = Field(alias="pass")
    score: int = Field(ge=0, le=100)
    palette_match: float = Field(ge=0.0, le=1.0)
    mood_match: float = Field(ge=0.0, le=1.0)
    legibility: float = Field(ge=0.0, le=1.0)
    on_brand: float = Field(ge=0.0, le=1.0)
    feedback: str = ""


def _default_assets() -> list[AssetType]:
    return ["logo", "hero_banner", "social_square", "product_mockup", "business_card"]


class RunOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assets: list[AssetType] = Field(default_factory=_default_assets)
    max_retries_per_asset: int = Field(default=2, ge=0, le=5)
    pulid_reference: str | None = None


class RunInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: RunId
    brand_name: str
    brief: str = Field(min_length=1, max_length=4000)
    reference_image: str
    options: RunOptions = Field(default_factory=RunOptions)

    @field_validator("run_id")
    @classmethod
    def _check_run_id(cls, v: str) -> str:
        if not re.fullmatch(RUN_ID_PATTERN, v):
            raise ValueError(f"run_id must match {RUN_ID_PATTERN}")
        return v


class KitAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: AssetType
    path: str
    status: AssetStatus
    final_score: int | None = Field(default=None, ge=0, le=100)
    error: str | None = None


class OptimizationStats(BaseModel):
    model_config = ConfigDict(extra="allow")

    vram_swaps: int = 0
    brand_dna_cache_hit: bool = False
    critic_effort_low_count: int = 0
    critic_effort_medium_count: int = 0
    critic_effort_high_count: int = 0
    total_vlm_calls: int = 0
    total_renders: int = 0
    routing_local_count: int = 0
    routing_nim_count: int = 0


class KitManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: RunId
    brand_name: str
    status: Literal["complete", "partial"]
    brand_dna_ref: str = "brand_dna.json"
    brand_guide: str = "brand_kit/brand_guide.md"
    assets: list[KitAsset]
    palette: list[HexColor]
    generated_at: datetime
    total_latency_s: int
    optimization_stats: OptimizationStats = Field(default_factory=OptimizationStats)


class OrchestratorEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    t: datetime
    action: str
    reason: str = ""
    backend: str = ""
    vram_before_gb: float | None = None
    vram_after_gb: float | None = None
    latency_s: float | None = None


class RenderResult(BaseModel):
    """Outcome of one Generator render attempt (also written as render_meta.json)."""

    model_config = ConfigDict(extra="forbid")

    asset_id: str
    attempt: int = Field(ge=1)
    png_path: str
    prompt_id: str
    seed: int
    steps: int
    cfg: float
    sampler: str = "euler"
    scheduler: str = "simple"
    guidance: float = 3.5
    uses_pulid: bool = False
    latency_s: float
    vram_free_mib: int | None = None
    error: str | None = None
