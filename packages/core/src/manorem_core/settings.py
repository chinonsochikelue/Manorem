"""Environment-driven configuration.

Model ids, quality presets and provider selection live here so nothing is
hard-coded at a call site. Everything is overridable via ``MANOREM_*`` env
vars or a local ``.env``.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from manorem_core.errors import ConfigError


class LLMProviderName(StrEnum):
    GEMINI = "gemini"
    CASSETTE = "cassette"
    STUB = "stub"


class RenderQuality(StrEnum):
    """Draft is for iteration; final is for delivery. Golden tests use draft."""

    DRAFT = "draft"  # 854x480 @ 15fps
    MEDIUM = "medium"  # 1280x720 @ 30fps
    FINAL = "final"  # 1920x1080 @ 60fps


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MANOREM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- workspace ----------------------------------------------------------
    workspace_root: Path = Field(default=Path("out"))
    log_level: str = Field(default="INFO")
    log_json: bool = Field(default=False, description="JSON logs for workers; console for humans")

    # --- AI ----------------------------------------------------------------
    llm_provider: LLMProviderName = Field(default=LLMProviderName.CASSETTE)
    gemini_api_key: SecretStr | None = Field(default=None)
    gemini_model: str = Field(default="gemini-3.8-flash")
    gemini_model_heavy: str = Field(
        default="gemini-3.8-flash",
        description="Used for story and visual planning if a stronger model is desired",
    )
    llm_temperature: float = Field(default=0.4, ge=0.0, le=2.0)
    llm_max_tokens: int = Field(default=8192, gt=0)
    ai_record: bool = Field(default=False, description="Refresh cassettes from live calls")
    ai_cassette_dir: Path = Field(default=Path("tests/fixtures/cassettes"))

    # --- repair loop --------------------------------------------------------
    max_repair_attempts: int = Field(default=2, ge=0, le=5)

    # --- render -------------------------------------------------------------
    render_quality: RenderQuality = Field(default=RenderQuality.DRAFT)
    render_timeout_s: int = Field(default=600, gt=0)
    frame_sample_hz: float = Field(
        default=1.0, gt=0.0, description="Keyframe sampling rate for the Visual QA seam"
    )

    # --- narration ----------------------------------------------------------
    narration_wpm: float = Field(
        default=150.0, gt=0.0, description="Placeholder pacing model until TTS lands"
    )

    @property
    def gemini_key_or_raise(self) -> str:
        if self.gemini_api_key is None:
            raise ConfigError(
                "MANOREM_GEMINI_API_KEY is not set. Set it, or use "
                "MANOREM_LLM_PROVIDER=cassette to replay recorded responses."
            )
        return self.gemini_api_key.get_secret_value()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
