"""The RenderPlan: what a renderer executes, and nothing more.

This is the second of the two IR layers, and the reason most of the system's
guarantees are cheap. Where :mod:`manorem_ir` is symbolic -- ``after(cue, 0.2)``,
``StagePoint(-0.5, 0.3)``, ``show`` -- a plan is *finished*: absolute world
coordinates, frame numbers, one closed set of primitives, one closed set of
animations. Nothing here needs solving, and nothing here can be misread.

Three properties follow from that, and each one pays for a requirement:

**It is the security boundary, structurally.** Every field is a number, a member
of a closed enum, or a storage key that :func:`~manorem_core.validate_key` has
already accepted. There is no field an expression could hide in, so there is
nothing for the renderer to evaluate -- ``exec`` is not avoided by policy, it is
unreachable because a plan cannot express code.

**It is hashable, so the regression gate is fast.** A plan is pure JSON with a
stable key order, so ``compile(ir) -> plan`` is snapshot-testable and the primary
test for the whole compiler runs in milliseconds instead of minutes of rendering.

**It is renderer-agnostic.** ``Primitive`` and ``PlanAnim`` name what to draw and
how it changes, not which class draws it. A future ManimGL or WebGL backend
inherits layout, scheduling and camera work by consuming the same plan.

The primitive vocabulary is deliberately *smaller* than
:class:`~manorem_ir.ObjectKind`: twenty-one semantic kinds lower onto twelve
drawables, because a ``network`` is a group of dots and lines once someone has
decided where they go.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from manorem_core import Slug
from manorem_ir import Aspect, Easing, FormatSpec, StyleTokens

__all__ = [
    "CAMERA_TRACK_ID",
    "PLAN_VERSION",
    "AudioCue",
    "CameraFrameAnim",
    "CreateAnim",
    "DrawAnim",
    "FadeInAnim",
    "FadeOutAnim",
    "FlashAnim",
    "GrowAnim",
    "IndicateAnim",
    "MobjectSpec",
    "MoveAlongPathAnim",
    "MoveToAnim",
    "PlanAnim",
    "PlanBounds",
    "PlanEvent",
    "PlanValue",
    "Point3",
    "Primitive",
    "RenderPlan",
    "ReplacementTransformAnim",
    "RotateAnim",
    "ScaleAnim",
    "ScenePlan",
    "SetColorAnim",
    "SetOpacityAnim",
    "ShrinkAnim",
    "Track",
    "TransformAnim",
    "UncreateAnim",
    "WriteAnim",
]

#: Bumped when the plan shape changes incompatibly. Renderers refuse a plan whose
#: major version they do not implement rather than guessing at a missing field.
PLAN_VERSION = "1.0"

#: Track id for the camera. Not a valid :data:`~manorem_core.Slug` -- slugs must
#: start with a letter -- so it can never collide with an authored object id.
CAMERA_TRACK_ID = "__camera__"

#: A world-space coordinate triple. Manim is 3D even when the scene is not.
Point3 = tuple[float, float, float]

#: What may appear in :attr:`MobjectSpec.args`. The union *is* the §26 boundary:
#: numbers, closed-enum strings, validated storage keys, and flat sequences of
#: those. A callable, a format string, or a nested object has nowhere to sit.
PlanValue = bool | int | float | str | tuple[float, ...] | tuple[str, ...]


class Primitive(StrEnum):
    """The drawables a renderer must implement. Closed, and smaller than ``ObjectKind``.

    Pass P7 lowers every semantic kind onto these, so a renderer backend has
    twelve factories to write rather than twenty-one -- and adding a semantic kind
    does not oblige a backend to change at all.
    """

    TEXT = "text"
    MATH = "math"
    CIRCLE = "circle"
    RECTANGLE = "rectangle"
    LINE = "line"
    ARROW = "arrow"
    DOT = "dot"
    POLYGON = "polygon"
    AXES = "axes"
    IMAGE = "image"
    SVG = "svg"
    GROUP = "group"


class PlanBounds(BaseModel):
    """An axis-aligned box in world units, carried rather than recomputed.

    The renderer is an interpreter, not a geometry engine: it must be able to emit
    a scene manifest (which mobject occupied what, when) without measuring
    anything. Pass P6 already knows these numbers, so it writes them down.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    min_x: float
    min_y: float
    max_x: float
    max_y: float

    @property
    def width(self) -> float:
        return self.max_x - self.min_x

    @property
    def height(self) -> float:
        return self.max_y - self.min_y

    @property
    def center(self) -> tuple[float, float]:
        return ((self.min_x + self.max_x) / 2.0, (self.min_y + self.max_y) / 2.0)


class MobjectSpec(BaseModel):
    """One drawable, fully resolved: what it is, where it is, how big it ended up."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    primitive: Primitive
    #: Constructor arguments. Numbers, enum strings and validated storage keys
    #: only -- see :data:`PlanValue`.
    args: dict[str, PlanValue] = Field(default_factory=dict)
    position: Point3 = (0.0, 0.0, 0.0)
    bounds: PlanBounds
    z_index: int = 0
    #: Objects a cue introduces start hidden; a decorative backdrop does not.
    initial_visible: bool = False
    #: Ids of the mobjects this one groups, empty unless ``primitive`` is ``group``.
    members: tuple[str, ...] = ()
    #: Set when this mobject was invented by a P2 expansion (a travelling packet,
    #: a highlight ring) rather than authored. Debug aid; never changes rendering.
    synthetic: bool = False


# ---------------------------------------------------------------------------
# Animations
# ---------------------------------------------------------------------------
# Discriminated on ``kind`` so the renderer dispatches through a lookup table and
# an unknown animation is a parse failure rather than a silent no-op.


class _Anim(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CreateAnim(_Anim):
    """Draw a shape's outline into being."""

    kind: Literal["create"] = "create"


class WriteAnim(_Anim):
    """Write text or math stroke by stroke."""

    kind: Literal["write"] = "write"


class DrawAnim(_Anim):
    """Trace the border, then fill -- the deliberate version of ``create``."""

    kind: Literal["draw"] = "draw"


class FadeInAnim(_Anim):
    kind: Literal["fade_in"] = "fade_in"
    shift: Point3 = (0.0, 0.0, 0.0)


class FadeOutAnim(_Anim):
    kind: Literal["fade_out"] = "fade_out"
    shift: Point3 = (0.0, 0.0, 0.0)


class GrowAnim(_Anim):
    kind: Literal["grow"] = "grow"


class ShrinkAnim(_Anim):
    kind: Literal["shrink"] = "shrink"


class UncreateAnim(_Anim):
    """Un-draw an outline: the reverse of ``create``."""

    kind: Literal["uncreate"] = "uncreate"


class TransformAnim(_Anim):
    """Morph this mobject into another, leaving the source in place."""

    kind: Literal["transform"] = "transform"
    into: str


class ReplacementTransformAnim(_Anim):
    """Morph this mobject into another and retire the source."""

    kind: Literal["replacement_transform"] = "replacement_transform"
    into: str


class MoveToAnim(_Anim):
    kind: Literal["move_to"] = "move_to"
    point: Point3


class MoveAlongPathAnim(_Anim):
    """Follow an explicit polyline. Points are world-space and pre-solved."""

    kind: Literal["move_along_path"] = "move_along_path"
    points: tuple[Point3, ...] = Field(min_length=2)


class ScaleAnim(_Anim):
    kind: Literal["scale"] = "scale"
    factor: float = Field(gt=0.0)


class RotateAnim(_Anim):
    kind: Literal["rotate"] = "rotate"
    radians: float


class SetColorAnim(_Anim):
    kind: Literal["set_color"] = "set_color"
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")


class SetOpacityAnim(_Anim):
    """Dim or restore. How ``focus`` de-emphasises everything else."""

    kind: Literal["set_opacity"] = "set_opacity"
    opacity: float = Field(ge=0.0, le=1.0)


class IndicateAnim(_Anim):
    kind: Literal["indicate"] = "indicate"
    scale_factor: float = Field(default=1.2, gt=0.0)
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")


class FlashAnim(_Anim):
    kind: Literal["flash"] = "flash"
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    line_length: float = Field(default=0.2, gt=0.0)


class CameraFrameAnim(_Anim):
    """Move the camera. Only ever appears on the camera track."""

    kind: Literal["camera_frame"] = "camera_frame"
    center: Point3
    width: float = Field(gt=0.0)


PlanAnim = Annotated[
    CreateAnim
    | WriteAnim
    | DrawAnim
    | FadeInAnim
    | FadeOutAnim
    | GrowAnim
    | ShrinkAnim
    | UncreateAnim
    | TransformAnim
    | ReplacementTransformAnim
    | MoveToAnim
    | MoveAlongPathAnim
    | ScaleAnim
    | RotateAnim
    | SetColorAnim
    | SetOpacityAnim
    | IndicateAnim
    | FlashAnim
    | CameraFrameAnim,
    Field(discriminator="kind"),
]


# ---------------------------------------------------------------------------
# Tracks and scenes
# ---------------------------------------------------------------------------


class PlanEvent(BaseModel):
    """One animation on one target, placed on the frame grid.

    Frames, not seconds: the renderer must not round, because two renderers
    rounding differently would make golden frame hashes backend-specific.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    start_frame: int = Field(ge=0)
    duration_frames: int = Field(ge=1)
    anim: PlanAnim
    easing: Easing = Easing.SMOOTH
    #: The cue this came from. Carried for tracing and inspector highlighting; the
    #: renderer ignores it.
    cue_id: str | None = None

    @property
    def end_frame(self) -> int:
        return self.start_frame + self.duration_frames


class Track(BaseModel):
    """One lane of events for one target, in start order and never overlapping.

    A lane is what makes frame-exact scheduling possible: the renderer turns each
    into ``Succession(Wait(gap), anim, ...)`` and plays all lanes in a single
    group, so no animation's timing depends on another's. That only works while
    the gaps are non-negative, which is why events within a lane may not overlap.

    ``target_id`` is therefore *not* unique across :attr:`ScenePlan.tracks`. Two
    animations genuinely meant to run at once on the same mobject -- a dot moving
    while it changes colour -- are split across two lanes by pass P7, which is
    exactly what ``self.play(a, b)`` does in hand-written Manim. Rejecting the
    overlap instead would forbid a legitimate direction for an implementation
    reason.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    target_id: str
    events: tuple[PlanEvent, ...] = ()

    @property
    def end_frame(self) -> int:
        return max((e.end_frame for e in self.events), default=0)


class AudioCue(BaseModel):
    """A narration segment on the frame grid, for the compositor and subtitles.

    Present even with no audio: M1 renders silent video, and these are what the
    SRT and WebVTT are written from. ``asset`` fills in when a TTS provider exists,
    which changes numbers rather than architecture.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    segment_id: str
    start_frame: int = Field(ge=0)
    duration_frames: int = Field(ge=0)
    role: str
    text: str
    #: Storage key of the rendered speech, once there is any. ``None`` in M1.
    asset: str | None = None


class ScenePlan(BaseModel):
    """One scene, ready to render. Self-contained: no cross-scene references."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: Slug
    #: Total length. Every event ends at or before this frame -- checked by P8.
    duration_frames: int = Field(ge=1)
    background: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    mobjects: tuple[MobjectSpec, ...] = ()
    tracks: tuple[Track, ...] = ()
    camera: Track = Track(target_id=CAMERA_TRACK_ID)
    audio_cues: tuple[AudioCue, ...] = ()
    #: Frames of overlap with the following scene, from the authored transition.
    #: The compositor reads it; the renderer does not.
    transition_out_frames: int = Field(default=0, ge=0)

    def mobject(self, mobject_id: str) -> MobjectSpec | None:
        return next((m for m in self.mobjects if m.id == mobject_id), None)

    @property
    def mobject_ids(self) -> tuple[str, ...]:
        return tuple(m.id for m in self.mobjects)

    @property
    def event_count(self) -> int:
        return sum(len(t.events) for t in self.tracks) + len(self.camera.events)


class RenderPlan(BaseModel):
    """The compiler's whole output: numbers, enums and validated keys.

    Content-addressable by :func:`~manorem_core.sha256_of` of its canonical JSON,
    which is what lets an unchanged scene reuse a cached video and what makes the
    16:9 / 9:16 / 1:1 goldens a real aspect contract.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    plan_version: str = PLAN_VERSION
    project_id: Slug
    #: Resolved from the IR's own ``FormatSpec``, so aspect, resolution and fps
    #: travel together and no downstream stage re-derives them.
    format: FormatSpec
    style: StyleTokens
    scenes: tuple[ScenePlan, ...] = ()

    @property
    def aspect(self) -> Aspect:
        return self.format.aspect

    @property
    def fps(self) -> int:
        return self.format.fps

    @property
    def total_frames(self) -> int:
        return sum(scene.duration_frames for scene in self.scenes)

    @property
    def duration_seconds(self) -> float:
        return self.total_frames / self.format.fps

    def scene(self, scene_id: str) -> ScenePlan | None:
        return next((s for s in self.scenes if s.id == scene_id), None)
