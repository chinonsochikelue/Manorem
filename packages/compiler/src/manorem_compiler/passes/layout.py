"""P3 Layout: how big everything is, and where it goes.

The two halves of :mod:`manorem_compiler.layout` meet here. Sizes are *estimated*
from props, never measured, so the pass stays a pure function and a committed plan
stays reproducible; positions come from a solver that sees only stage space, which is
what lets one authored scene render to three aspect ratios.

**Explicit placement is resolved around the solver, not by it.** A solver is handed
the auto-placed objects and nothing else, in four phases:

1. ``stage`` -- an authored coordinate, taken as written.
2. ``slot`` -- the object named a panel, so it is arranged *inside* that panel by the
   panel's own layout kind, through the same helpers ``solve_split`` uses.
3. ``auto`` -- everything left, handed to the scene's solver in placement order.
4. ``anchor`` -- resolved against the three above, iterating so a chain of anchors
   settles. A cycle is reported rather than guessed at.

That ordering is what makes "put the hub in the middle and let the rest ring it" work
with no special support in any solver: the hub is phase 1, the ring is phase 3.

**Positions are total, even when something is wrong.** An unresolvable anchor or an
unknown slot is a ``CMP401``, and the object still gets a point -- the compile will
halt on the error, but the geometry lints and P8 run over a complete map rather than
having to defend against a missing key. Synthetic objects are measured here too, since
P7 owes every mobject a ``bounds``, but they are never *positioned*: where a travelling
packet sits is a property of the step that moves it.

Once positions exist, :func:`~manorem_ir.check_geometry` runs. It is the T3 half that
could not run before this pass -- overlap and off-stage need coordinates -- and it
lives in the IR package because it shares the same policy object as the rest of T3.
It is geometric, not perceptual: it proves nothing is outside the safe area, not that
anything is readable.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from manorem_compiler.context import CompileContext, SceneWork
from manorem_compiler.layout import (
    BUILTIN_SOLVERS,
    DEGRADED_KINDS,
    content_region,
    dispatch,
    estimate_props_size,
    estimate_sizes,
    point,
    slot_regions,
    sub_request,
)
from manorem_core import Code
from manorem_ir import (
    AnchorPlacement,
    AutoPlacement,
    LayoutSpec,
    SceneObject,
    Side,
    SlotPlacement,
    StageBounds,
    StagePlacement,
    StagePoint,
    StageSize,
    StyleTokens,
    check_geometry,
)
from manorem_skills import LayoutRequest, LayoutSolver

__all__ = ["run"]

#: Unit vector per side, in stage space. ``center`` is not a mistake: an anchored
#: object with ``side="center"`` sits on its reference, which is how a label is put
#: *on* a box rather than beside it.
_SIDE_STEP: Mapping[Side, tuple[float, float]] = {
    Side.LEFT: (-1.0, 0.0),
    Side.RIGHT: (1.0, 0.0),
    Side.ABOVE: (0.0, 1.0),
    Side.BELOW: (0.0, -1.0),
    Side.CENTER: (0.0, 0.0),
}

#: Extent assumed for an id with no estimate. Matches the solvers' own fallback, so an
#: anchor gap and a layout gap read the same object as the same size.
_FALLBACK = StageSize(width=0.2, height=0.1)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True, slots=True)
class _Placements:
    """One scene's objects, grouped by how their position is arrived at.

    Built in one walk so each phase reads a tuple rather than re-filtering the scene,
    and so an object whose placement could not be honoured is moved into ``auto``
    at the point the problem is found -- there is no later chance to keep the map total.
    """

    fixed: tuple[tuple[str, StagePoint], ...] = ()
    slotted: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    anchored: tuple[tuple[str, AnchorPlacement], ...] = ()
    auto: tuple[str, ...] = ()


def _order_key(obj: SceneObject, index: int) -> tuple[int, int]:
    """Placement order for an auto-placed object, falling back to declaration order.

    P0 writes an explicit order onto every auto placement, so the fallback only fires
    for a scene built in code. Declaration index breaks ties, which keeps two objects
    sharing an order in the sequence their author wrote.
    """
    placement = obj.placement
    if isinstance(placement, AutoPlacement) and placement.order is not None:
        return (placement.order, index)
    return (index, index)


def _report_unknown_slots(ctx: CompileContext, work: SceneWork, missing: Mapping[str, int]) -> None:
    """One diagnostic per undefined slot, not per object that named it."""
    for name in sorted(missing):
        ctx.bag.add(
            Code.CMP401_LAYOUT_UNSOLVABLE,
            f"{missing[name]} object(s) are placed in slot {name!r}, "
            f"which this layout does not define",
            pointer=work.ptr("layout"),
            scene_id=work.id,
            hint="Add the slot to the layout's `slots`, or place the objects automatically.",
        )


def _group(ctx: CompileContext, work: SceneWork, regions: Mapping[str, StageBounds]) -> _Placements:
    """Sort every authored object into the phase that will position it."""
    fixed: list[tuple[str, StagePoint]] = []
    slotted: dict[str, list[str]] = {}
    anchored: list[tuple[str, AnchorPlacement]] = []
    auto: list[tuple[tuple[int, int], str]] = []
    missing: dict[str, int] = {}
    for index, obj in enumerate(work.scene.objects):
        placement = obj.placement
        match placement:
            case StagePlacement():
                fixed.append((obj.id, point(placement.point.x, placement.point.y)))
            case SlotPlacement() if placement.slot in regions:
                slotted.setdefault(placement.slot, []).append(obj.id)
            case AnchorPlacement():
                anchored.append((obj.id, placement))
            case _:
                # An object naming an undefined slot lands here: it is still laid out,
                # and the `CMP401` says why it is not where its author asked.
                if isinstance(placement, SlotPlacement):
                    missing[placement.slot] = missing.get(placement.slot, 0) + 1
                auto.append((_order_key(obj, index), obj.id))
    _report_unknown_slots(ctx, work, missing)
    return _Placements(
        fixed=tuple(fixed),
        slotted={name: tuple(ids) for name, ids in slotted.items()},
        anchored=tuple(anchored),
        auto=tuple(object_id for _, object_id in sorted(auto)),
    )


def _request(
    spec: LayoutSpec,
    region: StageBounds,
    work: SceneWork,
    ids: tuple[str, ...],
) -> LayoutRequest:
    """A solver request for part of one scene, carrying the whole scene's context.

    ``sizes`` and ``relationships`` are not narrowed to ``ids``: a tree solver reads
    edges to decide structure, and an edge to an object placed in another phase still
    tells it something. Handing over the full maps costs nothing and keeps a solver
    from having to ask why a relationship it can see names an id it cannot.
    """
    return LayoutRequest(
        spec=spec,
        region=region,
        object_ids=ids,
        sizes=work.sizes,
        relationships=tuple(work.scene.relationships),
        seed=spec.seed,
    )


def _solver(work: SceneWork) -> LayoutSolver:
    """The scene's solver: a skill's if one claims the kind, otherwise the built-in."""
    kind = work.scene.layout.kind
    supplied = work.skills.layouts.get(kind)
    return supplied if supplied is not None else BUILTIN_SOLVERS[kind]


def _report_degraded(ctx: CompileContext, work: SceneWork) -> None:
    """Say so when the only solver for a kind is a labelled placeholder.

    A ``map`` layout with no geography skill enabled arranges its markers in a grid.
    That renders, and it is not geography -- so the gap is reported as an unsupported
    intent rather than passed off as an answer. See
    :data:`~manorem_compiler.layout.DEGRADED_KINDS`.
    """
    kind = work.scene.layout.kind
    if kind not in DEGRADED_KINDS or kind in work.skills.layouts:
        return
    ctx.bag.add(
        Code.CMP402_UNSUPPORTED_INTENT,
        f"the {kind.value!r} layout has no real solver, so its objects are arranged "
        f"as a grid instead",
        pointer=work.ptr("layout"),
        scene_id=work.id,
        hint=f"Enable a skill supplying a {kind.value!r} layout solver. The scene still "
        "renders, but the arrangement carries no meaning.",
    )


def _anchor_point(
    anchor: AnchorPlacement,
    at: StagePoint,
    own: StageSize,
    reference: StageSize,
) -> StagePoint:
    """Where an anchored object sits: beside its reference, edge to edge plus the gap.

    Measured between *edges*, so ``gap`` means the same thing whatever the two objects'
    sizes are -- a label 0.1 below a big box and 0.1 below a small one look equally far
    away, which is what an author writing a gap expects.
    """
    step_x, step_y = _SIDE_STEP[anchor.side]
    reach_x = (reference.width + own.width) / 2.0 + anchor.gap
    reach_y = (reference.height + own.height) / 2.0 + anchor.gap
    return point(at.x + step_x * reach_x, at.y + step_y * reach_y)


def _report_unresolved_anchor(
    ctx: CompileContext, work: SceneWork, object_id: str, ref: str
) -> None:
    known = ref in work.symbols.objects
    ctx.bag.add(
        Code.CMP401_LAYOUT_UNSOLVABLE,
        f"{object_id!r} is anchored to {ref!r}, whose own position cannot be resolved",
        pointer=work.ptr("objects"),
        scene_id=work.id,
        object_id=object_id,
        hint=(
            "The anchors form a cycle: two objects cannot each sit beside the other."
            if known
            else "Its anchor names an object this scene does not define."
        ),
    )


def _resolve_anchors(
    ctx: CompileContext,
    work: SceneWork,
    placed: dict[str, StagePoint],
    anchored: Sequence[tuple[str, AnchorPlacement]],
    region: StageBounds,
) -> None:
    """Place anchored objects against already-placed ones, until nothing moves.

    A fixpoint rather than a topological sort, because an anchor chain is short and
    bounded by the object count either way -- and iterating means a cycle simply stops
    making progress instead of needing its own detector. Whatever is left when progress
    stops is the cycle, and every member of it is reported.

    Each resolved centre is clamped into the content region. An anchored label pushed
    off the edge by a large reference would otherwise leave the frame with nothing but
    an ``IR305`` to show for it, and the clamp keeps the relationship readable.
    """
    pending = dict(anchored)
    while pending:
        progressed = False
        for object_id in sorted(pending):
            anchor = pending[object_id]
            at = placed.get(anchor.ref)
            if at is None:
                continue
            resolved = _anchor_point(
                anchor,
                at,
                work.sizes.get(object_id, _FALLBACK),
                work.sizes.get(anchor.ref, _FALLBACK),
            )
            placed[object_id] = point(
                _clamp(resolved.x, region.min_x, region.max_x),
                _clamp(resolved.y, region.min_y, region.max_y),
            )
            del pending[object_id]
            progressed = True
        if not progressed:
            break
    center = region.center
    for object_id in sorted(pending):
        _report_unresolved_anchor(ctx, work, object_id, pending[object_id].ref)
        # Still given a point: the compile halts on the error above, and the geometry
        # lints and P8 read a complete map rather than defending against a gap.
        placed[object_id] = point(center.x, center.y)


def _measure(work: SceneWork, style: StyleTokens) -> None:
    """Extents for every mobject P7 will emit, authored and synthetic alike.

    Synthetic objects are measured with the same rules as authored ones -- a packet
    invented by a ``flow`` must not measure differently from a dot someone wrote down,
    or the overlap lint would read the two inconsistently.
    """
    work.sizes.update(estimate_sizes(work.scene.objects, style))
    for obj in work.synthetic:
        work.sizes[obj.id] = estimate_props_size(obj.props, style)


def _layout_scene(ctx: CompileContext, work: SceneWork) -> None:
    _measure(work, ctx.style)
    _report_degraded(ctx, work)
    spec = work.scene.layout
    region = content_region(spec, spec.region)
    regions = slot_regions(spec, region)
    groups = _group(ctx, work, regions)
    placed: dict[str, StagePoint] = dict(groups.fixed)
    for name, members in sorted(groups.slotted.items()):
        slot = spec.slot(name)
        if slot is None:
            continue
        outer = _request(spec, region, work, members)
        placed.update(dispatch(sub_request(outer, slot.layout, regions[name], members)))
    if groups.auto:
        placed.update(_solver(work).solve(_request(spec, spec.region, work, groups.auto)))
    _resolve_anchors(ctx, work, placed, groups.anchored, region)
    work.positions.update(placed)
    work.bounds.update(
        {
            object_id: StageBounds.around(at, work.sizes.get(object_id, _FALLBACK))
            for object_id, at in placed.items()
        }
    )


def run(ctx: CompileContext) -> None:
    for work in ctx.scenes:
        _layout_scene(ctx, work)
        # The T3 geometry lints, which could not run until now. Built from this scene's
        # own skills, because `strict_lints` and the overlap threshold are policy the
        # caller set -- warnings by default, errors when a final cut is being prepared.
        ctx.bag.extend(check_geometry(work.id, work.bounds, work.validation(ctx), work.pointer))
