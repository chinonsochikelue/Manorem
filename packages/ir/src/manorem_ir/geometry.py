"""Stage space: the aspect-independent coordinate system.

Positions are authored in ``[-1, 1]`` on both axes, where the unit square is the
*safe area* -- content guaranteed visible in every aspect ratio. Compiler pass P6
maps stage space to Manim world units for the target format. No world coordinate
and no 16:9 constant appears anywhere upstream of that pass.
"""

from __future__ import annotations

import math
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StagePoint(BaseModel):
    """A point in normalized stage space. ``(0, 0)`` is frame center."""

    model_config = ConfigDict(frozen=True)

    x: float = Field(ge=-2.0, le=2.0)
    y: float = Field(ge=-2.0, le=2.0)

    @model_validator(mode="after")
    def _finite(self) -> Self:
        if not (math.isfinite(self.x) and math.isfinite(self.y)):
            raise ValueError("stage coordinates must be finite")
        return self

    def __add__(self, other: StagePoint) -> StagePoint:
        return StagePoint(x=self.x + other.x, y=self.y + other.y)

    def scaled(self, factor: float) -> StagePoint:
        return StagePoint(x=self.x * factor, y=self.y * factor)

    def distance_to(self, other: StagePoint) -> float:
        return math.hypot(self.x - other.x, self.y - other.y)

    def as_tuple(self) -> tuple[float, float]:
        return (self.x, self.y)


ORIGIN = StagePoint(x=0.0, y=0.0)


class StageSize(BaseModel):
    """Extent in stage units. ``1.0`` spans half the safe area on that axis."""

    model_config = ConfigDict(frozen=True)

    width: float = Field(gt=0.0, le=4.0)
    height: float = Field(gt=0.0, le=4.0)


class StageBounds(BaseModel):
    """Axis-aligned box in stage space, used for layout, overlap lints and camera
    framing. Produced by the compiler, never authored by hand."""

    model_config = ConfigDict(frozen=True)

    min_x: float
    min_y: float
    max_x: float
    max_y: float

    @model_validator(mode="after")
    def _ordered_and_finite(self) -> Self:
        values = (self.min_x, self.min_y, self.max_x, self.max_y)
        if not all(math.isfinite(v) for v in values):
            raise ValueError("bounds must be finite")
        if self.min_x > self.max_x or self.min_y > self.max_y:
            raise ValueError("bounds min must not exceed max")
        return self

    @classmethod
    def around(cls, center: StagePoint, size: StageSize) -> StageBounds:
        half_w, half_h = size.width / 2.0, size.height / 2.0
        return cls(
            min_x=center.x - half_w,
            min_y=center.y - half_h,
            max_x=center.x + half_w,
            max_y=center.y + half_h,
        )

    @property
    def center(self) -> StagePoint:
        return StagePoint(x=(self.min_x + self.max_x) / 2.0, y=(self.min_y + self.max_y) / 2.0)

    @property
    def width(self) -> float:
        return self.max_x - self.min_x

    @property
    def height(self) -> float:
        return self.max_y - self.min_y

    @property
    def area(self) -> float:
        return self.width * self.height

    def intersects(self, other: StageBounds) -> bool:
        return not (
            self.max_x <= other.min_x
            or other.max_x <= self.min_x
            or self.max_y <= other.min_y
            or other.max_y <= self.min_y
        )

    def intersection_area(self, other: StageBounds) -> float:
        if not self.intersects(other):
            return 0.0
        dx = min(self.max_x, other.max_x) - max(self.min_x, other.min_x)
        dy = min(self.max_y, other.max_y) - max(self.min_y, other.min_y)
        return dx * dy

    def contains(self, other: StageBounds) -> bool:
        return (
            self.min_x <= other.min_x
            and self.min_y <= other.min_y
            and self.max_x >= other.max_x
            and self.max_y >= other.max_y
        )

    def union(self, other: StageBounds) -> StageBounds:
        return StageBounds(
            min_x=min(self.min_x, other.min_x),
            min_y=min(self.min_y, other.min_y),
            max_x=max(self.max_x, other.max_x),
            max_y=max(self.max_y, other.max_y),
        )

    def padded(self, pad: float) -> StageBounds:
        return StageBounds(
            min_x=self.min_x - pad,
            min_y=self.min_y - pad,
            max_x=self.max_x + pad,
            max_y=self.max_y + pad,
        )


#: The safe area. Anything outside this in the *target* aspect triggers IR305.
SAFE_AREA = StageBounds(min_x=-1.0, min_y=-1.0, max_x=1.0, max_y=1.0)


def union_all(boxes: list[StageBounds]) -> StageBounds | None:
    """Combined extent of many boxes, or None when there are none."""
    if not boxes:
        return None
    result = boxes[0]
    for box in boxes[1:]:
        result = result.union(box)
    return result
