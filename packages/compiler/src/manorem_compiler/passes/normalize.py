"""P0 Normalize: make implicit authoring explicit, and change nothing else.

This pass exists so no later pass has to write ``x if x is not None else default``.
Everything it does is a defaulting rule that was always going to be applied; doing
it once, here, means the value a pass reads is the value the plan will carry.

What it deliberately does **not** do is the reason it is short. Colours are *role
names* (``ObjectStyle.color``, ``Scene.background``) resolved against the project's
style tokens, and they stay role names all the way to P7 -- rewriting them to hex
here would make a restyle a no-op for anything already normalized, and would make
``color_for``'s fallback fire twice with different meanings. Cue durations already
resolve through the operation registry in :func:`~manorem_ir.resolve_timing`, which
P1 calls, so defaulting them here would only give two answers a chance to disagree.
Ids are validated as slugs at parse time, so "canonicalize ids" has nothing left to
canonicalize -- what it meant is the ordering rule below.

None of the three rules can change the set of object, cue, relationship or narration
ids, which is what keeps the autofix invariant checkable over a compiled corpus.
"""

from __future__ import annotations

from manorem_compiler.context import CompileContext
from manorem_ir import AutoPlacement, Cue, Easing, Scene, SceneObject

__all__ = ["run"]

#: Ceiling on a synthesized placement order. ``AutoPlacement.order`` is capped at 999
#: and a scene holds at most 200 objects, so this only ever guards against a future
#: limit change rather than clamping a real scene.
_MAX_ORDER = 999


def _ordered(objects: list[SceneObject]) -> list[SceneObject] | None:
    """Give every auto-placed object an explicit order, or ``None`` if all have one.

    An auto-placed object with no order falls back to declaration order in the
    solvers, which is the right answer -- writing it down is what makes it *visible*,
    so a reader of the compiled scene can see the sequence the layout will use rather
    than having to know that list position is load-bearing.
    """
    updated = list(objects)
    changed = False
    for index, obj in enumerate(objects):
        placement = obj.placement
        if isinstance(placement, AutoPlacement) and placement.order is None:
            order = min(index, _MAX_ORDER)
            updated[index] = obj.model_copy(update={"placement": AutoPlacement(order=order)})
            changed = True
    return updated if changed else None


def _eased(timeline: list[Cue]) -> list[Cue] | None:
    """Fill in the default easing, so a step's easing is never ``None``."""
    updated = list(timeline)
    changed = False
    for index, cue in enumerate(timeline):
        if cue.easing is None:
            updated[index] = cue.model_copy(update={"easing": Easing.SMOOTH})
            changed = True
    return updated if changed else None


def _normalize(scene: Scene, skill_ids: tuple[str, ...]) -> Scene:
    """One scene's normalized copy, or the scene itself when nothing changed."""
    update: dict[str, object] = {}
    objects = _ordered(scene.objects)
    if objects is not None:
        update["objects"] = objects
    timeline = _eased(scene.timeline)
    if timeline is not None:
        update["timeline"] = timeline
    # Skills are reordered, not filtered: the base pack first, then the rest in the
    # order the registry resolved them, then anything it did not recognize. Dropping
    # an unknown id would erase the evidence for the IR210 the validator just raised.
    canonical = list(skill_ids)
    if canonical != scene.skills:
        update["skills"] = canonical
    return scene.model_copy(update=update) if update else scene


def run(ctx: CompileContext) -> None:
    for work in ctx.scenes:
        known = work.skills.ids
        unknown = tuple(s for s in work.skills.unknown if s not in known)
        work.scene = _normalize(work.scene, known + unknown)
