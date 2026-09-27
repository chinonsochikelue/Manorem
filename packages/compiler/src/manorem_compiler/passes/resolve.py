"""P1 Resolve: build the symbol table, and resolve symbolic time to seconds.

Neither half is reimplemented here. Timing resolution lives in
:func:`~manorem_ir.resolve_timing` because the validator and this pass must agree
about when a cue starts -- two implementations would eventually report a defect the
other could not see. What P1 adds is the compiler's own reading of the result:
*which cues can be lowered at all*.

A cue whose start could not be resolved is excluded from
:attr:`~manorem_compiler.context.SymbolTable.cue_order` and reported, rather than
placed at zero. Inventing a time would produce a video where a cue fires at a moment
nobody asked for, and the resulting frame looks plausible enough that no one would
check. The same goes for a cue in a timing cycle: the validator has already raised
``IR204``, and ``CMP407`` here is what stops it reaching the frame grid.
"""

from __future__ import annotations

from manorem_compiler.context import CompileContext, SceneWork, SymbolTable
from manorem_core import Code
from manorem_ir import Scene, resolve_timing

__all__ = ["run"]


def _cue_order(scene: Scene, excluded: frozenset[str]) -> tuple[str, ...]:
    """Cue ids in dependency order, excluding the ones that cannot be placed.

    A cue is scheduled against at most one other cue, so "depth" -- the length of the
    chain behind it -- is enough to order them: a child's depth always exceeds its
    parent's, and declaration order breaks ties so two independent cues keep the
    sequence their author wrote.

    Computed by iterating to a fixpoint rather than by recursion, bounded by the cue
    count, so a cycle that slipped past detection terminates instead of overflowing
    the stack.
    """
    ids = [cue.id for cue in scene.timeline if cue.id not in excluded]
    index = {cue_id: n for n, cue_id in enumerate(ids)}
    parents = {
        cue.id: cue.depends_on_cue
        for cue in scene.timeline
        if cue.id in index and cue.depends_on_cue in index
    }
    depth = dict.fromkeys(ids, 0)
    for _ in range(len(ids)):
        progressed = False
        for cue_id, parent in parents.items():
            if depth[cue_id] <= depth[parent]:
                depth[cue_id] = depth[parent] + 1
                progressed = True
        if not progressed:
            break
    return tuple(sorted(ids, key=lambda cue_id: (depth[cue_id], index[cue_id])))


def _report_unplaceable(ctx: CompileContext, work: SceneWork) -> frozenset[str]:
    """Cues whose time is unknown, reported and named for exclusion."""
    timing = work.timing
    broken: set[str] = set()
    for cycle in timing.cycles:
        broken.update(cycle)
        chain = " -> ".join((*cycle, cycle[0]))
        ctx.bag.add(
            Code.CMP407_UNRESOLVED_TIME,
            f"cues form a timing cycle and cannot be placed: {chain}",
            pointer=work.ptr("timeline"),
            scene_id=work.id,
            hint="Anchor one of these cues to an absolute time or a narration segment.",
        )
    for cue_id in sorted(timing.unresolved - broken):
        cue = work.scene.cue_by_id(cue_id)
        ctx.bag.add(
            Code.CMP407_UNRESOLVED_TIME,
            f"cue {cue_id!r} has no resolvable start time",
            pointer=work.ptr("timeline"),
            scene_id=work.id,
            object_id=cue_id,
            hint=(
                "Its anchor refers to something that does not exist; the compiler will "
                "not place it at zero instead."
            )
            if cue is not None
            else None,
        )
        broken.add(cue_id)
    return frozenset(broken)


def run(ctx: CompileContext) -> None:
    for work in ctx.scenes:
        scene = work.scene
        work.timing_ = resolve_timing(scene, registry=work.skills.registry, wpm=ctx.wpm)
        excluded = _report_unplaceable(ctx, work)
        work.symbols_ = SymbolTable(
            objects={obj.id: obj for obj in scene.objects},
            groups={group.id: tuple(group.members) for group in scene.groups},
            cue_order=_cue_order(scene, excluded),
        )
