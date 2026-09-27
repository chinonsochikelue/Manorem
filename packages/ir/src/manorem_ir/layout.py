"""Layout intent.

The author declares *how things should be arranged*, not where they go. Letting
a language model assign coordinates is the fastest route to overlapping,
off-screen, unreadable frames -- it has no feedback loop and no notion of a
bounding box. Compiler pass P3 owns actual positions.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from manorem_ir.enums import LayoutKind
from manorem_ir.geometry import SAFE_AREA, StageBounds

Align = Literal["start", "center", "end", "space_between"]


class LayoutSlot(BaseModel):
    """A named region within a composite layout.

    ``capacity`` is what makes "too much crammed into the left panel" a
    validation error (IR206) instead of a rendering surprise.
    """

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1, max_length=40)
    weight: float = Field(default=1.0, gt=0.0, le=100.0)
    capacity: int = Field(default=8, ge=1, le=64)
    layout: LayoutKind = LayoutKind.VERTICAL


class LayoutSpec(BaseModel):
    """How a scene's objects are arranged.

    Every field is a hint to a solver. Unsupported combinations are rejected here
    rather than producing a silently degraded arrangement.
    """

    model_config = ConfigDict(frozen=True)

    kind: LayoutKind = LayoutKind.CENTERED
    #: Region the layout fills. Defaults to the full safe area, so content is
    #: visible in every aspect ratio.
    region: StageBounds = Field(default=SAFE_AREA)
    gap: float = Field(default=0.15, ge=0.0, le=1.0)
    padding: float = Field(default=0.08, ge=0.0, le=1.0)
    align: Align = "center"

    # Kind-specific hints. ``None`` means "solver decides".
    columns: int | None = Field(default=None, ge=1, le=16)
    rows: int | None = Field(default=None, ge=1, le=16)
    radius: float | None = Field(default=None, gt=0.0, le=2.0)
    start_angle: float = Field(default=90.0, ge=-360.0, le=360.0)
    direction: Literal["horizontal", "vertical"] = "horizontal"
    slots: list[LayoutSlot] = Field(default_factory=list, max_length=12)
    #: Seed for solvers with a randomized component (force-directed graph).
    #: Fixed by default because a layout that moves between runs would break
    #: RenderPlan snapshots.
    seed: int = Field(default=0, ge=0, le=2**31 - 1)

    @model_validator(mode="after")
    def _kind_requirements(self) -> Self:
        names = [s.name for s in self.slots]
        if len(names) != len(set(names)):
            raise ValueError("layout slot names must be unique")
        if self.kind is LayoutKind.SPLIT and len(self.slots) < 2:
            raise ValueError("split layout requires at least two slots")
        if self.kind is not LayoutKind.SPLIT and self.slots:
            raise ValueError(f"slots are only meaningful for a split layout, not {self.kind.value}")
        return self

    @property
    def slot_names(self) -> frozenset[str]:
        return frozenset(s.name for s in self.slots)

    def slot(self, name: str) -> LayoutSlot | None:
        return next((s for s in self.slots if s.name == name), None)

    @property
    def content_region(self) -> StageBounds:
        """The region minus padding -- where objects may actually be placed."""
        return self.region.padded(-self.padding) if self.padding else self.region
