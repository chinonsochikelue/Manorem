"""Semantic steps become concrete animations.

The last semantic decision in the compiler. A :class:`~manorem_compiler.context.ScheduledStep`
still says ``show`` -- an intent -- and a renderer needs ``Create`` or ``Write`` or
``FadeIn``. Choosing between them needs to know what kind of thing is being shown, which
is why this runs after P7 has built the mobjects rather than inside P2 with the expansion.

**A path is resolved here, not carried.** A ``flow`` step arrives holding
``{"from": "phone", "to": "satellite"}`` -- symbolic, because P2 ran before anything had
a position. By now P3 has solved both and P6 has a scale, so the step lowers to a
:class:`~manorem_compiler.plan.MoveAlongPathAnim` with explicit world-space points. The
renderer never resolves a name.

**A curve is a polyline.** Manim can draw a real arc, but a plan holding one would mean
two backends interpolating it differently, and a golden frame hash that is
backend-specific is not a regression test. So a curved path is sampled here, into a
fixed number of points, and every renderer traces the same shape.

**A step whose intent has no animation is dropped, loudly.** ``simulate`` with no skill
never reaches this module -- P2 rejected it -- but a skill's expansion is free to emit
any operation, and one this table cannot realize becomes ``CMP402`` rather than a
silently missing beat.
"""

from __future__ import annotations

from collections.abc import Mapping

from manorem_compiler.context import CompileContext, FrameMapping, SceneWork, ScheduledStep
from manorem_compiler.layout import content_region
from manorem_compiler.params import choice, flag, number, text
from manorem_compiler.plan import (
    CreateAnim,
    DrawAnim,
    FadeInAnim,
    FadeOutAnim,
    FlashAnim,
    GrowAnim,
    IndicateAnim,
    MobjectSpec,
    MoveAlongPathAnim,
    MoveToAnim,
    PlanAnim,
    Point3,
    Primitive,
    ReplacementTransformAnim,
    ScaleAnim,
    SetColorAnim,
    SetOpacityAnim,
    ShrinkAnim,
    TransformAnim,
    UncreateAnim,
    WriteAnim,
)
from manorem_core import Code
from manorem_ir import ParamValue, SemanticOp, StagePoint, StyleTokens

__all__ = ["anim_for"]

#: How far a curved path bows off the straight line between its endpoints, as a
#: fraction of the chord's length. Enough to read as deliberate, little enough that two
#: curves between neighbouring pairs do not cross.
_BOW = 0.18

#: Points a curved path is sampled into. A straight path uses two, because a polyline
#: through collinear points *is* the line.
_ARC_POINTS = 12

#: How far a ``reveal`` slides in from, in stage units.
_REVEAL_SHIFT = 0.35

#: Scale a ``highlight`` pulse grows to before returning.
_PULSE = 1.15

#: How much an ``accumulate`` grows its target. Modest: a quantity is building up, not
#: an object arriving.
_ACCUMULATE_SCALE = 1.25

#: Fraction of a compared object's own extent used as the gap between neighbours.
_COMPARE_PITCH = 1.35

#: ``show`` styles, in the order :data:`~manorem_ir.CORE_OPERATIONS` declares them.
_SHOW_STYLES = ("create", "write", "fade", "grow", "draw")

#: ``hide`` styles, likewise.
_HIDE_STYLES = ("fade", "shrink", "uncreate")

#: Which primitives are drawn stroke by stroke rather than outlined into being. A
#: ``show`` on text is a ``Write``; on a circle it is a ``Create``. That distinction is
#: the whole reason the choice waits until P7 has built the mobject.
_TYPESET = frozenset({Primitive.TEXT, Primitive.MATH})

#: Unit direction a ``reveal`` arrives from. "left" means it enters *from* the left, so
#: the shift it fades in across starts negative on x.
_FROM: Mapping[str, tuple[float, float]] = {
    "left": (-1.0, 0.0),
    "right": (1.0, 0.0),
    "up": (0.0, 1.0),
    "down": (0.0, -1.0),
}


def _report_unrealizable(ctx: CompileContext, work: SceneWork, step: ScheduledStep) -> None:
    ctx.bag.add(
        Code.CMP402_UNSUPPORTED_INTENT,
        f"{step.op.value} on {step.target_id!r} has no animation this plan can express",
        pointer=work.ptr("timeline"),
        scene_id=work.id,
        object_id=step.target_id,
        hint="The operation expanded into a step the plan has no animation for. A skill "
        "supplying an operation must expand it into steps the compiler can realize.",
    )


def _color(params: Mapping[str, ParamValue], tokens: StyleTokens) -> str | None:
    """A step's ``color`` param as hex, or ``None`` when it named none.

    Resolved through the style tokens like every other colour, so a step saying
    ``color="accent"`` picks up a restyle for free.
    """
    role = text(params, "color")
    return tokens.color_for(role) if role is not None else None


def _at(work: SceneWork, object_id: str) -> StagePoint:
    return work.positions.get(object_id, StagePoint(x=0.0, y=0.0))


def _curve(start: StagePoint, end: StagePoint, *, curved: bool) -> tuple[StagePoint, ...]:
    """A path between two points: two of them straight, sampled when it bows.

    The bow is perpendicular to the chord and scaled by its length, so a long hop and a
    short one curve by the same *proportion* -- which is what makes several flows across
    one diagram look like a set rather than a collection of accidents.
    """
    if not curved:
        return (start, end)
    dx, dy = end.x - start.x, end.y - start.y
    points: list[StagePoint] = []
    for index in range(_ARC_POINTS):
        along = index / (_ARC_POINTS - 1)
        lift = 4.0 * along * (1.0 - along) * _BOW
        points.append(
            StagePoint(x=start.x + dx * along - dy * lift, y=start.y + dy * along + dx * lift)
        )
    return tuple(points)


def _world(mapping: FrameMapping, points: tuple[StagePoint, ...]) -> tuple[Point3, ...]:
    return tuple(mapping.point(p) for p in points)


def _path_anim(step: ScheduledStep, work: SceneWork, mapping: FrameMapping) -> PlanAnim | None:
    """A travelling step as explicit motion between two now-solved endpoints."""
    source, destination = text(step.params, "from"), text(step.params, "to")
    if source is None or destination is None:
        return None
    points = _curve(
        _at(work, source),
        _at(work, destination),
        curved=flag(step.params, "curved", default=False),
    )
    return MoveAlongPathAnim(points=_world(mapping, points))


def _appear(spec: MobjectSpec, style: str) -> PlanAnim:
    """How something arrives. ``create`` defers to what the mobject actually is."""
    match style:
        case "write":
            return WriteAnim()
        case "fade":
            return FadeInAnim()
        case "grow":
            return GrowAnim()
        case "draw":
            return DrawAnim()
        case _:
            return WriteAnim() if spec.primitive in _TYPESET else CreateAnim()


def _vanish(style: str) -> PlanAnim:
    match style:
        case "shrink":
            return ShrinkAnim()
        case "uncreate":
            return UncreateAnim()
        case _:
            return FadeOutAnim()


def _highlight(step: ScheduledStep, tokens: StyleTokens) -> PlanAnim:
    """Attention without motion: a pulse, a flash, or a change of colour.

    ``circle`` lowers to a flash rather than inventing a ring, because a step cannot add
    a mobject by the time this runs and a flash is the same gesture. The gap is honest:
    the ring an author asked for is a P2 expansion nobody has written yet.
    """
    color = _color(step.params, tokens)
    match choice(step.params, "style", ("pulse", "flash", "circle", "color"), "pulse"):
        case "flash" | "circle":
            return FlashAnim(color=color)
        case "color":
            return SetColorAnim(color=color if color is not None else tokens.color_for("accent"))
        case _:
            return IndicateAnim(scale_factor=_PULSE, color=color)


def _compare(step: ScheduledStep, work: SceneWork, mapping: FrameMapping) -> PlanAnim:
    """Where one of several compared objects ends up: its slot in an evenly spaced row.

    The row is centred on the scene's own content region rather than on the objects'
    current centroid, because a comparison is a *new* arrangement -- centring it on
    wherever the objects happen to be would let one badly placed member drag the whole
    row off centre. Pitch comes from the object's own extent, so wide things get wide
    slots and the gaps read as equal.
    """
    index = int(number(step.params, "index", 0.0))
    total = max(int(number(step.params, "count", 1.0)), 1)
    horizontal = (
        choice(step.params, "axis", ("horizontal", "vertical"), "horizontal") == "horizontal"
    )
    size = work.sizes.get(step.target_id)
    extent = 0.3 if size is None else (size.width if horizontal else size.height)
    offset = (index - (total - 1) / 2.0) * extent * _COMPARE_PITCH
    spec = work.scene.layout
    middle = content_region(spec, spec.region).center
    place = (
        StagePoint(x=middle.x + offset, y=middle.y)
        if horizontal
        else StagePoint(x=middle.x, y=middle.y - offset)
    )
    return MoveToAnim(point=mapping.point(place))


def _become(step: ScheduledStep, *, replace_default: bool) -> PlanAnim | None:
    """A transform, replacing the source or not. ``None`` when no destination was named."""
    into = text(step.params, "into")
    if into is None:
        return None
    if flag(step.params, "replace", default=replace_default):
        return ReplacementTransformAnim(into=into)
    return TransformAnim(into=into)


def anim_for(
    ctx: CompileContext,
    work: SceneWork,
    step: ScheduledStep,
    spec: MobjectSpec,
    mapping: FrameMapping,
) -> PlanAnim | None:
    """One scheduled step as one animation, or ``None`` after reporting why not.

    A ``match`` over :class:`~manorem_ir.SemanticOp` rather than a dispatch dict, so
    ``mypy --strict`` names any operation this table has no answer for -- a twentieth
    semantic op fails the build here until someone decides what it looks like.
    """
    match step.op:
        case SemanticOp.SHOW:
            return _appear(spec, choice(step.params, "style", _SHOW_STYLES, "create"))
        case SemanticOp.HIDE:
            return _vanish(choice(step.params, "style", _HIDE_STYLES, "fade"))
        case SemanticOp.FLOW | SemanticOp.PROPAGATE:
            travel = _path_anim(step, work, mapping)
            if travel is None:
                _report_unrealizable(ctx, work, step)
            return travel
        case SemanticOp.COMPARE:
            return _compare(step, work, mapping)
        case SemanticOp.TRANSFORM | SemanticOp.SPLIT | SemanticOp.MERGE:
            became = _become(step, replace_default=True)
            if became is None:
                _report_unrealizable(ctx, work, step)
            return became
        case SemanticOp.MORPH:
            # Never replacing: a morph is a change of form, and the source stays alive.
            became = _become(step, replace_default=False)
            if became is None:
                _report_unrealizable(ctx, work, step)
            return became
        case SemanticOp.REVEAL:
            toward_x, toward_y = _FROM[choice(step.params, "direction", tuple(_FROM), "left")]
            shift = mapping.length(_REVEAL_SHIFT)
            return FadeInAnim(shift=(toward_x * shift, toward_y * shift, 0.0))
        case SemanticOp.HIGHLIGHT:
            return _highlight(step, ctx.style)
        case SemanticOp.FOCUS:
            # The camera half is P5's. This is the dimming, which P2 emitted as an
            # explicit opacity per object precisely so it needs no running state here.
            return SetOpacityAnim(opacity=number(step.params, "opacity", 1.0))
        case SemanticOp.TRACE:
            return DrawAnim()
        case SemanticOp.ACCUMULATE:
            # Growing toward a value, with no numeric axis to grow along in M1: a scale
            # reads as accumulation without pretending the number is plotted.
            return ScaleAnim(factor=_ACCUMULATE_SCALE)
        case (
            SemanticOp.CONNECT
            | SemanticOp.DISCONNECT
            | SemanticOp.SIMULATE
            | SemanticOp.ZOOM_TO
            | SemanticOp.PAN_TO
        ):
            # `connect` and `disconnect` always expand into show/hide of a link object,
            # `simulate` needs a skill, and camera work lives on the camera track.
            # Reaching here means a skill emitted a step holding one of these, which is
            # a real gap rather than something to paper over.
            _report_unrealizable(ctx, work, step)
            return None
