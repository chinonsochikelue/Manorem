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
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    KEYPOOL = "keypool"
    CASSETTE = "cassette"
    STUB = "stub"


class RenderQuality(StrEnum):
    """Draft is for iteration; final is for delivery. Golden tests use draft."""

    DRAFT = "draft"  # 854x480 @ 15fps
    MEDIUM = "medium"  # 1280x720 @ 30fps
    FINAL = "final"  # 1920x1080 @ 60fps


class TTSProviderName(StrEnum):
    """Speech synthesis backends. ``stub`` and ``cassette`` are offline; ``openai``
    is the one real, opt-in provider and is unreachable under ``--offline``."""

    STUB = "stub"
    CASSETTE = "cassette"
    OPENAI = "openai"


class ResearchProviderName(StrEnum):
    """Retrieval backends for content intelligence.

    ``stub`` and ``fixture`` serve a fixed in-memory corpus (offline, no keys);
    ``cassette`` replays committed recordings (and, with ``MANOREM_RESEARCH_RECORD``,
    records them from the live backend); ``brave`` is the one real, opt-in
    provider and is unreachable under ``--offline``.
    """

    STUB = "stub"
    FIXTURE = "fixture"
    CASSETTE = "cassette"
    BRAVE = "brave"


class GeminiKeyMode(StrEnum):
    SHARED = "shared"
    DEDICATED = "dedicated"


class GeminiTool(StrEnum):
    CASSETTE = "cassette"
    RESEARCH = "research"
    REPAIR = "repair"
    SCENE = "scene"
    EVIDENCE = "evidence"
    SCRIPT = "script"
    STORY = "story"
    VISUAL_PLAN = "visual_plan"

    @property
    def env_var(self) -> str:
        """The env variable this tool reads in dedicated mode."""
        return f"MANOREM_{self.value.upper()}_GEMINI_APIKEY"


# Shared key fields that pydantic-settings ignores (extra="ignore") so they never
# leak into .env or telemetry. The singular ``MANOREM_GEMINI_API_KEY`` is still
# accepted as a legacy alias by ``gemini_key_or_raise``.
MANOREM_CASSETTE_GEMINI_APIKEY: str = ""
MANOREM_RESEARCH_GEMINI_APIKEY: str = ""
MANOREM_REPAIR_GEMINI_APIKEY: str = ""
MANOREM_SCENE_GEMINI_APIKEY: str = ""
MANOREM_EVIDENCE_GEMINI_APIKEY: str = ""
MANOREM_SCRIPT_GEMINI_APIKEY: str = ""
MANOREM_STORY_GEMINI_APIKEY: str = ""
MANOREM_VISUAL_PLAN_GEMINI_APIKEY: str = ""


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
    anthropic_api_key: SecretStr | None = Field(default=None)
    anthropic_model: str = Field(default="claude-3-5-sonnet-20241022")
    anthropic_base_url: str | None = Field(
        default=None,
        description="Optional gateway URL (e.g. JustWorker), set MANOREM_ANTHROPIC_BASE_URL",
    )
    openai_api_key: SecretStr | None = Field(default=None)
    openai_model: str = Field(default="gpt-4o")
    openai_base_url: str | None = Field(
        default=None,
        description="Optional gateway URL, set MANOREM_OPENAI_BASE_URL",
    )
    keypool_key_pool: list[str] = Field(
        default_factory=list, description="Ordered api keys for KeyPoolProvider"
    )
    keypool_cooldown: int = Field(default=2, ge=0, description="Cooldown attempts after a 429")
    llm_temperature: float = Field(default=0.4, ge=0.0, le=2.0)
    llm_max_tokens: int = Field(default=8192, gt=0)
    # A ceiling on the model's output, not a per-call spend: a call is billed for
    # the tokens it actually generates, and the free-tier wall is requests/day, not
    # tokens. Repair emits the one large output -- a full JsonPatch over a scene --
    # so it gets a higher ceiling than the other stages, which keeps that patch from
    # truncating into invalid JSON without raising the cap (or the cost) elsewhere.
    llm_repair_max_tokens: int = Field(default=16384, gt=0)
    ai_record: bool = Field(default=False, description="Refresh cassettes from live calls")
    ai_cassette_dir: Path = Field(default=Path("tests/fixtures/cassettes"))

    # Legacy field name accepted for backward compatibility; new code uses
    # ``gemini_api_key`` (with underscore) which the ``gemini_key_or_raise``
    # property checks first. Both are ``SecretStr`` instances.
    gemini_apikey: SecretStr | None = Field(
        default=None, description="Legacy: MANOREM_GEMINI_API_KEY (deprecated)."
    )

    # --- repair loop --------------------------------------------------------
    max_repair_attempts: int = Field(default=2, ge=0, le=5)

    # --- research -------------------------------------------------------------
    research_enabled: bool = Field(
        default=False, description="Run the content-intelligence stage (retrieve, assess, trace)"
    )
    research_provider: ResearchProviderName = Field(default=ResearchProviderName.FIXTURE)
    research_record: bool = Field(default=False, description="Refresh research cassettes")
    research_api_key: SecretStr | None = Field(default=None)
    research_cassette_dir: Path = Field(default=Path("tests/fixtures/research_cassettes"))
    research_cache_ttl_s: float = Field(
        default=86400.0, gt=0.0, description="Reuse a retrieval within this window"
    )

    # --- render -------------------------------------------------------------
    render_quality: RenderQuality = Field(default=RenderQuality.DRAFT)
    render_timeout_s: int = Field(default=600, gt=0)
    frame_sample_hz: float = Field(
        default=1.0, gt=0.0, description="Keyframe sampling rate for the Visual QA seam"
    )

    # --- visual QA ----------------------------------------------------------
    vqa_enabled: bool = Field(default=False, description="Assess renders with GeometricVisualQA")

    # --- narration ----------------------------------------------------------
    narration_wpm: float = Field(
        default=150.0, gt=0.0, description="Fallback pacing model when no audio is synthesized"
    )

    # --- audio / TTS --------------------------------------------------------
    audio_enabled: bool = Field(default=False, description="Synthesize narration audio")
    tts_provider: TTSProviderName = Field(default=TTSProviderName.STUB)
    tts_voice: str = Field(default="narrator", description="Provider-neutral voice label")
    tts_language: str = Field(
        default="en", description="BCP-47-ish language tag passed to the provider"
    )
    tts_speed: float = Field(default=1.0, gt=0.0, le=4.0, description="Speaking-rate multiplier")
    tts_sample_rate: int = Field(default=24000, gt=0, description="Target PCM sample rate (Hz)")
    tts_cassette_dir: Path = Field(default=Path("tests/fixtures/tts_cassettes"))
    tts_record: bool = Field(default=False, description="Refresh TTS cassettes from live calls")
    tts_api_key: SecretStr | None = Field(default=None)
    tts_base_url: str | None = Field(
        default=None,
        description="Optional OpenAI-compatible gateway URL, set MANOREM_TTS_BASE_URL",
    )
    tts_model: str = Field(default="tts-1", description="Model id for the real speech provider")

    # --- Gemini key mode ----------------------------------------------------
    gemini_key_mode: GeminiKeyMode = Field(
        default=GeminiKeyMode.SHARED,
        description="How per-tool Gemini credentials are resolved",
    )
    gemini_allow_shared_fallback: bool = Field(
        default=False,
        description="If true and a tool has no dedicated key, silently fall back "
        "to the shared credential (MANOREM_GEMINI_APIKEY). Off by default so "
        "a missing variable is always a loud ConfigError.",
    )

    # Per-tool Gemini API keys (dedicated mode). Each corresponds to
    # ``MANOREM_<TOOL>_GEMINI_APIKEY`` set by the operator. Defaults to ``None``
    # so that a missing variable is always a loud ``ConfigError`` rather than a
    # silent fallthrough. The test helper ``_dedicated`` passes these as keyword
    # arguments keyed by ``<tool>_gemini_apikey``.
    cassette_gemini_apikey: SecretStr | None = Field(
        default=None, description="Key for the cassette tool"
    )
    research_gemini_apikey: SecretStr | None = Field(
        default=None, description="Key for the research tool"
    )
    repair_gemini_apikey: SecretStr | None = Field(
        default=None, description="Key for the repair tool"
    )
    scene_gemini_apikey: SecretStr | None = Field(
        default=None, description="Key for the scene tool"
    )
    evidence_gemini_apikey: SecretStr | None = Field(
        default=None, description="Key for the evidence tool"
    )
    script_gemini_apikey: SecretStr | None = Field(
        default=None, description="Key for the script tool"
    )
    story_gemini_apikey: SecretStr | None = Field(
        default=None, description="Key for the story tool"
    )
    visual_plan_gemini_apikey: SecretStr | None = Field(
        default=None, description="Key for the visual plan tool"
    )

    @property
    def gemini_key_or_raise(self) -> str:
        # Shared mode: one credential serves all tools.
        # Prefer the new env var name, fall back to the legacy field name
        # that the test suite constructs directly (``gemini_apikey``).
        if self.gemini_apikey is not None:
            return self.gemini_apikey.get_secret_value()
        if self.gemini_api_key is not None:
            return self.gemini_api_key.get_secret_value()
        # No key configured — give a clear error that names the variables
        # the operator can set, without exposing any value.
        raise ConfigError(
            "MANOREM_GEMINI_APIKEY is not set. Set it (MANOREM_GEMINI_API_KEY "
            "is still accepted as a legacy alias), or use "
            "MANOREM_LLM_PROVIDER=cassette to replay recorded responses."
        )


# Tools used by the live pipeline when --offline is not set. CASSETTE is excluded
# because cassette-record mode selects its own credential independently.
PIPELINE_GEMINI_TOOLS: tuple[GeminiTool, ...] = (
    GeminiTool.EVIDENCE,
    GeminiTool.RESEARCH,
    GeminiTool.SCENE,
    GeminiTool.SCRIPT,
    GeminiTool.STORY,
    GeminiTool.VISUAL_PLAN,
    GeminiTool.REPAIR,
)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
