"""Scene objects and their placement.

Placement is *intent*, not coordinates: ``Auto`` defers entirely to the layout
engine, ``Slot`` names a region, ``Anchor`` positions relative to another object.
``Stage`` exists as an escape hatch for genuinely hand-tuned positions, but it is
the exception -- letting the AI place everything manually is what produces
overlapping, broken frames.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from manorem_core import Slug
from manorem_ir.enums import ObjectKind, RelationKind, Side
from manorem_ir.geometry import StagePoint
from manorem_ir.props import ObjectProps


class AutoPlacement(BaseModel):
    """The layout engine decides. This is the default and the recommended case."""

    model_config = ConfigDict(frozen=True)

    mode: Literal["auto"] = "auto"
    order: int | None = Field(default=None, ge=0, le=999)


class SlotPlacement(BaseModel):
    """Occupies a named region of the active layout (e.g. ``left`` in a split)."""

    model_config = ConfigDict(frozen=True)

    mode: Literal["slot"] = "slot"
    slot: str = Field(min_length=1, max_length=40)


class AnchorPlacement(BaseModel):
    """Positioned relative to another object, resolved after that object's
    bounds are known."""

    model_config = ConfigDict(frozen=True)

    mode: Literal["anchor"] = "anchor"
    ref: Slug
    side: Side = Side.BELOW
    gap: float = Field(default=0.1, ge=0.0, le=2.0)


class StagePlacement(BaseModel):
    """Explicit stage-space coordinates. Aspect-independent, but still manual."""

    model_config = ConfigDict(frozen=True)

    mode: Literal["stage"] = "stage"
    point: StagePoint


Placement = Annotated[
    AutoPlacement | SlotPlacement | AnchorPlacement | StagePlacement,
    Field(discriminator="mode"),
]


class ObjectStyle(BaseModel):
    """Per-object overrides. Colors are *role names* resolved against the
    project's style tokens, so a restyle propagates everywhere."""

    model_config = ConfigDict(frozen=True)

    color: str | None = Field(default=None, max_length=32)
    fill_color: str | None = Field(default=None, max_length=32)
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    stroke_width: float | None = Field(default=None, gt=0.0, le=20.0)
    scale: float = Field(default=1.0, gt=0.0, le=10.0)
    rotation: float = Field(default=0.0, ge=-360.0, le=360.0)


class SceneObject(BaseModel):
    """A thing that can appear on stage.

    ``kind`` and ``props.kind`` are cross-checked so the discriminator can never
    disagree with the payload -- a mismatch would otherwise surface as a confusing
    renderer error far from its cause.
    """

    model_config = ConfigDict(frozen=True)

    id: Slug
    kind: ObjectKind
    props: ObjectProps = Field(discriminator="kind")
    label: str | None = Field(default=None, max_length=120)
    placement: Placement = Field(default_factory=AutoPlacement)
    style: ObjectStyle = Field(default_factory=ObjectStyle)
    z: int = Field(default=0, ge=-100, le=100)
    tags: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _kind_matches_props(self) -> Self:
        if self.kind.value != self.props.kind:
            raise ValueError(
                f"object {self.id!r}: kind {self.kind.value!r} does not match "
                f"props kind {self.props.kind!r}"
            )
        return self

    @property
    def referenced_ids(self) -> set[str]:
        """Object ids this object depends on, for reference validation.

        Includes group members and symbolic arrow endpoints; a dangling one is an
        IR201 error, never something autofix quietly removes.
        """
        refs: set[str] = set()
        if isinstance(self.placement, AnchorPlacement):
            refs.add(self.placement.ref)
        props = self.props
        if props.kind == "group":
            refs.update(props.members)
        elif props.kind == "arrow":
            for endpoint in (props.start, props.end):
                if isinstance(endpoint, str):
                    refs.add(endpoint)
        return refs


class Group(BaseModel):
    """A named collection targeted as one unit by cues.

    Distinct from a ``group``-kind object: this adds no geometry and exists purely
    so a cue can say "fade out the whole constellation".
    """

    model_config = ConfigDict(frozen=True)

    id: Slug
    members: list[Slug] = Field(min_length=1, max_length=200)
    label: str | None = Field(default=None, max_length=120)


class Relationship(BaseModel):
    """A typed edge between objects.

    Feeds layout solvers (graph and tree read these), skill constraints (a
    ``flow`` must follow a ``connected_to``) and, for some kinds, geometry.
    """

    model_config = ConfigDict(frozen=True)

    kind: RelationKind
    source: Slug
    target: Slug
    label: str | None = Field(default=None, max_length=80)
