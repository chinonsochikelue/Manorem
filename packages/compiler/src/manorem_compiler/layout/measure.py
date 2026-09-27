"""How big a thing is, before anything has been drawn.

Layout has to know extents to avoid collisions, but measuring a real text mobject
means asking Manim, and Manim is a subprocess the compiler must not depend on: a
compile that needed the renderer would stop being a pure function, committed plans
would stop being reproducible, and ``LayoutSolver`` could no longer promise to be
deterministic.

So extents are *estimated*, from props and the type scale, by a table of closed-form
rules. Two consequences worth being honest about:

* The numbers are approximations. Glyph advance widths vary by font and by
  character; ``0.52em`` average is a fit, not a measurement. Layout gaps are sized
  with that slack in mind.
* They are nonetheless **exact inputs**: the same IR always yields the same estimate,
  which is what makes the overlap lints and the RenderPlan goldens meaningful.

The renderer may find a text mobject slightly wider than estimated. That is a
readability question, not a correctness one, and it belongs to the Visual QA stage --
which measures pixels, because by then there are some.
"""

from __future__ import annotations

from manorem_ir import (
    ArrowProps,
    AxesProps,
    ChartProps,
    CircleProps,
    DiagramProps,
    DotProps,
    GlobeProps,
    GraphProps,
    GroupProps,
    IconProps,
    ImageProps,
    LineProps,
    MapProps,
    MathProps,
    NetworkProps,
    ObjectProps,
    ParticlesProps,
    PolygonProps,
    RectangleProps,
    SceneObject,
    StagePoint,
    StageSize,
    StyleTokens,
    SvgProps,
    TextProps,
    TimelineProps,
)

__all__ = ["estimate_props_size", "estimate_size", "estimate_sizes"]

#: Mean glyph advance as a fraction of the type size. Fitted to a sans-serif face;
#: wide enough that a heading of capitals does not overflow its estimate.
_CHAR_WIDTH = 0.52
#: Math sets denser per character but taller, from subscripts and radicals.
_MATH_CHAR_WIDTH = 0.46
#: Line box height as a multiple of the type size.
_LINE_HEIGHT = 1.32

#: Extents for kinds whose props say nothing about size. Deliberately generous: a
#: placeholder that under-claims space produces a layout that looks fine in the plan
#: and collides on screen.
_NOMINAL: dict[str, tuple[float, float]] = {
    "map": (1.2, 0.7),
    "diagram": (0.9, 0.6),
    "graph": (0.9, 0.9),
    "network": (0.9, 0.9),
    "chart": (0.9, 0.7),
    "axes": (0.9, 0.7),
    "image": (0.6, 0.45),
    "svg": (0.5, 0.5),
    "group": (0.4, 0.4),
}


def _text_size(content: str, size: float, per_char: float) -> StageSize:
    lines = content.splitlines() or [""]
    widest = max((len(line) for line in lines), default=0)
    return StageSize(
        width=max(widest * size * per_char, size * per_char),
        height=len(lines) * size * _LINE_HEIGHT,
    )


def _span(a: StagePoint, b: StagePoint) -> StageSize:
    """A segment's bounding box, with a floor so an axis-aligned line is not zero."""
    return StageSize(width=max(abs(b.x - a.x), 0.02), height=max(abs(b.y - a.y), 0.02))


def _typeset_size(props: TextProps | MathProps, style: StyleTokens) -> StageSize:
    """Text and math: line count times leading, widest line times mean advance."""
    match props:
        case TextProps():
            return _text_size(props.content, style.size_for(props.role), _CHAR_WIDTH)
        case MathProps():
            return _text_size(props.latex, style.size_for(props.role), _MATH_CHAR_WIDTH)


def _shape_size(
    props: CircleProps
    | GlobeProps
    | DotProps
    | RectangleProps
    | IconProps
    | ParticlesProps
    | TimelineProps,
) -> StageSize:
    """Kinds whose props already state their extent, in one form or another."""
    match props:
        case CircleProps() | GlobeProps() | DotProps():
            return StageSize(width=props.radius * 2.0, height=props.radius * 2.0)
        case RectangleProps():
            return StageSize(width=props.width, height=props.height)
        case IconProps():
            return StageSize(width=props.size, height=props.size)
        case ParticlesProps():
            return StageSize(width=props.spread, height=props.spread)
        case TimelineProps():
            return (
                StageSize(width=1.4, height=0.3)
                if props.orientation == "horizontal"
                else StageSize(width=0.3, height=1.4)
            )


def _path_size(props: LineProps | ArrowProps | PolygonProps) -> StageSize:
    """Kinds defined by points: the bounding box of the points they carry."""
    match props:
        case LineProps():
            return _span(props.start, props.end)
        case ArrowProps():
            # A symbolic endpoint is resolved after layout, so an arrow between two
            # objects has no extent to contribute and must not push them apart.
            if isinstance(props.start, StagePoint) and isinstance(props.end, StagePoint):
                return _span(props.start, props.end)
            return StageSize(width=0.02, height=0.02)
        case PolygonProps():
            xs = [p.x for p in props.points]
            ys = [p.y for p in props.points]
            return StageSize(
                width=max(max(xs) - min(xs), 0.02), height=max(max(ys) - min(ys), 0.02)
            )


def _nominal_size(
    props: ImageProps
    | SvgProps
    | GraphProps
    | ChartProps
    | AxesProps
    | MapProps
    | DiagramProps
    | NetworkProps
    | GroupProps,
) -> StageSize:
    """Kinds whose props say nothing usable about extent, so the table decides."""
    match props:
        case ImageProps() | SvgProps() if props.width is not None:
            # No intrinsic ratio is knowable without opening the asset, which the
            # compiler will not do; 4:3 is the least surprising guess.
            return StageSize(width=props.width, height=props.width * 0.75)
        case _:
            width, height = _NOMINAL[props.kind]
            return StageSize(width=width, height=height)


def _props_size(props: ObjectProps, style: StyleTokens) -> StageSize:
    """Unscaled extent for one props payload.

    A ``match`` over the discriminated union rather than a dispatch dict, because
    ``mypy --strict`` narrows each branch and reports a missing return when the match
    is not exhaustive -- so a twenty-second ``ObjectKind`` fails the build here until
    someone gives it a rule. A dict of callables would type-check happily and return
    the nominal fallback forever.

    Grouped into four helpers rather than one long chain only so each stays inside the
    branch limits; the outer match is still what proves every kind is covered.
    """
    match props:
        case TextProps() | MathProps():
            return _typeset_size(props, style)
        case (
            CircleProps()
            | GlobeProps()
            | DotProps()
            | RectangleProps()
            | IconProps()
            | ParticlesProps()
            | TimelineProps()
        ):
            return _shape_size(props)
        case LineProps() | ArrowProps() | PolygonProps():
            return _path_size(props)
        case (
            ImageProps()
            | SvgProps()
            | GraphProps()
            | ChartProps()
            | AxesProps()
            | MapProps()
            | DiagramProps()
            | NetworkProps()
            | GroupProps()
        ):
            return _nominal_size(props)


def estimate_props_size(props: ObjectProps, style: StyleTokens) -> StageSize:
    """Stage extent of a bare props payload, with no style scale applied.

    Public because a P2 expansion invents :class:`~manorem_skills.SyntheticObject`\\ s
    -- a travelling packet, a decomposed graph node -- which carry ``props`` but are
    not :class:`~manorem_ir.SceneObject`\\ s, and pass P7 still owes every mobject a
    ``bounds``. Same rules as an authored object of that kind, which is the point: a
    synthetic dot must not measure differently from one someone wrote down.
    """
    return _props_size(props, style)


def estimate_size(obj: SceneObject, style: StyleTokens) -> StageSize:
    """Stage extent of one object, including its style scale."""
    base = _props_size(obj.props, style)
    factor = obj.style.scale
    if factor == 1.0:
        return base
    # StageSize caps at 4.0 per axis; a scaled-up estimate clamps rather than raises,
    # because an oversized object is a layout defect to report, not a parse failure.
    return StageSize(
        width=min(base.width * factor, 4.0),
        height=min(base.height * factor, 4.0),
    )


def estimate_sizes(objects: list[SceneObject], style: StyleTokens) -> dict[str, StageSize]:
    """Extents for a whole scene, keyed by object id."""
    return {obj.id: estimate_size(obj, style) for obj in objects}
