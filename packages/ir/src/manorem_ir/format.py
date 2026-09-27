"""Output format and visual style.

``FormatSpec`` is the only place aspect, resolution and fps are decided, so the
same IR can be compiled to 16:9, 9:16 and 1:1 by varying this alone.
"""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from manorem_ir.enums import Aspect

#: Pixel dimensions per (aspect, quality tier). Draft renders fast for iteration
#: and is what golden tests use; final is for delivery.
RESOLUTIONS: dict[tuple[Aspect, str], tuple[int, int]] = {
    (Aspect.WIDESCREEN, "draft"): (854, 480),
    (Aspect.WIDESCREEN, "medium"): (1280, 720),
    (Aspect.WIDESCREEN, "final"): (1920, 1080),
    (Aspect.VERTICAL, "draft"): (480, 854),
    (Aspect.VERTICAL, "medium"): (720, 1280),
    (Aspect.VERTICAL, "final"): (1080, 1920),
    (Aspect.SQUARE, "draft"): (480, 480),
    (Aspect.SQUARE, "medium"): (720, 720),
    (Aspect.SQUARE, "final"): (1080, 1080),
}

FPS_BY_QUALITY: dict[str, int] = {"draft": 15, "medium": 30, "final": 60}


class FormatSpec(BaseModel):
    """Target video format. Everything downstream reads dimensions from here."""

    model_config = ConfigDict(frozen=True)

    aspect: Aspect = Aspect.WIDESCREEN
    width: int = Field(default=854, ge=64, le=7680)
    height: int = Field(default=480, ge=64, le=7680)
    fps: int = Field(default=15, ge=1, le=120)
    bitrate_kbps: int | None = Field(default=None, ge=100, le=200_000)

    @model_validator(mode="after")
    def _dimensions_match_aspect(self) -> Self:
        actual = self.width / self.height
        expected = self.aspect.ratio
        # 2% tolerance absorbs rounding to even pixel counts.
        if abs(actual - expected) / expected > 0.02:
            raise ValueError(
                f"dimensions {self.width}x{self.height} (ratio {actual:.3f}) "
                f"do not match aspect {self.aspect.value} (ratio {expected:.3f})"
            )
        return self

    @classmethod
    def for_quality(cls, aspect: Aspect = Aspect.WIDESCREEN, quality: str = "draft") -> FormatSpec:
        """Build a spec from an aspect and a named quality tier."""
        key = (aspect, quality)
        if key not in RESOLUTIONS:
            raise ValueError(f"unknown quality tier {quality!r} for aspect {aspect.value}")
        width, height = RESOLUTIONS[key]
        return cls(aspect=aspect, width=width, height=height, fps=FPS_BY_QUALITY[quality])

    @property
    def frame_duration(self) -> float:
        """Seconds per frame -- the quantum all timing is snapped to."""
        return 1.0 / self.fps

    def seconds_to_frames(self, seconds: float) -> int:
        """Quantize a duration to whole frames, rounding half away from zero."""
        return int(seconds * self.fps + 0.5)

    def frames_to_seconds(self, frames: int) -> float:
        return frames / self.fps


class StyleTokens(BaseModel):
    """Design tokens applied during normalization.

    Centralized so a scene never hard-codes a hex value, and so restyling a whole
    project is one edit rather than hundreds.
    """

    model_config = ConfigDict(frozen=True)

    background: str = Field(default="#0E1116", pattern=r"^#[0-9A-Fa-f]{6}$")
    primary: str = Field(default="#5AB2FF", pattern=r"^#[0-9A-Fa-f]{6}$")
    secondary: str = Field(default="#FFD166", pattern=r"^#[0-9A-Fa-f]{6}$")
    accent: str = Field(default="#EF476F", pattern=r"^#[0-9A-Fa-f]{6}$")
    muted: str = Field(default="#6B7280", pattern=r"^#[0-9A-Fa-f]{6}$")
    text: str = Field(default="#F5F7FA", pattern=r"^#[0-9A-Fa-f]{6}$")
    success: str = Field(default="#06D6A0", pattern=r"^#[0-9A-Fa-f]{6}$")

    # Type scale in stage units, resolved to world units by pass P6.
    title_size: float = Field(default=0.22, gt=0.0, le=1.0)
    heading_size: float = Field(default=0.15, gt=0.0, le=1.0)
    body_size: float = Field(default=0.10, gt=0.0, le=1.0)
    caption_size: float = Field(default=0.07, gt=0.0, le=1.0)

    stroke_width: float = Field(default=2.5, gt=0.0, le=20.0)
    default_op_duration: float = Field(default=1.0, gt=0.0, le=30.0)

    def color_for(self, role: str) -> str:
        """Resolve a semantic color role, falling back to the primary color."""
        return {
            "primary": self.primary,
            "secondary": self.secondary,
            "accent": self.accent,
            "muted": self.muted,
            "text": self.text,
            "success": self.success,
            "background": self.background,
        }.get(role, self.primary)

    def size_for(self, role: str) -> float:
        return {
            "title": self.title_size,
            "heading": self.heading_size,
            "body": self.body_size,
            "caption": self.caption_size,
        }.get(role, self.body_size)
