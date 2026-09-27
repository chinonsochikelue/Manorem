"""Camera intent.

The camera has a starting state and a policy; its *movements* live in the scene
timeline as ordinary cues (``zoom_to``, ``pan_to``, ``focus``), so a camera move
can be ordered and time-anchored against visuals with the same vocabulary.
Compiler pass P5 turns those cues into concrete frame keyframes.
"""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from manorem_core import Slug
from manorem_ir.geometry import ORIGIN, StagePoint


class CameraState(BaseModel):
    """A camera pose in stage space.

    ``width`` is the horizontal extent visible, in stage units: ``2.0`` shows the
    whole safe area, ``1.0`` is a 2x zoom. Expressing zoom as a width rather than
    a scale factor keeps it aspect-independent -- height follows from the format.
    """

    model_config = ConfigDict(frozen=True)

    center: StagePoint = Field(default=ORIGIN)
    width: float = Field(default=2.0, gt=0.05, le=8.0)

    def zoomed(self, factor: float) -> CameraState:
        return CameraState(center=self.center, width=self.width / factor)


class CameraSpec(BaseModel):
    """Initial camera state plus the limits the compiler must respect."""

    model_config = ConfigDict(frozen=True)

    initial: CameraState = Field(default_factory=CameraState)
    #: Frame all visible content at scene start instead of using ``initial``.
    auto_frame: bool = False
    #: Clamps applied to every camera cue, so a bad ``zoom_to`` cannot produce a
    #: frame showing one pixel or the whole void.
    min_width: float = Field(default=0.4, gt=0.05, le=8.0)
    max_width: float = Field(default=3.0, gt=0.05, le=8.0)
    #: Object the camera tracks for the whole scene, if any.
    follow: Slug | None = None
    #: Return to ``initial`` before the scene ends, so transitions start from a
    #: known pose rather than wherever the last cue left the frame.
    reset_at_end: bool = False

    @model_validator(mode="after")
    def _consistent_limits(self) -> Self:
        if self.min_width > self.max_width:
            raise ValueError("camera min_width must not exceed max_width")
        if not (self.min_width <= self.initial.width <= self.max_width):
            raise ValueError(
                f"initial camera width {self.initial.width} is outside "
                f"[{self.min_width}, {self.max_width}]"
            )
        return self

    def clamp_width(self, width: float) -> float:
        return min(max(width, self.min_width), self.max_width)
