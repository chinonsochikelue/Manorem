"""The scene timeline: cues.

A cue is one directorial instruction -- *what* should happen, to *what*, *when*,
and for *how long* -- expressed in the semantic vocabulary. It never names a
Manim class, never carries a coordinate, and never carries an absolute frame
number. Compiler passes P2/P4 turn cues into primitive, frame-quantized events.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from manorem_core import Slug
from manorem_ir.enums import CAMERA_OPS, Easing, SemanticOp
from manorem_ir.timing import (
    AUTO,
    AbsoluteTime,
    DurationExpr,
    TimeExpr,
    referenced_cue,
    referenced_segment,
)

#: Cue parameters are flat, JSON-scalar values only.
#:
#: This is the §26 security boundary made structural rather than procedural: a
#: parameter cannot be a nested structure, an expression, or anything that could
#: smuggle behaviour toward the renderer. Skills that need richer configuration
#: declare a new object kind, not a richer parameter.
ParamValue = bool | int | float | str | list[str] | list[float]


class Cue(BaseModel):
    """One timed instruction in a scene."""

    model_config = ConfigDict(frozen=True)

    id: Slug
    op: SemanticOp
    targets: list[Slug] = Field(default_factory=list, max_length=50)
    params: dict[str, ParamValue] = Field(default_factory=dict)
    at: TimeExpr = Field(default_factory=lambda: AbsoluteTime(seconds=0.0))
    duration: DurationExpr = Field(default=AUTO)
    easing: Easing | None = None
    #: Why this cue exists, in the director's words. Required by the visual
    #: planner's schema and carried through so a human reviewing generated IR can
    #: see the intent, not just the mechanics.
    why: str | None = Field(default=None, max_length=280)

    @property
    def is_camera(self) -> bool:
        return self.op in CAMERA_OPS

    @property
    def depends_on_cue(self) -> str | None:
        """Cue id this one is scheduled against, for the timing DAG."""
        return referenced_cue(self.at)

    @property
    def depends_on_segments(self) -> set[str]:
        """Narration segment ids this cue's start or length depends on."""
        refs: set[str] = set()
        start_ref = referenced_segment(self.at)
        if start_ref is not None:
            refs.add(start_ref)
        length_ref = referenced_segment(self.duration)
        if length_ref is not None:
            refs.add(length_ref)
        return refs
