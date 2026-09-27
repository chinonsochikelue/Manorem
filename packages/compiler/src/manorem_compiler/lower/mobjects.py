"""Semantic object kinds become plan primitives.

Twenty-one :class:`~manorem_ir.ObjectKind` members lower onto twelve
:class:`~manorem_compiler.plan.Primitive` members, because a ``network`` is a group of
dots and lines once someone has decided where they go. That reduction is why a renderer
backend has twelve factories to write instead of twenty-one, and why adding a semantic
kind need not oblige any backend to change.

Three things happen per object, and they are separable on purpose.

**Composites decompose.** A ``graph`` is not a drawable; it is nodes and edges. So
graph, network, chart, diagram, timeline and particles each emit a ``group`` plus one
child per part, with ids of the form ``parent__part``. The children are marked
``synthetic`` -- nobody authored them -- and the parent's ``members`` names them, so a
cue targeting the graph animates the group and the renderer moves everything inside it.

**Colours resolve here, and nowhere earlier.** An object's ``style.color`` is a *role*
("primary", "accent") all the way through the IR, so restyling a project is one edit.
This is the last stage before a renderer, so this is where
:meth:`~manorem_ir.StyleTokens.color_for` runs. A role nobody declared resolves to the
primary colour rather than failing: an unknown role is a normalization defect P0
already had its chance at, and a plan that would not render because of a typo'd colour
name is a worse outcome than a slightly wrong hue.

**Every arg is a number, an enum string, or a validated storage key.** That is the §26
boundary, and it is structural: :data:`~manorem_compiler.plan.PlanValue` has no member
an expression could hide in. Asset keys go through
:func:`~manorem_core.validate_key`, and a key that fails is reported as ``CMP408``
rather than raising -- one bad image should cost its own mobject, not the compile.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping

from manorem_compiler.context import CompileContext, FrameMapping, SceneWork
from manorem_compiler.plan import MobjectSpec, PlanBounds, PlanValue, Primitive
from manorem_core import Code, UnsafePathError, validate_key
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
    ObjectStyle,
    ParticlesProps,
    PolygonProps,
    RectangleProps,
    StageBounds,
    StagePoint,
    StageSize,
    StyleTokens,
    SvgProps,
    TextProps,
    TimelineProps,
)

__all__ = ["lower_mobjects"]

#: Separator between a composite's id and one of its parts. Double underscore, so a
#: child id falls outside the ``Slug`` grammar and cannot collide with an authored one.
_PART = "__"

#: Radius of a node dot inside a decomposed graph or network, in stage units.
_NODE_RADIUS = 0.05

#: A node dot's own extent, so an edge's bounds cover the dots it joins.
_DOT_SIZE = StageSize(width=_NODE_RADIUS * 2.0, height=_NODE_RADIUS * 2.0)

#: Style for an object P2 invented. ``accent``, because a travelling packet or a
#: highlight ring exists to draw the eye -- and a :class:`SyntheticObject` carries no
#: style of its own, so this is the one place the choice can be made.
_SYNTHETIC_STYLE = ObjectStyle(color="accent")

#: ``z_index`` for a synthetic object: above anything authored, since a packet moving
#: along an edge or a ring around a node is meant to be seen over what it marks.
_SYNTHETIC_Z = 100

#: Extent of one box inside a decomposed ``diagram``.
_BOX = StageSize(width=0.28, height=0.14)

#: Extent of one tick label inside a decomposed ``timeline``.
_TICK = StageSize(width=0.16, height=0.06)

#: Fallback extent, matching P3's own so an object with no estimate measures the same
#: here as it did during layout.
_FALLBACK = StageSize(width=0.2, height=0.1)

#: Extents the composite kinds occupy, matching :mod:`~manorem_compiler.layout.measure`'s
#: table so a decomposed graph fills the space the layout solver reserved for it.
_NOMINAL: Mapping[str, StageSize] = {
    "axes": StageSize(width=0.9, height=0.7),
    "chart": StageSize(width=0.9, height=0.7),
    "diagram": StageSize(width=0.9, height=0.6),
    "graph": StageSize(width=0.9, height=0.9),
    "map": StageSize(width=1.2, height=0.7),
    "network": StageSize(width=0.9, height=0.9),
    "timeline": StageSize(width=1.4, height=0.3),
}

#: Which primitive each kind draws as. A composite maps to ``group`` and contributes
#: its parts through :func:`_children`.
_PRIMITIVE: Mapping[str, Primitive] = {
    "text": Primitive.TEXT,
    "math": Primitive.MATH,
    "circle": Primitive.CIRCLE,
    "rectangle": Primitive.RECTANGLE,
    "line": Primitive.LINE,
    "arrow": Primitive.ARROW,
    "dot": Primitive.DOT,
    "polygon": Primitive.POLYGON,
    "axes": Primitive.AXES,
    "image": Primitive.IMAGE,
    "svg": Primitive.SVG,
    # An icon renders as its own name: there is no icon font in M1, and inventing a
    # primitive no backend implements would be worse than a legible label.
    "icon": Primitive.TEXT,
    "globe": Primitive.CIRCLE,
    "group": Primitive.GROUP,
    "particles": Primitive.GROUP,
    "chart": Primitive.GROUP,
    "graph": Primitive.GROUP,
    "network": Primitive.GROUP,
    "diagram": Primitive.GROUP,
    "timeline": Primitive.GROUP,
    "map": Primitive.GROUP,
}


def _child_id(parent: str, *parts: str | int) -> str:
    return parent + _PART + _PART.join(str(p) for p in parts)


def _world_bounds(mapping: FrameMapping, box: StageBounds) -> PlanBounds:
    """A stage box in world units. Carried so the renderer never measures anything."""
    return PlanBounds(
        min_x=box.min_x * mapping.scale,
        min_y=box.min_y * mapping.scale,
        max_x=box.max_x * mapping.scale,
        max_y=box.max_y * mapping.scale,
    )


def _colors(style: ObjectStyle, tokens: StyleTokens) -> dict[str, PlanValue]:
    """An object's colour args, with roles resolved to hex.

    ``fill_color`` and ``stroke_width`` are omitted rather than defaulted when unset,
    so a renderer applies its primitive's own default instead of one invented here.
    """
    args: dict[str, PlanValue] = {
        "color": tokens.color_for(style.color if style.color is not None else "primary"),
        "opacity": style.opacity,
    }
    if style.fill_color is not None:
        args["fill_color"] = tokens.color_for(style.fill_color)
    if style.stroke_width is not None:
        args["stroke_width"] = style.stroke_width
    return args


def _report_unsafe_asset(ctx: CompileContext, work: SceneWork, object_id: str, key: str) -> None:
    ctx.bag.add(
        Code.CMP408_UNSAFE_ASSET_KEY,
        f"{object_id!r} refers to asset {key!r}, which is not a valid storage key",
        pointer=work.ptr("objects"),
        scene_id=work.id,
        object_id=object_id,
        hint="An asset is addressed by a storage key, not a filesystem path: no leading "
        "slash, no drive letter, and no `..` segment.",
    )


def _asset(ctx: CompileContext, work: SceneWork, object_id: str, key: str) -> str:
    """A checked storage key, or the empty string after reporting why it was refused.

    The check happens here because this is the boundary: past this point the key is in
    a plan a renderer will open. Reporting rather than raising keeps one bad image from
    costing the whole compile, and ``CMP408`` is an error, so nothing renders anyway
    until it is fixed.
    """
    try:
        return validate_key(key)
    except UnsafePathError:
        _report_unsafe_asset(ctx, work, object_id, key)
        return ""


def _typeset_args(props: TextProps | MathProps, tokens: StyleTokens) -> dict[str, PlanValue]:
    match props:
        case TextProps():
            return {
                "text": props.content,
                "size": tokens.size_for(props.role),
                "align": props.align,
            }
        case MathProps():
            return {"latex": props.latex, "size": tokens.size_for(props.role)}


def _shape_args(
    props: CircleProps | DotProps | GlobeProps | RectangleProps | IconProps | PolygonProps,
    mapping: FrameMapping,
) -> dict[str, PlanValue]:
    """Geometry in world units, because a radius is a length like any other."""
    match props:
        case CircleProps():
            return {"radius": mapping.length(props.radius), "filled": props.filled}
        case DotProps():
            return {"radius": mapping.length(props.radius)}
        case GlobeProps():
            return {"radius": mapping.length(props.radius), "filled": False}
        case RectangleProps():
            return {
                "width": mapping.length(props.width),
                "height": mapping.length(props.height),
                "corner_radius": mapping.length(props.corner_radius),
                "filled": props.filled,
            }
        case IconProps():
            return {"text": props.name, "size": props.size}
        case PolygonProps():
            flat: list[float] = []
            for p in props.points:
                flat.extend((p.x * mapping.scale, p.y * mapping.scale))
            return {"points": tuple(flat), "filled": props.filled}


def _endpoint(
    value: StagePoint | str, positions: Mapping[str, StagePoint], fallback: StagePoint
) -> StagePoint:
    """One arrow endpoint as a real point: literal, looked up, or the arrow's centre.

    A symbolic endpoint is what makes an arrow follow whatever the layout engine
    decided, and by this pass it has decided. An endpoint naming nothing collapses onto
    the arrow's own centre -- a degenerate arrow rather than a NaN, with the dangling
    reference already reported as ``IR201`` upstream.
    """
    if isinstance(value, StagePoint):
        return value
    return positions.get(value, fallback)


def _path_args(
    props: LineProps | ArrowProps,
    at: StagePoint,
    positions: Mapping[str, StagePoint],
    mapping: FrameMapping,
) -> dict[str, PlanValue]:
    """A segment's endpoints in world units."""
    match props:
        case LineProps():
            start, end = props.start, props.end
            extra: dict[str, PlanValue] = {"dashed": props.dashed}
        case ArrowProps():
            start = _endpoint(props.start, positions, at)
            end = _endpoint(props.end, positions, at)
            extra = {"double_headed": props.double_headed, "curved": props.curved}
    return {
        "start": (start.x * mapping.scale, start.y * mapping.scale),
        "end": (end.x * mapping.scale, end.y * mapping.scale),
        **extra,
    }


def _asset_args(
    ctx: CompileContext,
    work: SceneWork,
    object_id: str,
    props: ImageProps | SvgProps,
    mapping: FrameMapping,
) -> dict[str, PlanValue]:
    args: dict[str, PlanValue] = {"asset": _asset(ctx, work, object_id, props.asset)}
    if props.width is not None:
        args["width"] = mapping.length(props.width)
    return args


def _grouplike_args(
    props: AxesProps | ChartProps | GraphProps | NetworkProps | MapProps,
    mapping: FrameMapping,
) -> dict[str, PlanValue]:
    """Args for the kinds that carry a frame of their own, not just members."""
    size = _NOMINAL[props.kind]
    args: dict[str, PlanValue] = {
        "width": mapping.length(size.width),
        "height": mapping.length(size.height),
    }
    match props:
        case AxesProps():
            args |= {
                "x_range": tuple(float(v) for v in props.x_range),
                "y_range": tuple(float(v) for v in props.y_range),
                "show_grid": props.show_grid,
            }
        case ChartProps():
            args |= {"chart_type": props.chart_type, "series": len(props.series)}
        case MapProps():
            args |= {"projection": props.projection, "show_borders": props.show_borders}
        case GraphProps() | NetworkProps():
            args |= {"nodes": len(props.nodes), "edges": len(props.edges)}
    return args


def _args(
    ctx: CompileContext,
    work: SceneWork,
    object_id: str,
    props: ObjectProps,
    *,
    at: StagePoint,
    mapping: FrameMapping,
) -> dict[str, PlanValue]:
    """Constructor args for one props payload, in world units.

    A ``match`` over the discriminated union rather than a dispatch dict, for the same
    reason :mod:`~manorem_compiler.layout.measure` uses one: ``mypy --strict`` reports a
    missing return when the match is not exhaustive, so a twenty-second ``ObjectKind``
    fails the build here until someone gives it a rule.
    """
    match props:
        case TextProps() | MathProps():
            return _typeset_args(props, ctx.style)
        case (
            CircleProps()
            | DotProps()
            | GlobeProps()
            | RectangleProps()
            | IconProps()
            | PolygonProps()
        ):
            return _shape_args(props, mapping)
        case LineProps() | ArrowProps():
            return _path_args(props, at, work.positions, mapping)
        case ImageProps() | SvgProps():
            return _asset_args(ctx, work, object_id, props, mapping)
        case AxesProps() | ChartProps() | GraphProps() | NetworkProps() | MapProps():
            return _grouplike_args(props, mapping)
        case DiagramProps():
            return {"style": props.style, "boxes": len(props.boxes)}
        case TimelineProps():
            size = _NOMINAL["timeline"]
            return {
                "orientation": props.orientation,
                "width": mapping.length(size.width),
                "height": mapping.length(size.height),
            }
        case ParticlesProps():
            return {"count": props.count, "spread": mapping.length(props.spread)}
        case GroupProps():
            return {"members": len(props.members)}


def _spread(count: int, span: float) -> list[float]:
    """``count`` evenly spaced offsets across ``span``, centred on zero.

    One item sits at the middle rather than at an edge, which is what makes a
    single-node graph or a one-entry timeline look deliberate instead of misaligned.
    """
    if count <= 1:
        return [0.0] * count
    step = span / (count - 1)
    return [-span / 2.0 + index * step for index in range(count)]


def _ring(count: int, radius: float) -> list[StagePoint]:
    """``count`` points evenly around a circle, the first at the top.

    Starting at twelve o'clock and going clockwise, so a three-node graph reads as a
    triangle pointing up rather than sitting on a corner.
    """
    if count == 1:
        return [StagePoint(x=0.0, y=0.0)]
    turn = 2.0 * math.pi / count
    return [
        StagePoint(x=radius * math.sin(index * turn), y=radius * math.cos(index * turn))
        for index in range(count)
    ]


def _node_children(
    parent: str,
    props: GraphProps | NetworkProps,
    at: StagePoint,
    *,
    style: ObjectStyle,
    ctx: CompileContext,
    mapping: FrameMapping,
) -> Iterator[MobjectSpec]:
    """A graph or network as dots and lines, arranged in a ring around its centre.

    A ring rather than the scene's own layout solver: these nodes are *inside* one
    object's box, so the arrangement is a property of the composite and not of the
    scene. A dedicated graph layout is what the ``graph`` :class:`LayoutKind` is for,
    on objects the author actually named.
    """
    size = _NOMINAL[props.kind]
    radius = min(size.width, size.height) / 2.0 - _NODE_RADIUS
    places = {
        node.id: StagePoint(x=at.x + p.x, y=at.y + p.y)
        for node, p in zip(props.nodes, _ring(len(props.nodes), radius), strict=True)
    }
    colors = _colors(style, ctx.style)
    for edge in props.edges:
        start, end = places.get(edge.source), places.get(edge.target)
        if start is None or end is None:
            # An edge naming a node the graph does not declare: already an `IR201`, and
            # inventing an endpoint here would draw a line to nowhere.
            continue
        middle = StagePoint(x=(start.x + end.x) / 2.0, y=(start.y + end.y) / 2.0)
        segment = {
            "start": (start.x * mapping.scale, start.y * mapping.scale),
            "end": (end.x * mapping.scale, end.y * mapping.scale),
        }
        yield MobjectSpec(
            id=_child_id(parent, "edge", edge.source, edge.target),
            primitive=Primitive.ARROW if edge.directed else Primitive.LINE,
            args=colors
            | segment
            | ({"double_headed": False, "curved": False} if edge.directed else {"dashed": False}),
            position=mapping.point(middle),
            bounds=_world_bounds(
                mapping,
                StageBounds.around(start, _DOT_SIZE).union(StageBounds.around(end, _DOT_SIZE)),
            ),
            synthetic=True,
        )
    for node in props.nodes:
        place = places[node.id]
        yield MobjectSpec(
            id=_child_id(parent, "node", node.id),
            primitive=Primitive.DOT,
            args=colors | {"radius": mapping.length(_NODE_RADIUS)},
            position=mapping.point(place),
            bounds=_world_bounds(mapping, StageBounds.around(place, _DOT_SIZE)),
            synthetic=True,
        )


def _label_child(
    child_id: str,
    text: str,
    at: StagePoint,
    size: StageSize,
    *,
    args: Mapping[str, PlanValue],
    mapping: FrameMapping,
) -> MobjectSpec:
    """One piece of text inside a composite: a diagram box's caption, a timeline tick."""
    return MobjectSpec(
        id=child_id,
        primitive=Primitive.TEXT,
        args=dict(args) | {"text": text, "size": size.height, "align": "center"},
        position=mapping.point(at),
        bounds=_world_bounds(mapping, StageBounds.around(at, size)),
        synthetic=True,
    )


def _diagram_children(
    parent: str,
    props: DiagramProps,
    at: StagePoint,
    *,
    style: ObjectStyle,
    ctx: CompileContext,
    mapping: FrameMapping,
) -> Iterator[MobjectSpec]:
    """A diagram as labelled boxes, stacked along whichever axis its style implies.

    ``flow`` reads left to right because that is what an arrow between steps means;
    ``layered`` and ``block`` stack downward, because a layer diagram's top layer is
    the one on top.
    """
    size = _NOMINAL["diagram"]
    horizontal = props.style == "flow"
    span = (size.width - _BOX.width) if horizontal else (size.height - _BOX.height)
    colors = _colors(style, ctx.style)
    for index, (label, offset) in enumerate(
        zip(props.boxes, _spread(len(props.boxes), max(span, 0.0)), strict=True)
    ):
        place = StagePoint(
            x=at.x + (offset if horizontal else 0.0),
            y=at.y + (0.0 if horizontal else -offset),
        )
        yield MobjectSpec(
            id=_child_id(parent, "box", index),
            primitive=Primitive.RECTANGLE,
            args=colors
            | {
                "width": mapping.length(_BOX.width),
                "height": mapping.length(_BOX.height),
                "corner_radius": mapping.length(0.02),
                "filled": False,
            },
            position=mapping.point(place),
            bounds=_world_bounds(mapping, StageBounds.around(place, _BOX)),
            synthetic=True,
        )
        yield _label_child(
            _child_id(parent, "label", index), label, place, _TICK, args=colors, mapping=mapping
        )


def _timeline_children(
    parent: str,
    props: TimelineProps,
    at: StagePoint,
    *,
    style: ObjectStyle,
    ctx: CompileContext,
    mapping: FrameMapping,
) -> Iterator[MobjectSpec]:
    """A timeline as an axis, a tick per entry, and each entry's label beside it.

    Entry positions are the *authored* normalized ones rather than an even spread: a
    timeline's whole point is that the gaps mean something.
    """
    size = _NOMINAL["timeline"]
    horizontal = props.orientation == "horizontal"
    span = size.width if horizontal else size.height
    colors = _colors(style, ctx.style)
    ends = (
        (StagePoint(x=at.x - span / 2.0, y=at.y), StagePoint(x=at.x + span / 2.0, y=at.y))
        if horizontal
        else (StagePoint(x=at.x, y=at.y - span / 2.0), StagePoint(x=at.x, y=at.y + span / 2.0))
    )
    yield MobjectSpec(
        id=_child_id(parent, "axis"),
        primitive=Primitive.LINE,
        args=colors
        | {
            "start": (ends[0].x * mapping.scale, ends[0].y * mapping.scale),
            "end": (ends[1].x * mapping.scale, ends[1].y * mapping.scale),
            "dashed": False,
        },
        position=mapping.point(at),
        bounds=_world_bounds(
            mapping,
            StageBounds.around(ends[0], _DOT_SIZE).union(StageBounds.around(ends[1], _DOT_SIZE)),
        ),
        synthetic=True,
    )
    for index, entry in enumerate(props.entries):
        along = -span / 2.0 + entry.position * span
        place = (
            StagePoint(x=at.x + along, y=at.y) if horizontal else StagePoint(x=at.x, y=at.y + along)
        )
        yield MobjectSpec(
            id=_child_id(parent, "tick", index),
            primitive=Primitive.DOT,
            args=colors | {"radius": mapping.length(_NODE_RADIUS)},
            position=mapping.point(place),
            bounds=_world_bounds(mapping, StageBounds.around(place, _DOT_SIZE)),
            synthetic=True,
        )
        beside = (
            StagePoint(x=place.x, y=place.y - _TICK.height * 1.5)
            if horizontal
            else StagePoint(x=place.x + _TICK.width, y=place.y)
        )
        yield _label_child(
            _child_id(parent, "label", index),
            entry.label,
            beside,
            _TICK,
            args=colors,
            mapping=mapping,
        )


def _chart_children(
    parent: str,
    props: ChartProps,
    at: StagePoint,
    *,
    style: ObjectStyle,
    ctx: CompileContext,
    mapping: FrameMapping,
) -> Iterator[MobjectSpec]:
    """A chart as bars: one per value, heights proportional to the largest value.

    Every ``chart_type`` decomposes to bars in M1. A line chart drawn as bars is
    honest about being a placeholder in a way a wrong line would not be, and the
    ``dataviz`` skill is the extension point that makes it a real plot.
    """
    size = _NOMINAL["chart"]
    values = [value for series in props.series for value in series.values]
    peak = max((abs(value) for value in values), default=1.0) or 1.0
    slot = size.width / max(len(values), 1)
    width = slot * 0.7
    colors = _colors(style, ctx.style)
    for index, (value, offset) in enumerate(
        zip(values, _spread(len(values), size.width - slot), strict=True)
    ):
        height = max(abs(value) / peak * size.height, 0.01)
        place = StagePoint(x=at.x + offset, y=at.y - size.height / 2.0 + height / 2.0)
        yield MobjectSpec(
            id=_child_id(parent, "bar", index),
            primitive=Primitive.RECTANGLE,
            args=colors
            | {
                "width": mapping.length(width),
                "height": mapping.length(height),
                "corner_radius": 0.0,
                "filled": True,
            },
            position=mapping.point(place),
            bounds=_world_bounds(
                mapping, StageBounds.around(place, StageSize(width=width, height=height))
            ),
            synthetic=True,
        )


def _particle_children(
    parent: str,
    props: ParticlesProps,
    at: StagePoint,
    *,
    style: ObjectStyle,
    ctx: CompileContext,
    mapping: FrameMapping,
) -> Iterator[MobjectSpec]:
    """A particle cloud as dots on a deterministic spiral.

    A spiral rather than random jitter, because a plan is a committed artifact and a
    golden that changes between runs is not a regression test. It reads as a cloud at
    the sizes a cloud is used at.
    """
    size = StageSize(width=props.particle_radius * 2.0, height=props.particle_radius * 2.0)
    colors = _colors(style, ctx.style)
    turn = 2.399963229728653  # the golden angle, which is what makes a spiral look even
    for index in range(props.count):
        reach = props.spread * math.sqrt((index + 0.5) / props.count)
        place = StagePoint(
            x=at.x + reach * math.cos(index * turn), y=at.y + reach * math.sin(index * turn)
        )
        yield MobjectSpec(
            id=_child_id(parent, "mote", index),
            primitive=Primitive.DOT,
            args=colors | {"radius": mapping.length(props.particle_radius)},
            position=mapping.point(place),
            bounds=_world_bounds(mapping, StageBounds.around(place, size)),
            synthetic=True,
        )


def _map_children(
    parent: str,
    props: MapProps,
    at: StagePoint,
    *,
    style: ObjectStyle,
    ctx: CompileContext,
    mapping: FrameMapping,
) -> Iterator[MobjectSpec]:
    """A map as its own outline, and nothing else.

    No coastlines: M1 has no geography data, and a rectangle labelled with its region
    is a placeholder anyone can read as one. Real geography arrives with the
    ``geography`` skill, which is why ``region`` and ``projection`` stay in the args --
    a skill-backed renderer has what it needs without the IR changing.
    """
    size = _NOMINAL["map"]
    colors = _colors(style, ctx.style)
    yield MobjectSpec(
        id=_child_id(parent, "frame"),
        primitive=Primitive.RECTANGLE,
        args=colors
        | {
            "width": mapping.length(size.width),
            "height": mapping.length(size.height),
            "corner_radius": 0.0,
            "filled": False,
        },
        position=mapping.point(at),
        bounds=_world_bounds(mapping, StageBounds.around(at, size)),
        synthetic=True,
    )
    label = StagePoint(x=at.x, y=at.y + size.height / 2.0 + _TICK.height)
    yield _label_child(
        _child_id(parent, "region"), props.region, label, _TICK, args=colors, mapping=mapping
    )


def _children(
    parent: str,
    props: ObjectProps,
    at: StagePoint,
    *,
    style: ObjectStyle,
    ctx: CompileContext,
    mapping: FrameMapping,
) -> tuple[MobjectSpec, ...]:
    """The parts a composite decomposes into, or nothing for a kind that draws itself.

    Not a ``match`` over the whole union: the composite kinds are the exception here,
    and the exhaustiveness that matters -- every kind gets *args* -- is already proved
    in :func:`_args`. A new composite kind that forgets to decompose renders as an
    empty group, which is visible immediately rather than a type error away.
    """
    match props:
        case GraphProps() | NetworkProps():
            return tuple(_node_children(parent, props, at, style=style, ctx=ctx, mapping=mapping))
        case DiagramProps():
            return tuple(
                _diagram_children(parent, props, at, style=style, ctx=ctx, mapping=mapping)
            )
        case TimelineProps():
            return tuple(
                _timeline_children(parent, props, at, style=style, ctx=ctx, mapping=mapping)
            )
        case ChartProps():
            return tuple(_chart_children(parent, props, at, style=style, ctx=ctx, mapping=mapping))
        case ParticlesProps():
            return tuple(
                _particle_children(parent, props, at, style=style, ctx=ctx, mapping=mapping)
            )
        case MapProps():
            return tuple(_map_children(parent, props, at, style=style, ctx=ctx, mapping=mapping))
        case _:
            return ()


def _introduced(work: SceneWork) -> frozenset[str]:
    """Ids some step brings onto the stage, so they can start hidden.

    Read from the *steps* rather than the cues, because P2 is what decided which
    objects a cue actually touches -- a ``flow`` introduces a packet nobody wrote down,
    and a group target has already been expanded to its members by here.
    """
    registry = work.skills.registry
    return frozenset(
        step.target_id
        for step in work.steps
        if (decl := registry.get(step.op)) is not None and decl.introduces
    )


def _members(
    work: SceneWork, props: ObjectProps, children: tuple[MobjectSpec, ...]
) -> tuple[str, ...]:
    """What a ``group`` primitive contains: authored members, or decomposed parts.

    An authored ``group`` names ids; a composite owns children it invented. Members
    that resolve to nothing are dropped, since a group of a missing object is already
    an ``IR201`` and a renderer asked to group a name it has no mobject for would fail
    at construction.
    """
    if isinstance(props, GroupProps):
        return tuple(member for member in props.members if member in work.symbols.objects)
    return tuple(child.id for child in children)


def lower_mobjects(ctx: CompileContext, work: SceneWork) -> tuple[MobjectSpec, ...]:
    """Every drawable one scene needs: authored objects, composite parts, synthetics.

    Order is authored objects in declaration order, each immediately followed by its
    own children, then the synthetic objects P2 invented. Declaration order because it
    is the only order an author can predict, and a composite's parts next to it because
    a plan is read by people as well as by renderers. ``z_index`` is what actually
    decides what covers what, so the ordering costs nothing.
    """
    mapping = work.frame
    introduced = _introduced(work)
    specs: list[MobjectSpec] = []
    for obj in work.scene.objects:
        at = work.positions.get(obj.id, StagePoint(x=0.0, y=0.0))
        box = work.bounds.get(obj.id, StageBounds.around(at, _FALLBACK))
        children = _children(obj.id, obj.props, at, style=obj.style, ctx=ctx, mapping=mapping)
        specs.append(
            MobjectSpec(
                id=obj.id,
                primitive=_PRIMITIVE[obj.props.kind],
                args=_colors(obj.style, ctx.style)
                | _args(ctx, work, obj.id, obj.props, at=at, mapping=mapping),
                position=mapping.point(at),
                bounds=_world_bounds(mapping, box),
                z_index=obj.z,
                initial_visible=obj.id not in introduced,
                members=_members(work, obj.props, children),
            )
        )
        specs.extend(children)
    for invented in work.synthetic:
        at = invented.at if invented.at is not None else StagePoint(x=0.0, y=0.0)
        size = work.sizes.get(invented.id, _FALLBACK)
        specs.append(
            MobjectSpec(
                id=invented.id,
                primitive=_PRIMITIVE[invented.props.kind],
                args=_colors(_SYNTHETIC_STYLE, ctx.style)
                | _args(ctx, work, invented.id, invented.props, at=at, mapping=mapping),
                position=mapping.point(at),
                bounds=_world_bounds(mapping, StageBounds.around(at, size)),
                # Above the authored objects: a packet travelling along an edge or a
                # ring around a highlighted node exists to be seen over what it marks.
                z_index=_SYNTHETIC_Z,
                initial_visible=False,
                synthetic=True,
            )
        )
    return tuple(specs)
