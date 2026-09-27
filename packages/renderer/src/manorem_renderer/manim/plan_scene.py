"""The one module a Manim render subprocess ever executes.

There is no code generation anywhere in this system. A :class:`PlanScene` reads a
finished :class:`~manorem_compiler.RenderPlan` -- numbers, closed enums and
validated keys -- and *interprets* it through two lookup tables: one from
:class:`~manorem_compiler.Primitive` to a Manim mobject, one from an animation
``kind`` to a Manim :class:`Animation`. Nothing here is ``eval``'d, ``exec``'d, or
built from a string, because a plan cannot express any of those things (§26). A
readable Manim source dump may be emitted elsewhere as a debug artifact, but it is
never on the execution path; this interpreter is.

The timing model is the one verified in the design probe. Each
:class:`~manorem_compiler.Track` becomes a ``Succession`` of ``Wait`` gaps and
animations, padded so every lane is exactly the scene's length; all lanes play in
a single ``AnimationGroup(lag_ratio=0)`` with ``run_time`` fixed to
``duration_frames / fps``. No animation's timing depends on another's, and the
frame count is exact rather than approximate.

The plan arrives by path in the ``MANOREM_PLAN_PATH`` environment variable, set by
:class:`~manorem_renderer.ManimRenderer` before it spawns ``manim``; the scene
re-validates it on the way in as defence in depth.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from manim import (
    AnimationGroup as MAnimationGroup,
)
from manim import (
    Arrow,
    Axes,
    Circle,
    Create,
    CurvedArrow,
    DashedLine,
    Dot,
    DoubleArrow,
    DrawBorderThenFill,
    FadeIn,
    FadeOut,
    Flash,
    Group,
    GrowFromCenter,
    ImageMobject,
    Indicate,
    Line,
    MathTex,
    MoveAlongPath,
    MovingCameraScene,
    Polygon,
    Rectangle,
    ReplacementTransform,
    Rotate,
    RoundedRectangle,
    ShrinkToCenter,
    Succession,
    SVGMobject,
    Text,
    Transform,
    Uncreate,
    VMobject,
    Wait,
    Write,
    config,
    rate_functions,
)
from numpy import array as np_array

from manorem_compiler import (
    CAMERA_TRACK_ID,
    PLAN_VERSION,
    MobjectSpec,
    PlanEvent,
    Primitive,
    RenderPlan,
    ScenePlan,
    Track,
)
from manorem_compiler.plan import (
    CameraFrameAnim,
    CreateAnim,
    DrawAnim,
    FadeInAnim,
    FadeOutAnim,
    FlashAnim,
    GrowAnim,
    IndicateAnim,
    MoveAlongPathAnim,
    MoveToAnim,
    Point3,
    ReplacementTransformAnim,
    RotateAnim,
    ScaleAnim,
    SetColorAnim,
    SetOpacityAnim,
    ShrinkAnim,
    TransformAnim,
    UncreateAnim,
    WriteAnim,
)
from manorem_ir import Easing

__all__ = ["MOBJECT_FACTORIES", "PlanScene", "build_animation", "build_mobject", "load_plan"]

#: Environment variable naming the plan JSON to render. Set by ``ManimRenderer``.
PLAN_ENV = "MANOREM_PLAN_PATH"

Registry = dict[str, Any]


def load_plan(path: Path | None = None) -> RenderPlan:
    """Read and re-validate the plan the subprocess was handed.

    The renderer already validated this plan before writing it; parsing it again
    here is defence in depth (§26), so a plan tampered with on disk between spawn
    and read still cannot smuggle anything past the pydantic models.
    """
    source = path if path is not None else Path(os.environ[PLAN_ENV])
    plan = RenderPlan.model_validate_json(source.read_text(encoding="utf-8"))
    if plan.plan_version.split(".")[0] != PLAN_VERSION.split(".")[0]:
        message = f"plan_version {plan.plan_version!r} incompatible with {PLAN_VERSION!r}"
        raise ValueError(message)
    return plan


def _rate(easing: Easing) -> Callable[[float], float]:
    """The Manim rate function an :class:`Easing` names.

    Easing values are exactly ``rate_functions`` member names, but the coupling is
    made here rather than assumed on either side.
    """
    rate: Callable[[float], float] = getattr(rate_functions, easing.value, rate_functions.smooth)
    return rate


def _pt(point: Point3) -> Any:
    """A plan ``Point3`` as a Manim vector."""
    return np_array([point[0], point[1], point[2]])


def _xy(point: tuple[float, ...]) -> Any:
    """A 2-tuple stage-plane point as a Manim vector, z pinned to zero."""
    return np_array([point[0], point[1], 0.0])


def _stroke(mob: Any, args: dict[str, Any]) -> Any:
    """Apply the resolved stroke colour and width the compiler wrote into ``args``."""
    color = args.get("color")
    if color is not None:
        mob.set_color(str(color))
    width = args.get("stroke_width")
    if width is not None:
        mob.set_stroke(width=float(width))
    return mob


def _fill(mob: Any, args: dict[str, Any]) -> Any:
    """Fill a shape only when the plan says ``filled``; otherwise leave it hollow."""
    if args.get("filled"):
        fill = str(args.get("fill_color", args.get("color", "#FFFFFF")))
        mob.set_fill(fill, opacity=float(args.get("opacity", 1.0)))
    else:
        mob.set_fill(opacity=0.0)
    return mob


def _place(mob: Any, spec: MobjectSpec) -> Any:
    """Centre a mobject on its resolved ``position``.

    Only for primitives whose geometry is authored relative to their own centre
    (text, circles, boxes). Line/arrow/polygon carry absolute world coordinates
    and are left where they were built.
    """
    mob.move_to(_pt(spec.position))
    return mob


def _fit_height(mob: Any, args: dict[str, Any]) -> None:
    size = args.get("size")
    if size is not None and mob.height > 0:
        mob.scale_to_fit_height(float(size))


def _text(spec: MobjectSpec) -> Any:
    args: dict[str, Any] = spec.args
    mob = Text(str(args["text"]), color=str(args.get("color", "#FFFFFF")))
    _fit_height(mob, args)
    return _place(mob, spec)


def _math(spec: MobjectSpec) -> Any:
    args: dict[str, Any] = spec.args
    mob = MathTex(str(args["latex"]), color=str(args.get("color", "#FFFFFF")))
    _fit_height(mob, args)
    return _place(mob, spec)


def _circle(spec: MobjectSpec) -> Any:
    args: dict[str, Any] = spec.args
    mob = Circle(radius=float(args["radius"]))
    _fill(_stroke(mob, args), args)
    return _place(mob, spec)


def _rectangle(spec: MobjectSpec) -> Any:
    args: dict[str, Any] = spec.args
    width = float(args["width"])
    height = float(args["height"])
    corner = float(args.get("corner_radius", 0.0))
    mob = (
        RoundedRectangle(corner_radius=corner, width=width, height=height)
        if corner > 0.0
        else Rectangle(width=width, height=height)
    )
    _fill(_stroke(mob, args), args)
    return _place(mob, spec)


def _dot(spec: MobjectSpec) -> Any:
    args: dict[str, Any] = spec.args
    mob = Dot(radius=float(args.get("radius", 0.08)), color=str(args.get("color", "#FFFFFF")))
    return _place(mob, spec)


def _polygon(spec: MobjectSpec) -> Any:
    args: dict[str, Any] = spec.args
    flat = tuple(float(v) for v in args["points"])
    verts = [np_array([flat[i], flat[i + 1], 0.0]) for i in range(0, len(flat) - 1, 2)]
    mob = Polygon(*verts)
    _fill(_stroke(mob, args), args)
    return mob


def _line(spec: MobjectSpec) -> Any:
    args: dict[str, Any] = spec.args
    start = _xy(args["start"])
    end = _xy(args["end"])
    mob = DashedLine(start, end) if args.get("dashed") else Line(start, end)
    return _stroke(mob, args)


def _arrow(spec: MobjectSpec) -> Any:
    args: dict[str, Any] = spec.args
    start = _xy(args["start"])
    end = _xy(args["end"])
    if args.get("curved"):
        mob = CurvedArrow(start, end)
    elif args.get("double_headed"):
        mob = DoubleArrow(start, end)
    else:
        mob = Arrow(start, end)
    return _stroke(mob, args)


def _axes(spec: MobjectSpec) -> Any:
    args: dict[str, Any] = spec.args
    mob = Axes(
        x_range=list(args["x_range"]),
        y_range=list(args["y_range"]),
        x_length=float(args["width"]),
        y_length=float(args["height"]),
    )
    _stroke(mob, args)
    return _place(mob, spec)


def _image(spec: MobjectSpec) -> Any:
    args: dict[str, Any] = spec.args
    mob = ImageMobject(str(args["asset"]))
    width = args.get("width")
    if width is not None:
        mob.scale_to_fit_width(float(width))
    return _place(mob, spec)


def _svg(spec: MobjectSpec) -> Any:
    args: dict[str, Any] = spec.args
    mob = SVGMobject(str(args["asset"]))
    width = args.get("width")
    if width is not None:
        mob.scale_to_fit_width(float(width))
    _stroke(mob, args)
    return _place(mob, spec)


#: Every drawable primitive except ``GROUP``, which needs the registry of its
#: already-built children and is handled in :func:`build_mobject`.
MOBJECT_FACTORIES: dict[Primitive, Callable[[MobjectSpec], Any]] = {
    Primitive.TEXT: _text,
    Primitive.MATH: _math,
    Primitive.CIRCLE: _circle,
    Primitive.RECTANGLE: _rectangle,
    Primitive.DOT: _dot,
    Primitive.POLYGON: _polygon,
    Primitive.LINE: _line,
    Primitive.ARROW: _arrow,
    Primitive.AXES: _axes,
    Primitive.IMAGE: _image,
    Primitive.SVG: _svg,
}


def build_mobject(spec: MobjectSpec, registry: Registry) -> Any:
    """Turn one :class:`MobjectSpec` into a Manim mobject.

    A ``GROUP`` gathers children the registry already holds; every other
    primitive comes from :data:`MOBJECT_FACTORIES`. The ``z_index`` is applied
    uniformly so the plan's stacking order is honoured.
    """
    if spec.primitive is Primitive.GROUP:
        members = [registry[m] for m in spec.members if m in registry]
        group = Group(*members)
        group.set_z_index(spec.z_index)
        return group
    mob = MOBJECT_FACTORIES[spec.primitive](spec)
    mob.set_z_index(spec.z_index)
    return mob


def _path(points: tuple[Point3, ...]) -> Any:
    path = VMobject()
    path.set_points_as_corners([_pt(p) for p in points])
    return path


def build_animation(target: Any, event: PlanEvent, fps: int, registry: Registry) -> Any:
    """The Manim animation one :class:`PlanEvent` names, bound to its target.

    Matches on the animation's concrete type so mypy proves every arm reads only
    fields that arm's model actually has, and so a new ``PlanAnim`` member is a
    compile-time hole here rather than a silent runtime skip. ``run_time`` is the
    event's own frame span; nothing scales it later.
    """
    anim = event.anim
    run_time = event.duration_frames / fps
    rate = _rate(event.easing)
    match anim:
        case CreateAnim():
            return Create(target, run_time=run_time, rate_func=rate)
        case WriteAnim():
            return Write(target, run_time=run_time, rate_func=rate)
        case DrawAnim():
            return DrawBorderThenFill(target, run_time=run_time, rate_func=rate)
        case FadeInAnim(shift=shift):
            return FadeIn(target, shift=_pt(shift), run_time=run_time, rate_func=rate)
        case FadeOutAnim(shift=shift):
            return FadeOut(target, shift=_pt(shift), run_time=run_time, rate_func=rate)
        case GrowAnim():
            return GrowFromCenter(target, run_time=run_time, rate_func=rate)
        case ShrinkAnim():
            return ShrinkToCenter(target, run_time=run_time, rate_func=rate)
        case UncreateAnim():
            return Uncreate(target, run_time=run_time, rate_func=rate)
        case TransformAnim(into=into):
            return Transform(target, registry[into], run_time=run_time, rate_func=rate)
        case ReplacementTransformAnim(into=into):
            return ReplacementTransform(target, registry[into], run_time=run_time, rate_func=rate)
        case MoveToAnim(point=point):
            return target.animate(run_time=run_time, rate_func=rate).move_to(_pt(point))
        case MoveAlongPathAnim(points=points):
            return MoveAlongPath(target, _path(points), run_time=run_time, rate_func=rate)
        case ScaleAnim(factor=factor):
            return target.animate(run_time=run_time, rate_func=rate).scale(factor)
        case RotateAnim(radians=radians):
            return Rotate(target, angle=radians, run_time=run_time, rate_func=rate)
        case SetColorAnim(color=color):
            return target.animate(run_time=run_time, rate_func=rate).set_color(color)
        case SetOpacityAnim(opacity=opacity):
            return target.animate(run_time=run_time, rate_func=rate).set_opacity(opacity)
        case IndicateAnim(scale_factor=scale_factor, color=color):
            extra = {"color": color} if color is not None else {}
            return Indicate(
                target, scale_factor=scale_factor, run_time=run_time, rate_func=rate, **extra
            )
        case FlashAnim(color=color, line_length=line_length):
            extra = {"color": color} if color is not None else {}
            return Flash(
                target, line_length=line_length, run_time=run_time, rate_func=rate, **extra
            )
        case CameraFrameAnim(center=center, width=width):
            return (
                target.animate(run_time=run_time, rate_func=rate)
                .move_to(_pt(center))
                .set(width=width)
            )
    message = f"unhandled animation kind: {anim.kind!r}"  # pragma: no cover
    raise ValueError(message)  # pragma: no cover


class PlanScene(MovingCameraScene):
    """The interpreter Manim runs. Reads the plan, plays every scene in order.

    One ``construct`` renders all of the plan's scenes back to back into a single
    file; the compositor (a later stage) is what stitches independently-rendered
    scenes, but a whole-plan render is what Slice 1 needs and what the timing
    probe verified. Between scenes the stage is cleared and the camera reset so no
    state leaks across a cut.
    """

    def construct(self) -> None:
        plan = load_plan()
        default_width = float(config.frame_width)
        for scene in plan.scenes:
            self._render_scene(scene, plan.fps, default_width)

    def _render_scene(self, scene: ScenePlan, fps: int, default_width: float) -> None:
        self.camera.background_color = scene.background
        registry: Registry = {}
        for spec in scene.mobjects:
            if spec.primitive is Primitive.GROUP:
                continue
            registry[spec.id] = build_mobject(spec, registry)
            if spec.initial_visible and not spec.synthetic:
                self.add(registry[spec.id])
        for spec in scene.mobjects:
            if spec.primitive is not Primitive.GROUP:
                continue
            registry[spec.id] = build_mobject(spec, registry)
            if spec.initial_visible:
                self.add(registry[spec.id])

        lanes = [
            lane
            for track in scene.tracks
            if (lane := self._lane(track, scene.duration_frames, fps, registry)) is not None
        ]
        camera_registry: Registry = {CAMERA_TRACK_ID: self.camera.frame}
        camera_lane = self._lane(scene.camera, scene.duration_frames, fps, camera_registry)
        if camera_lane is not None:
            lanes.append(camera_lane)

        run_time = scene.duration_frames / fps
        if lanes:
            self.play(MAnimationGroup(*lanes, lag_ratio=0.0), run_time=run_time)
        else:
            self.wait(run_time)

        self.clear()
        self.camera.frame.move_to(np_array([0.0, 0.0, 0.0]))
        self.camera.frame.set(width=default_width)

    def _lane(self, track: Track, total_frames: int, fps: int, registry: Registry) -> Any | None:
        """One track as a padded ``Succession``, or ``None`` if it has no target.

        Leading and inter-event ``Wait`` gaps place each animation at its exact
        start frame; a trailing ``Wait`` pads the lane to the full scene length so
        every lane in the group shares one duration and none is rescaled.
        """
        target = registry.get(track.target_id)
        if target is None:
            return None
        segments: list[Any] = []
        cursor = 0
        for event in track.events:
            gap = event.start_frame - cursor
            if gap > 0:
                segments.append(Wait(gap / fps))
            segments.append(build_animation(target, event, fps, registry))
            cursor = event.end_frame
        tail = total_frames - cursor
        if tail > 0:
            segments.append(Wait(tail / fps))
        if not segments:
            return None
        return Succession(*segments)
