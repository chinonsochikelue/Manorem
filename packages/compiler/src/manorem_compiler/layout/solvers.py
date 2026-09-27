"""The built-in layout solvers: one per :class:`~manorem_ir.LayoutKind`.

The author states intent -- "these three things sit side by side", "this is a tree" --
and a solver turns it into stage coordinates. That division is the reason the AI never
computes positions, and the reason one authored scene renders to three aspect ratios:
solvers work entirely in stage space, and mapping stage space to a frame is a
different pass's job.

Every solver obeys the same three rules, which are what the snapshot goldens rest on:

* **Total.** Every id in ``request.object_ids`` gets a point. A solver that skipped
  one would leave an object at the origin with nothing saying why.
* **Deterministic.** No clock, no unseeded randomness, no dict-iteration order --
  ids are processed in the order given, and that order comes from the scene.
* **Quantized.** Results are rounded to :data:`GRID_EPS`. Trigonometric libm results
  differ in the last bit between platforms, and an unrounded radial layout would make
  a committed plan Windows-specific.

Solvers see only *auto-placed* objects. Explicit stage coordinates, named slots and
anchored placements are resolved by pass P3 around them, so "put the hub in the
middle and let the rest ring it" needs no special solver support.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from manorem_ir import (
    LayoutKind,
    LayoutSlot,
    LayoutSpec,
    RelationKind,
    StageBounds,
    StagePoint,
    StageSize,
)
from manorem_skills import LayoutRequest, LayoutSolver

__all__ = [
    "BUILTIN_SOLVERS",
    "DEGRADED_KINDS",
    "GRID_EPS",
    "LayoutRule",
    "content_region",
    "dispatch",
    "point",
    "quantize",
    "slot_regions",
    "solve_centered",
    "solve_flow",
    "solve_freeform",
    "solve_graph",
    "solve_grid",
    "solve_horizontal",
    "solve_map",
    "solve_radial",
    "solve_split",
    "solve_stack",
    "solve_timeline",
    "solve_tree",
    "solve_vertical",
    "solver_for",
    "sub_request",
]

#: Stage-space resolution. Positions are rounded to this so a plan is reproducible
#: across platforms whose ``sin``/``cos`` disagree in the final bit.
GRID_EPS = 1e-6

#: Furthest a solver may place a centre. Matches ``StagePoint``'s own bound, so a
#: crowded layout clamps and gets reported by the off-stage lint rather than raising
#: a validation error from inside a solver.
_MAX_COORD = 2.0

#: Fallback extent for an id with no measured size. Small enough not to dominate a
#: layout, large enough not to read as zero-width.
_UNKNOWN = StageSize(width=0.2, height=0.1)


def quantize(value: float) -> float:
    """Snap one coordinate to the stage grid and clamp it to the addressable range."""
    clamped = max(-_MAX_COORD, min(_MAX_COORD, value))
    snapped = round(clamped / GRID_EPS) * GRID_EPS
    # ``round`` of a negative zero keeps the sign, which would make two otherwise
    # identical plans differ by ``-0.0`` vs ``0.0`` in JSON.
    return snapped + 0.0


def point(x: float, y: float) -> StagePoint:
    """A quantized stage point. Every solver returns points through this."""
    return StagePoint(x=quantize(x), y=quantize(y))


def _size(request: LayoutRequest, object_id: str) -> StageSize:
    return request.sizes.get(object_id, _UNKNOWN)


def _sizes(request: LayoutRequest) -> list[StageSize]:
    return [_size(request, oid) for oid in request.object_ids]


def _distribute(extents: Sequence[float], span: float, gap: float, align: str) -> list[float]:
    """Offsets along one axis for consecutive extents, per the alignment mode.

    Returns the *leading edge* of each item measured from the start of the span, so a
    caller can convert to a centre without knowing which axis it is working on.
    """
    total = sum(extents) + gap * max(len(extents) - 1, 0)
    if align == "space_between" and len(extents) > 1:
        slack = max(span - sum(extents), 0.0)
        step = slack / (len(extents) - 1)
        offsets: list[float] = []
        cursor = 0.0
        for extent in extents:
            offsets.append(cursor)
            cursor += extent + step
        return offsets
    start = {"start": 0.0, "end": span - total}.get(align, (span - total) / 2.0)
    offsets = []
    cursor = start
    for extent in extents:
        offsets.append(cursor)
        cursor += extent + gap
    return offsets


def _along_x(request: LayoutRequest, region: StageBounds) -> dict[str, StagePoint]:
    sizes = _sizes(request)
    offsets = _distribute(
        [s.width for s in sizes], region.width, request.spec.gap, request.spec.align
    )
    y = region.center.y
    return {
        oid: point(region.min_x + offset + size.width / 2.0, y)
        for oid, size, offset in zip(request.object_ids, sizes, offsets, strict=True)
    }


def _along_y(request: LayoutRequest, region: StageBounds) -> dict[str, StagePoint]:
    """Top to bottom, because that is reading order -- the first object leads."""
    sizes = _sizes(request)
    offsets = _distribute(
        [s.height for s in sizes], region.height, request.spec.gap, request.spec.align
    )
    x = region.center.x
    return {
        oid: point(x, region.max_y - offset - size.height / 2.0)
        for oid, size, offset in zip(request.object_ids, sizes, offsets, strict=True)
    }


def content_region(spec: LayoutSpec, region: StageBounds) -> StageBounds:
    """A region minus a spec's padding, shrunk only as far as it can go.

    Public because pass P3 needs the same answer a solver will get: slot regions are
    carved out of the padded region, and an anchored object is clamped to it. Padding
    that would invert the box is reduced instead of raising -- an over-padded layout is
    a crowded frame to report, not a parse failure.
    """
    pad = spec.padding
    if pad <= 0.0:
        return region
    room = min(region.width, region.height) / 2.0 - GRID_EPS
    return region.padded(-min(pad, max(room, 0.0)))


def _region(request: LayoutRequest) -> StageBounds:
    return content_region(request.spec, request.region)


# ---------------------------------------------------------------------------
# The solvers
# ---------------------------------------------------------------------------


def solve_centered(request: LayoutRequest) -> dict[str, StagePoint]:
    """One thing in the middle -- and if there are several, a centred column.

    Stacking would be the literal reading of "centered" for many objects, but two
    objects on the same point is never what anyone means by it, and it would fire the
    overlap lint on the most common layout an author writes.
    """
    region = _region(request)
    if len(request.object_ids) > 1:
        return _along_y(request, region)
    center = region.center
    return {oid: point(center.x, center.y) for oid in request.object_ids}


def solve_horizontal(request: LayoutRequest) -> dict[str, StagePoint]:
    """Side by side, in authored order, vertically centred in the region."""
    return _along_x(request, _region(request))


def solve_vertical(request: LayoutRequest) -> dict[str, StagePoint]:
    """Stacked, in authored order, horizontally centred in the region."""
    return _along_y(request, _region(request))


def _columns_for(count: int, columns: int | None, rows: int | None) -> int:
    if columns is not None:
        return columns
    if rows is not None:
        return max(math.ceil(count / rows), 1)
    return max(math.ceil(math.sqrt(count)), 1)


def solve_grid(request: LayoutRequest) -> dict[str, StagePoint]:
    """Row-major cells of equal size, filled left to right then top to bottom.

    Cells are uniform rather than fitted to their contents: a grid whose columns
    shifted with the width of one label would stop reading as a grid.
    """
    ids = request.object_ids
    if not ids:
        return {}
    region = _region(request)
    columns = _columns_for(len(ids), request.spec.columns, request.spec.rows)
    rows = max(math.ceil(len(ids) / columns), 1)
    cell_w = region.width / columns
    cell_h = region.height / rows
    placed: dict[str, StagePoint] = {}
    for index, oid in enumerate(ids):
        row, column = divmod(index, columns)
        placed[oid] = point(
            region.min_x + (column + 0.5) * cell_w,
            region.max_y - (row + 0.5) * cell_h,
        )
    return placed


def _ring_radius(region: StageBounds, sizes: Sequence[StageSize]) -> float:
    """Largest ring keeping every object inside the region."""
    margin = max((max(s.width, s.height) / 2.0 for s in sizes), default=0.0)
    return max(min(region.width, region.height) / 2.0 - margin, GRID_EPS)


def solve_radial(request: LayoutRequest) -> dict[str, StagePoint]:
    """Evenly spaced on a ring, counter-clockwise from ``start_angle``.

    Nothing is placed at the centre. A hub belongs at an explicit stage coordinate,
    which pass P3 resolves before the solver runs -- so "hub plus satellites" is
    authored as one placement and one radial layout, with no special case here.
    """
    ids = request.object_ids
    region = _region(request)
    center = region.center
    if len(ids) == 1:
        return {ids[0]: point(center.x, center.y)}
    radius = request.spec.radius
    if radius is None:
        radius = _ring_radius(region, _sizes(request))
    step = 360.0 / len(ids) if ids else 0.0
    placed: dict[str, StagePoint] = {}
    for index, oid in enumerate(ids):
        angle = math.radians(request.spec.start_angle + index * step)
        placed[oid] = point(
            center.x + radius * math.cos(angle), center.y + radius * math.sin(angle)
        )
    return placed


def _child_map(request: LayoutRequest) -> tuple[dict[str, list[str]], dict[str, str]]:
    """Children and parents from ``parent_of``, restricted to the ids being laid out.

    A second parent is ignored rather than reported: whether the hierarchy is well
    formed is a T2 question, and a solver that raised would turn one authoring
    mistake into a crash instead of a diagnostic.
    """
    ids = frozenset(request.object_ids)
    children: dict[str, list[str]] = {oid: [] for oid in request.object_ids}
    parents: dict[str, str] = {}
    for rel in request.relationships:
        if rel.kind is not RelationKind.PARENT_OF:
            continue
        if rel.source not in ids or rel.target not in ids or rel.target in parents:
            continue
        children[rel.source].append(rel.target)
        parents[rel.target] = rel.source
    return children, parents


def _tree_levels(request: LayoutRequest) -> list[list[str]]:
    """Ids grouped by depth, siblings kept adjacent by a pre-order walk."""
    children, parents = _child_map(request)
    seen: set[str] = set()
    levels: list[list[str]] = []
    roots = [oid for oid in request.object_ids if oid not in parents]
    stack = [(oid, 0) for oid in reversed(roots)]
    while stack:
        node, depth = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        while len(levels) <= depth:
            levels.append([])
        levels[depth].append(node)
        stack.extend((child, depth + 1) for child in reversed(children[node]))
    # A cycle among the parent edges leaves nodes unreached. They still need a point,
    # so they get their own bottom row; P1 has already reported the cycle.
    orphans = [oid for oid in request.object_ids if oid not in seen]
    if orphans:
        levels.append(orphans)
    return levels


def solve_tree(request: LayoutRequest) -> dict[str, StagePoint]:
    """Tiers top to bottom from ``parent_of`` edges, evenly spread within each tier."""
    if not request.object_ids:
        return {}
    region = _region(request)
    levels = _tree_levels(request)
    row_height = region.height / len(levels)
    placed: dict[str, StagePoint] = {}
    for depth, level in enumerate(levels):
        y = region.max_y - (depth + 0.5) * row_height
        step = region.width / len(level)
        for column, oid in enumerate(level):
            placed[oid] = point(region.min_x + (column + 0.5) * step, y)
    return placed


#: Relations a graph layout treats as adjacency. ``represents`` and ``derived_from``
#: describe what an object *means*, not what it is next to, so they pull nothing.
_GRAPH_RELATIONS = frozenset(
    {RelationKind.CONNECTED_TO, RelationKind.POINTS_TO, RelationKind.PARENT_OF}
)

#: Relaxation steps. Enough to untangle a few dozen nodes; fixed, because a
#: convergence test would make the result depend on floating-point luck.
_GRAPH_STEPS = 60

#: Per-step cooling. Displacements shrink geometrically so late steps settle.
_GRAPH_COOLING = 0.9


def _graph_pairs(request: LayoutRequest) -> list[tuple[str, str]]:
    """Undirected, de-duplicated edges among the ids being laid out."""
    ids = frozenset(request.object_ids)
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for rel in request.relationships:
        if rel.kind not in _GRAPH_RELATIONS or rel.source == rel.target:
            continue
        if rel.source not in ids or rel.target not in ids:
            continue
        key = (rel.source, rel.target) if rel.source < rel.target else (rel.target, rel.source)
        if key not in seen:
            seen.add(key)
            pairs.append(key)
    return pairs


def _force_step(
    positions: dict[str, list[float]],
    pairs: Sequence[tuple[str, str]],
    ideal: float,
    temperature: float,
) -> None:
    """One Fruchterman-Reingold relaxation, in place.

    Repulsion between every pair, attraction along every edge, then a move capped by
    ``temperature``. Ids are walked in insertion order, which is authored order, so
    the arithmetic sequence -- and therefore the result -- is fixed.
    """
    ids = list(positions)
    disp = {oid: [0.0, 0.0] for oid in ids}
    for index, a in enumerate(ids):
        for b in ids[index + 1 :]:
            ox = positions[a][0] - positions[b][0]
            oy = positions[a][1] - positions[b][1]
            force = ideal * ideal / max(ox * ox + oy * oy, GRID_EPS)
            disp[a][0] += ox * force
            disp[a][1] += oy * force
            disp[b][0] -= ox * force
            disp[b][1] -= oy * force
    for a, b in pairs:
        ox = positions[a][0] - positions[b][0]
        oy = positions[a][1] - positions[b][1]
        force = math.hypot(ox, oy) / ideal
        disp[a][0] -= ox * force
        disp[a][1] -= oy * force
        disp[b][0] += ox * force
        disp[b][1] += oy * force
    for oid in ids:
        magnitude = max(math.hypot(disp[oid][0], disp[oid][1]), GRID_EPS)
        limit = min(magnitude, temperature) / magnitude
        positions[oid][0] += disp[oid][0] * limit
        positions[oid][1] += disp[oid][1] * limit


def _fit_into(
    positions: Mapping[str, list[float]], region: StageBounds, sizes: Sequence[StageSize]
) -> dict[str, StagePoint]:
    """Scale and centre a free-floating cloud into the region, uniformly.

    Uniform on both axes on purpose: stretching a solved graph to fill a 9:16 region
    would distort the very adjacency the solver just worked out.
    """
    xs = [p[0] for p in positions.values()]
    ys = [p[1] for p in positions.values()]
    margin = max((max(s.width, s.height) / 2.0 for s in sizes), default=0.0)
    span_x = max(xs) - min(xs)
    span_y = max(ys) - min(ys)
    room_x = max(region.width - 2.0 * margin, GRID_EPS)
    room_y = max(region.height - 2.0 * margin, GRID_EPS)
    scale = min(
        room_x / span_x if span_x > GRID_EPS else 1.0,
        room_y / span_y if span_y > GRID_EPS else 1.0,
    )
    mid_x = (max(xs) + min(xs)) / 2.0
    mid_y = (max(ys) + min(ys)) / 2.0
    center = region.center
    return {
        oid: point(center.x + (p[0] - mid_x) * scale, center.y + (p[1] - mid_y) * scale)
        for oid, p in positions.items()
    }


#: How many overlap-relief sweeps run after a force-directed solve. Small on purpose:
#: this nudges neighbours apart, it does not re-solve the layout.
_SEPARATION_STEPS = 8


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _separate(
    placed: Mapping[str, StagePoint], request: LayoutRequest, region: StageBounds
) -> dict[str, StagePoint]:
    """Push overlapping boxes apart along whichever axis needs the smaller shove.

    Only the unstructured solvers use this. In a grid or a tree an overlap means the
    author asked for more than fits in the region, and quietly nudging cells would
    both break the arrangement and hide that from the overlap lint; in a
    force-directed graph there is no arrangement to preserve, and two nodes landing
    on top of each other is an artefact of the solve rather than anything authored.

    Centres are clamped back into the region, not boxes: an object that still
    overhangs is the off-stage lint's business, and moving it further would undo the
    separation this just did.
    """
    ids = list(placed)
    xs = {oid: placed[oid].x for oid in ids}
    ys = {oid: placed[oid].y for oid in ids}
    for _ in range(_SEPARATION_STEPS):
        moved = False
        for index, first in enumerate(ids):
            for second in ids[index + 1 :]:
                need_x = (_size(request, first).width + _size(request, second).width) / 2.0
                need_y = (_size(request, first).height + _size(request, second).height) / 2.0
                away_x = xs[first] - xs[second]
                away_y = ys[first] - ys[second]
                gap_x = need_x - abs(away_x)
                gap_y = need_y - abs(away_y)
                if gap_x <= 0.0 or gap_y <= 0.0:
                    continue
                moved = True
                if gap_x / need_x <= gap_y / need_y:
                    shift = (gap_x / 2.0 + GRID_EPS) * (1.0 if away_x >= 0.0 else -1.0)
                    xs[first] += shift
                    xs[second] -= shift
                else:
                    shift = (gap_y / 2.0 + GRID_EPS) * (1.0 if away_y >= 0.0 else -1.0)
                    ys[first] += shift
                    ys[second] -= shift
        if not moved:
            break
    return {
        oid: point(
            _clamp(xs[oid], region.min_x, region.max_x),
            _clamp(ys[oid], region.min_y, region.max_y),
        )
        for oid in ids
    }


def solve_graph(request: LayoutRequest) -> dict[str, StagePoint]:
    """Force-directed, but with no randomness at all.

    Nodes start evenly on a ring rotated by ``spec.seed``, and every step after that
    is arithmetic. So the seed changes the arrangement -- an author can ask for a
    different untangling -- without the layout ever changing between two runs.

    The forces work on points, which is why :func:`_separate` runs at the end: two
    nodes an edge pulled together can be a tenth of a unit apart and still overlap
    once they are boxes with labels in them.
    """
    ids = request.object_ids
    if len(ids) <= 1:
        return solve_centered(request)
    region = _region(request)
    ideal = math.sqrt(region.width * region.height / len(ids))
    positions: dict[str, list[float]] = {}
    for index, oid in enumerate(ids):
        angle = math.radians(request.spec.seed % 360 + index * 360.0 / len(ids))
        positions[oid] = [ideal * math.cos(angle), ideal * math.sin(angle)]
    pairs = _graph_pairs(request)
    temperature = ideal
    for _ in range(_GRAPH_STEPS):
        _force_step(positions, pairs, ideal, temperature)
        temperature *= _GRAPH_COOLING
    return _separate(_fit_into(positions, region, _sizes(request)), request, region)


#: How far a timeline marker sits off the axis. Markers alternate sides by that much.
_TIMELINE_OFFSET = 0.22


def solve_timeline(request: LayoutRequest) -> dict[str, StagePoint]:
    """Evenly along an axis, alternating sides.

    Alternating is not decoration: entries on a timeline are usually labelled, and
    labels placed on one side collide as soon as two of them are close together.
    """
    ids = request.object_ids
    if not ids:
        return {}
    region = _region(request)
    center = region.center
    vertical = request.spec.direction == "vertical"
    step = (region.height if vertical else region.width) / len(ids)
    lift = min(_TIMELINE_OFFSET, (region.width if vertical else region.height) / 2.0)
    placed: dict[str, StagePoint] = {}
    for index, oid in enumerate(ids):
        along = (index + 0.5) * step
        side = lift if index % 2 == 0 else -lift
        placed[oid] = (
            point(center.x + side, region.max_y - along)
            if vertical
            else point(region.min_x + along, center.y + side)
        )
    return placed


def solve_map(request: LayoutRequest) -> dict[str, StagePoint]:
    """A placeholder, and labelled as one.

    Real map layout needs a projection and coordinates per marker, and no object in
    the IR carries a latitude yet. Rather than invent a plausible-looking arrangement
    and let it pass for geography, this falls back to a grid so the scene still
    renders, and pass P3 reports ``CMP402`` naming the gap -- see
    :data:`DEGRADED_KINDS`.
    """
    return solve_grid(request)


def slot_regions(spec: LayoutSpec, region: StageBounds) -> dict[str, StageBounds]:
    """Sub-regions for a split layout's slots, divided by weight.

    Public because pass P3 needs it twice: once for the objects a slot's own layout
    arranges, and once to resolve every ``SlotPlacement`` that names a slot directly.
    """
    total = sum(slot.weight for slot in spec.slots)
    if total <= 0.0:
        return {}
    horizontal = spec.direction == "horizontal"
    span = region.width if horizontal else region.height
    regions: dict[str, StageBounds] = {}
    cursor = 0.0
    for slot in spec.slots:
        extent = span * slot.weight / total
        regions[slot.name] = (
            StageBounds(
                min_x=region.min_x + cursor,
                min_y=region.min_y,
                max_x=region.min_x + cursor + extent,
                max_y=region.max_y,
            )
            if horizontal
            else StageBounds(
                min_x=region.min_x,
                min_y=region.max_y - cursor - extent,
                max_x=region.max_x,
                max_y=region.max_y - cursor,
            )
        )
        cursor += extent
    return regions


def sub_request(
    request: LayoutRequest, kind: LayoutKind, region: StageBounds, ids: tuple[str, ...]
) -> LayoutRequest:
    """The same request narrowed to one slot: its kind, its region, its members.

    Public because pass P3 places an object that *names* a slot with it, so a member
    the author assigned and one the split solver dealt into the same panel are arranged
    by identical rules rather than by two implementations of "inside a slot".
    """
    # A slot whose own layout is ``split`` would need slots of its own, which a
    # ``LayoutSlot`` cannot carry. One level is the whole feature; nesting reads as
    # a column.
    inner = LayoutKind.VERTICAL if kind is LayoutKind.SPLIT else kind
    spec = request.spec.model_copy(update={"kind": inner, "region": region, "slots": []})
    return LayoutRequest(
        spec=spec,
        region=region,
        object_ids=ids,
        sizes=request.sizes,
        relationships=request.relationships,
        seed=request.seed,
    )


def _shares(
    ids: tuple[str, ...], slots: Sequence[LayoutSlot]
) -> list[tuple[LayoutSlot, tuple[str, ...]]]:
    """Auto-placed ids dealt round-robin across the slots, respecting capacity.

    Dealt rather than packed. Filling the first panel to its capacity before touching
    the second would put five auto-placed objects in the left half of a two-panel
    split and leave the right half empty, which is not what anyone means by ``split``.
    An object that belongs in a particular panel says so with a ``SlotPlacement``, and
    pass P3 resolves those before the solver sees anything -- so what arrives here is
    the remainder, and spreading it is the least surprising thing to do with it.

    Overflow joins the last slot instead of vanishing. An over-full panel is already
    an ``IR206``; dropping the surplus here would hide it and lose an object.
    """
    if not slots:
        return []
    buckets: list[list[str]] = [[] for _ in slots]
    cursor = 0
    for oid in ids:
        chosen = len(slots) - 1
        for probe in range(len(slots)):
            candidate = (cursor + probe) % len(slots)
            if len(buckets[candidate]) < slots[candidate].capacity:
                chosen = candidate
                break
        buckets[chosen].append(oid)
        cursor = chosen + 1
    return [(slot, tuple(bucket)) for slot, bucket in zip(slots, buckets, strict=True)]


def solve_split(request: LayoutRequest) -> dict[str, StagePoint]:
    """Panels divided by weight, each arranged by its own layout kind."""
    ids = request.object_ids
    if not ids:
        return {}
    region = _region(request)
    regions = slot_regions(request.spec, region)
    placed: dict[str, StagePoint] = {}
    for slot, members in _shares(ids, request.spec.slots):
        if not members or slot.name not in regions:
            continue
        inner = sub_request(request, slot.layout, regions[slot.name], members)
        placed.update(dispatch(inner))
    # A spec with no slots cannot reach validation, but a hand-built request can.
    return placed if placed else solve_vertical(request)


def solve_stack(request: LayoutRequest) -> dict[str, StagePoint]:
    """A deck: same place, offset slightly so the pile below stays visible."""
    region = _region(request)
    center = region.center
    step = request.spec.gap / 2.0
    return {
        oid: point(center.x + index * step, center.y - index * step)
        for index, oid in enumerate(request.object_ids)
    }


def _wrap(extents: Sequence[float], limit: float, gap: float) -> list[list[int]]:
    """Indices grouped into lines that fit within ``limit``, in order.

    An item wider than the whole line still gets its own line rather than being
    skipped -- the off-stage lint is the right place to complain about it.
    """
    groups: list[list[int]] = [[]]
    used = 0.0
    for index, extent in enumerate(extents):
        step = extent if not groups[-1] else gap + extent
        if groups[-1] and used + step > limit:
            groups.append([])
            used = extent
        else:
            used += step
        groups[-1].append(index)
    return groups


def solve_flow(request: LayoutRequest) -> dict[str, StagePoint]:
    """Reading order with wrapping: rows left to right, or columns top to bottom."""
    ids = request.object_ids
    if not ids:
        return {}
    region = _region(request)
    sizes = _sizes(request)
    gap = request.spec.gap
    align = request.spec.align
    vertical = request.spec.direction == "vertical"
    main = [s.height if vertical else s.width for s in sizes]
    limit = region.height if vertical else region.width
    groups = _wrap(main, limit, gap)
    band = (region.width if vertical else region.height) / len(groups)
    placed: dict[str, StagePoint] = {}
    for line, group in enumerate(groups):
        offsets = _distribute([main[i] for i in group], limit, gap, align)
        cross = (
            region.min_x + (line + 0.5) * band if vertical else region.max_y - (line + 0.5) * band
        )
        for offset, index in zip(offsets, group, strict=True):
            lead = offset + main[index] / 2.0
            placed[ids[index]] = (
                point(cross, region.max_y - lead) if vertical else point(region.min_x + lead, cross)
            )
    return placed


def solve_freeform(request: LayoutRequest) -> dict[str, StagePoint]:
    """No imposed structure -- so whatever is left over simply flows.

    ``freeform`` means the author is placing things explicitly. Anything still on
    auto is arranged by the least opinionated total solver there is, which keeps the
    scene renderable without pretending to a composition nobody asked for.
    """
    return solve_flow(request)


# ---------------------------------------------------------------------------
# The table
# ---------------------------------------------------------------------------

#: Every kind, spelled out. A dict comprehension over ``LayoutKind`` would be
#: shorter and would silently give a new kind the wrong solver; this way adding one
#: fails ``test_every_layout_kind_has_a_solver`` immediately.
_PLACERS: Mapping[LayoutKind, Callable[[LayoutRequest], dict[str, StagePoint]]] = {
    LayoutKind.CENTERED: solve_centered,
    LayoutKind.HORIZONTAL: solve_horizontal,
    LayoutKind.VERTICAL: solve_vertical,
    LayoutKind.GRID: solve_grid,
    LayoutKind.RADIAL: solve_radial,
    LayoutKind.TREE: solve_tree,
    LayoutKind.GRAPH: solve_graph,
    LayoutKind.TIMELINE: solve_timeline,
    LayoutKind.MAP: solve_map,
    LayoutKind.SPLIT: solve_split,
    LayoutKind.STACK: solve_stack,
    LayoutKind.FLOW: solve_flow,
    LayoutKind.FREEFORM: solve_freeform,
}

#: Kinds whose built-in solver is an honest placeholder rather than an answer. Pass
#: P3 reports ``CMP402`` when one is used and no skill supplied a real solver, so an
#: expressiveness gap surfaces as a product signal instead of a mediocre frame.
DEGRADED_KINDS = frozenset({LayoutKind.MAP})


def dispatch(request: LayoutRequest) -> dict[str, StagePoint]:
    """Run the built-in solver for a request's own kind.

    Used for the inside of a split layout's slots, by ``solve_split`` and by pass P3
    alike. Skill-supplied solvers override only the scene's top-level kind -- a slot is
    a region, not a second vocabulary.
    """
    return _PLACERS[request.spec.kind](request)


@dataclass(frozen=True, slots=True)
class LayoutRule:
    """A solver function wearing the :class:`~manorem_skills.LayoutSolver` protocol.

    Thirteen classes would each carry a ``kind`` property and a one-line ``solve``;
    one adapter over thirteen functions says the same thing with the arrangement
    logic left in plain view.
    """

    kind: LayoutKind
    place: Callable[[LayoutRequest], dict[str, StagePoint]]

    def solve(self, request: LayoutRequest) -> Mapping[str, StagePoint]:
        return self.place(request)


#: The compiler's own solvers, ready to be overridden by any skill that has a better
#: one for the same kind.
BUILTIN_SOLVERS: Mapping[LayoutKind, LayoutSolver] = {
    kind: LayoutRule(kind=kind, place=place) for kind, place in _PLACERS.items()
}


def solver_for(kind: LayoutKind) -> LayoutSolver:
    """The built-in solver for one kind. Total over :class:`~manorem_ir.LayoutKind`."""
    return BUILTIN_SOLVERS[kind]
