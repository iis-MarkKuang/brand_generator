"""Typed application settings loaded from environment / .env.

This module is the *only* place that reads environment variables for secrets-bearing
config (see references/design/07-security-and-tokens.md §A — single secrets boundary).
For the orchestrator service this is the boundary itself; the OpenClaw skill and the
NemoClaw sandboxed agent must NOT import this and instead call the orchestrator API.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _split_csv(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _split_csv_int(raw: str | None) -> list[int]:
    out: list[int] = []
    for item in _split_csv(raw):
        try:
            out.append(int(item))
        except ValueError as err:
            raise ValueError(f"non-integer id in list: {item!r}") from err
    return out


_PLACEHOLDER_PREFIX = "replace_with_your_"
_REQUIRED_SECRETS = (
    "stepfun_api_key",
    "nvidia_api_key",
    "hf_token",
    "telegram_bot_token",
)


class Settings(BaseSettings):
    """All runtime configuration. Sources: .env then process environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Stepfun (阶跃星辰) ---
    stepfun_api_key: Annotated[str, Field(default="", repr=False)]
    stepfun_base_url: str = "https://api.stepfun.com/v1"
    stepfun_vlm_model: str = "step-3.7-flash"
    stepfun_text_model: str = "step-2-mini"

    # --- NVIDIA developer API (NIM cloud fallback / routing) ---
    nvidia_api_key: Annotated[str, Field(default="", repr=False)]
    nvidia_nim_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_nim_model: str = "nvidia/llama-3.3-nemotron-super-49b-v1.5"
    # CP-013 local<->cloud reasoning router strategy:
    #   local-first (default) | cloud-first | local-only
    routing_strategy: str = "local-first"

    # --- Hugging Face (NeMo LoRA leg) ---
    hf_token: Annotated[str, Field(default="", repr=False)]
    hf_hub_offline: bool = True

    # --- Telegram ---
    telegram_bot_token: Annotated[str, Field(default="", repr=False)]

    # --- NVIDIA local stack (DGX Spark) ---
    ollama_host: str = "http://127.0.0.1:11434"
    ollama_api_key: str = "ollama-local"
    ollama_reasoning_model: str = "nemotron-3-super:120b"
    ollama_light_model: str = "glm-4.7-flash:latest"
    comfyui_host: str = "http://127.0.0.1:8200"
    # Absolute path to the workshop comfyui-ctl.sh; empty disables CUDA-dirty restart.
    comfyui_ctl_script: str = ""
    # CP-014: optional FLUX LoRA adapter (ComfyUI LoraLoader). Filename relative to
    # ComfyUI's models/loras/ dir; empty disables LoRA (the default, non-LoRA path).
    lora_adapter: str = ""
    lora_strength: float = 1.0

    # --- OpenClaw ---
    openclaw_home: str = "/home/nvidia/build_a_claw_workshop/openclaw-home"
    openclaw_port: int = 9000  # workshop notebook uses 3030; this Spark's gateway binds 9000

    # --- App ---
    app_port: int = 8000
    frontend_port: int = 5173
    runs_root: str = "runs"
    log_level: str = "INFO"

    # --- Security & token budget (07-security-and-tokens.md §D) ---
    max_upload_mb: int = 10
    # CP-020: maximum number of reference images per run.
    max_reference_images: int = 5
    cors_allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )
    telegram_allowed_chat_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)
    max_total_vlm_calls: int = 25
    max_total_renders: int = 20
    run_timeout_s: int = 600
    no_cloud_vision: bool = False
    vlm_image_detail_first: str = "high"
    vlm_image_detail_recheck: str = "low"
    critic_pass_threshold: int = 70
    critic_deep_reasoning: bool = True  # CP-017: multi-step VLM reasoning chain
    vram_free_threshold_gb: float = 32.0
    ollama_unload_timeout_s: int = 30
    run_id_regex: str = r"^[A-Za-z0-9_-]{1,64}$"

    # JSON-encoded list env vars come in as raw strings; coerce them.
    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _parse_cors(cls, v: object) -> list[str]:
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        return _split_csv(v if isinstance(v, str) else None)

    @field_validator("telegram_allowed_chat_ids", mode="before")
    @classmethod
    def _parse_chat_ids(cls, v: object) -> list[int]:
        if isinstance(v, list):
            return [int(x) for x in v]
        return _split_csv_int(v if isinstance(v, str) else None)

    @model_validator(mode="after")
    def _reject_placeholders(self) -> Settings:
        # When ALL secrets are empty (CI / test mode without .env), skip
        # placeholder validation so the module-level `app = create_app()`
        # in api.py can import successfully.
        if all(not getattr(self, name) for name in _REQUIRED_SECRETS):
            return self
        bad = [
            name
            for name in _REQUIRED_SECRETS
            if not getattr(self, name) or getattr(self, name).startswith(_PLACEHOLDER_PREFIX)
        ]
        if bad:
            raise ValueError(
                f"Required secret(s) still placeholder or empty: {', '.join(bad)}. "
                f"Fill them in .env (see .env.example)."
            )
        if self.vlm_image_detail_first not in {"low", "high"}:
            raise ValueError("vlm_image_detail_first must be 'low' or 'high'")
        if self.vlm_image_detail_recheck not in {"low", "high"}:
            raise ValueError("vlm_image_detail_recheck must be 'low' or 'high'")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings singleton. Import once, use everywhere in the orchestrator."""
    return Settings()  # type: ignore[call-arg]
