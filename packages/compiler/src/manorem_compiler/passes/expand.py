"""P2 Expand: one semantic cue becomes the primitive steps that realize it.

A cue says *what should happen*; a step says *what animates, when, for how long*.
Most cues need no macro at all -- ``show`` on three objects is three ``show`` steps
-- and the ones that do get their rule from :mod:`manorem_compiler.expansions`, or
from a skill that overrides it. This pass is the plumbing around those rules: it
finds the rule, expands groups, puts the result on the frame grid, and refuses to
invent anything a rule asked for but the scene does not have.

**Fractions become frames here.** A rule works in fractions of its cue's window
because a cue's length may come from a narration segment, which P1 resolves. P2
multiplies by the resolved duration and quantizes start and end *independently* from
the cue's own start -- not a start plus a rounded length. Two steps that abut
fractionally then abut exactly on the grid, where rounding each length separately
could overlap them by one frame and force P7 to open a second lane for something the
author wrote as a sequence.

**``focus`` is expanded here, not by a rule.** What a focus dims is "everything else
currently on stage", and a rule sees one cue and its scene, never the running state.
So the dimming is this pass's own work, in a second walk once the whole timeline's
visibility is known; the camera half belongs to P5.

Two ways a cue does not survive, both errors:

``CMP404`` -- the operation has no declaration in this scene's registry. The scene
enabled a set of skills, and their composed vocabulary is what it may use.

``CMP402`` -- the operation is understood but cannot be realized: ``simulate`` with
no skill defining the behaviour, a ``disconnect`` of a connection nothing made, a
``propagate`` from an object nothing links to. Each is a real authoring defect, and
emitting a step for a target that does not exist would turn it into a renderer crash
three stages later.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from itertools import chain

from manorem_compiler.context import CompileContext, SceneWork, ScheduledStep, SymbolTable
from manorem_compiler.expansions import NEEDS_SKILL, expansion_for
from manorem_compiler.params import flag, text
from manorem_core import Code
from manorem_ir import Cue, Easing, OperationDecl, OperationRegistry, SemanticOp, Window
from manorem_skills import ExpandedStep, Expansion, ExpansionRule

__all__ = ["DIM_OPACITY", "run"]

#: Opacity a ``focus`` leaves everything it is not focusing on at. Low enough to
#: recede, high enough that a dimmed object still reads as context rather than
#: disappearing -- a focus that blanked the rest would lose the diagram.
DIM_OPACITY = 0.25


def _targets(cue: Cue, symbols: SymbolTable) -> tuple[str, ...]:
    """A cue's targets with groups expanded: in order, and without repeats.

    Order is the author's, because ``compare`` and ``split`` read meaning into which
    target came first. Repeats are dropped so naming an object *and* a group it
    belongs to animates it once rather than twice in the same lane.
    """
    return tuple(dict.fromkeys(chain.from_iterable(symbols.expand(t) for t in cue.targets)))


def _one_step_each(cue: Cue, symbols: SymbolTable) -> Expansion:
    """The common case, and not a fallback: one step per target, filling the cue."""
    return Expansion(
        steps=tuple(
            ExpandedStep(
                target_id=target_id, op=cue.op, offset=0.0, duration=1.0, params=cue.params
            )
            for target_id in _targets(cue, symbols)
        )
    )


def _opacity_step(target_id: str, opacity: float) -> ExpandedStep:
    return ExpandedStep(
        target_id=target_id,
        op=SemanticOp.FOCUS,
        offset=0.0,
        duration=1.0,
        params={"opacity": opacity},
    )


def _focus_steps(
    cue: Cue, symbols: SymbolTable, visible: Iterable[str]
) -> tuple[ExpandedStep, ...]:
    """Bring the targets to full opacity, and push everything else on stage back.

    The targets get a step even when they are already opaque: a focus after another
    focus has to undo the first one's dimming, and a step that happens to change
    nothing is cheaper than tracking who dimmed what.

    Only authored objects are dimmed. Synthetic ones are transient by construction --
    a particle exists for part of one cue -- so dimming them would either be a no-op
    or fight the expansion that owns them.
    """
    focused = frozenset(_targets(cue, symbols))
    steps = [_opacity_step(target_id, 1.0) for target_id in sorted(focused)]
    if flag(cue.params, "dim_others", default=True):
        steps.extend(_opacity_step(other, DIM_OPACITY) for other in sorted(set(visible) - focused))
    return tuple(steps)


def _clamped(fraction: float) -> float:
    return min(max(fraction, 0.0), 1.0)


def _report_missing_target(
    ctx: CompileContext, work: SceneWork, cue: Cue, ptr: str, wanted: str
) -> None:
    ctx.bag.add(
        Code.CMP402_UNSUPPORTED_INTENT,
        f"{cue.op.value} cannot run: it needs an object that does not exist, {wanted!r}",
        pointer=ptr,
        scene_id=work.id,
        object_id=wanted,
        hint=(
            "A `disconnect` can only remove a connection an earlier `connect` made."
            if cue.op is SemanticOp.DISCONNECT
            else "The expansion asked for a target neither the scene nor an earlier cue provides."
        ),
    )


def _place(
    ctx: CompileContext,
    work: SceneWork,
    cue: Cue,
    ptr: str,
    *,
    window: Window,
    steps: Iterable[ExpandedStep],
    known: frozenset[str],
) -> list[ScheduledStep]:
    """Fractional steps, quantized onto the frame grid, each with a real target."""
    placed: list[ScheduledStep] = []
    sub_frame = 0
    easing = cue.easing if cue.easing is not None else Easing.SMOOTH
    for step in steps:
        if step.target_id not in known:
            _report_missing_target(ctx, work, cue, ptr, step.target_id)
            continue
        start = _clamped(step.offset)
        end = _clamped(start + max(step.duration, 0.0))
        start_frame = ctx.frames(window.start + start * window.duration)
        length = ctx.frames(window.start + end * window.duration) - start_frame
        if length < 1:
            sub_frame += 1
            length = 1
        placed.append(
            ScheduledStep(
                target_id=step.target_id,
                op=step.op,
                cue_id=cue.id,
                start_frame=start_frame,
                duration_frames=length,
                easing=easing,
                params=step.params,
            )
        )
    if sub_frame:
        ctx.bag.warn(
            Code.CMP406_ZERO_DURATION_EVENT,
            f"cue {cue.id!r} has {sub_frame} step(s) shorter than one frame, held at one frame",
            pointer=ptr,
            scene_id=work.id,
            hint="Lengthen the cue, or raise the frame rate, if these should read separately.",
        )
    return placed


def _needs_a_skill(
    ctx: CompileContext,
    work: SceneWork,
    cue: Cue,
    ptr: str,
    overrides: Mapping[SemanticOp, ExpansionRule],
) -> bool:
    """Whether the operation is one only a skill can realize, with none enabled."""
    if cue.op not in NEEDS_SKILL or cue.op in overrides:
        return False
    behaviour = text(cue.params, "behaviour")
    named = f" {behaviour!r}" if behaviour is not None else ""
    ctx.bag.add(
        Code.CMP402_UNSUPPORTED_INTENT,
        f"{cue.op.value}{named} is defined by a skill, and none of this scene's skills defines it",
        pointer=ptr,
        scene_id=work.id,
        hint=f"Enable a skill that supplies a {cue.op.value} rule, or express the idea with "
        "operations the compiler can realize on its own.",
    )
    return True


def _expansion(
    ctx: CompileContext,
    work: SceneWork,
    cue: Cue,
    ptr: str,
    *,
    decl: OperationDecl,
    overrides: Mapping[SemanticOp, ExpansionRule],
) -> Expansion | None:
    """One cue's steps and invented objects, or ``None`` when it was rejected."""
    rule = expansion_for(cue.op, overrides)
    if decl.is_camera and rule is None:
        # Camera work is P5's, from the same cue. `focus` also dims, which needs the
        # running stage state, so its steps are added by the second walk below.
        return Expansion()
    if _needs_a_skill(ctx, work, cue, ptr, overrides):
        return None
    if rule is not None:
        expansion = rule.expand(cue, work.scene)
    else:
        expansion = _one_step_each(cue, work.symbols)
    if not expansion.steps:
        ctx.bag.add(
            Code.CMP402_UNSUPPORTED_INTENT,
            f"{cue.op.value} has nothing to animate in this scene",
            pointer=ptr,
            scene_id=work.id,
            hint="Its targets resolve to no objects, or the scene gives it no route to "
            "follow. The compiler will not invent one.",
        )
        return None
    return expansion


def _stage_ops(registry: OperationRegistry) -> tuple[frozenset[SemanticOp], frozenset[SemanticOp]]:
    """Which operations put something on stage, and which take it off.

    Read from the declarations rather than listed here, so a skill that narrows an
    operation cannot leave this pass believing the old answer.
    """
    introduces: set[SemanticOp] = set()
    removes: set[SemanticOp] = set()
    for op in registry.known_ops():
        decl = registry.get(op)
        if decl is None:
            continue
        if decl.introduces:
            introduces.add(op)
        if decl.removes:
            removes.add(op)
    return frozenset(introduces), frozenset(removes)


def _apply_focus(
    ctx: CompileContext,
    work: SceneWork,
    by_cue: Mapping[str, list[ScheduledStep]],
    pointers: Mapping[str, str],
) -> None:
    """Add each ``focus`` cue's dimming, once the stage state is known.

    A second walk, and it has to be. An object is on stage from frame zero *unless*
    some step introduces it later -- a fact about the whole timeline -- so what a
    focus in the middle of a scene dims cannot be known while the timeline is still
    being expanded. Walking cue order a second time and replaying introductions and
    removals is what makes "everything else currently visible" a real answer rather
    than a guess.
    """
    overrides = work.skills.expansions
    introduces, removes = _stage_ops(work.skills.registry)
    authored = frozenset(work.symbols.objects)
    introduced = {
        step.target_id for steps in by_cue.values() for step in steps if step.op in introduces
    }
    visible = set(authored - introduced)
    dimming: list[ScheduledStep] = []
    for cue_id in work.symbols.cue_order:
        cue = work.scene.cue_by_id(cue_id)
        window = work.timing.window(cue_id)
        if cue is None or window is None:
            continue
        if cue.op is SemanticOp.FOCUS and SemanticOp.FOCUS not in overrides:
            steps = _focus_steps(cue, work.symbols, visible)
            dimming.extend(
                _place(ctx, work, cue, pointers[cue_id], window=window, steps=steps, known=authored)
            )
        for step in by_cue.get(cue_id, ()):
            if step.op in introduces:
                visible.add(step.target_id)
            elif step.op in removes:
                visible.discard(step.target_id)
    work.steps.extend(dimming)


def _expand_scene(ctx: CompileContext, work: SceneWork) -> None:
    scene = work.scene
    registry = work.skills.registry
    overrides = work.skills.expansions
    pointers = {cue.id: work.ptr("timeline", index) for index, cue in enumerate(scene.timeline)}
    known = set(work.symbols.objects)
    by_cue: dict[str, list[ScheduledStep]] = {}
    for cue_id in work.symbols.cue_order:
        cue = scene.cue_by_id(cue_id)
        window = work.timing.window(cue_id)
        if cue is None or window is None:
            # P1 excluded unresolved cues from `cue_order` and reported them; a cue
            # arriving here without a window would be a pipeline bug, not authoring.
            continue
        ptr = pointers[cue_id]
        decl = registry.get(cue.op)
        if decl is None:
            ctx.bag.add(
                Code.CMP404_OP_NOT_IN_ALLOWLIST,
                f"operation {cue.op.value!r} is not offered by this scene's skills",
                pointer=ptr,
                scene_id=work.id,
                hint="Add the skill that declares it to the scene's `skills`.",
            )
            continue
        expansion = _expansion(ctx, work, cue, ptr, decl=decl, overrides=overrides)
        if expansion is None:
            continue
        for obj in expansion.objects:
            # A second `connect` between the same pair reuses the first one's link
            # rather than stacking a duplicate mobject on top of it.
            if obj.id not in known:
                known.add(obj.id)
                work.synthetic.append(obj)
        placed = _place(
            ctx, work, cue, ptr, window=window, steps=expansion.steps, known=frozenset(known)
        )
        by_cue[cue_id] = placed
        work.steps.extend(placed)
    _apply_focus(ctx, work, by_cue, pointers)
    # Sorted so the step list reads as a timeline and two compiles of one scene
    # produce byte-identical goldens regardless of which walk emitted what.
    work.steps.sort(key=lambda step: (step.start_frame, step.target_id, step.op.value, step.cue_id))


def run(ctx: CompileContext) -> None:
    for work in ctx.scenes:
        _expand_scene(ctx, work)
