"""P8 Verify: the plan's invariants, checked once before it leaves the compiler.

Every earlier pass trusts the ones before it. This one trusts nothing: it is the
last thing that runs, and a defect it lets through becomes a renderer crash or a
backend-specific golden. So it re-establishes the guarantees the plan's type already
mostly encodes, on the principle that a cheap assertion here is worth more than a
stack trace three stages downstream.

Three things it checks, each mapped to a diagnostic the inspector already knows:

``CMP403`` -- a non-finite number anywhere. A NaN reaches a renderer as a silently
misplaced or invisible mobject; here it is a loud, located error.

``CMP404`` -- an animation whose ``kind`` is not one a renderer must implement. The
plan's discriminated union makes this nearly unreachable, which is the point: if it
*is* reachable, a new animation was added to the union without the renderer's
lookup table growing to match, and that is exactly the drift to catch before ship.

``CMP405`` -- an event that ends after its scene does. P4 sized the scene to hold its
steps; an event past the end means a later pass moved or lengthened something without
re-sizing, and the renderer would either truncate it or overrun the audio.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import get_args

from manorem_compiler.context import CompileContext, SceneWork
from manorem_compiler.plan import PlanAnim, PlanEvent, ScenePlan, Track
from manorem_core import Code

__all__ = ["run"]

#: Animation ``kind`` values a renderer must implement, read from the plan's own
#: union so this allowlist can never fall behind the type it guards.
_ANIM_KINDS: frozenset[str] = frozenset(
    member.model_fields["kind"].default for member in get_args(get_args(PlanAnim)[0])
)


def _non_finite(value: object) -> bool:
    """Whether a dumped plan value hides a NaN or infinity, at any depth."""
    if isinstance(value, bool):
        return False
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, Mapping):
        return any(_non_finite(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_non_finite(item) for item in value)
    return False


def _check_mobjects(ctx: CompileContext, work: SceneWork, plan: ScenePlan) -> None:
    for spec in plan.mobjects:
        if _non_finite(spec.model_dump()):
            ctx.bag.add(
                Code.CMP403_NON_FINITE_VALUE,
                f"mobject {spec.id!r} lowered to a non-finite coordinate or argument",
                pointer=work.ptr("objects"),
                scene_id=work.id,
                object_id=spec.id,
                hint="A position, bound, or numeric argument resolved to NaN or infinity. "
                "This is a solver or mapping defect, not an authoring one.",
            )


def _check_event(ctx: CompileContext, work: SceneWork, track: Track, event: PlanEvent) -> None:
    if event.anim.kind not in _ANIM_KINDS:
        ctx.bag.add(
            Code.CMP404_OP_NOT_IN_ALLOWLIST,
            f"animation {event.anim.kind!r} on {track.target_id!r} is not in the render allowlist",
            pointer=work.ptr("timeline"),
            scene_id=work.id,
            object_id=track.target_id,
            hint="A new PlanAnim was added without the renderer's factory table growing "
            "to match. Add the factory, or drop the animation.",
        )
    if _non_finite(event.anim.model_dump()):
        ctx.bag.add(
            Code.CMP403_NON_FINITE_VALUE,
            f"animation on {track.target_id!r} carries a non-finite value",
            pointer=work.ptr("timeline"),
            scene_id=work.id,
            object_id=track.target_id,
            hint="An animation argument resolved to NaN or infinity.",
        )
    if event.end_frame > work.duration_frames:
        ctx.bag.add(
            Code.CMP405_EVENT_PAST_SCENE_END,
            f"event on {track.target_id!r} ends at frame {event.end_frame}, "
            f"past the scene's {work.duration_frames}",
            pointer=work.ptr("timeline"),
            scene_id=work.id,
            object_id=track.target_id,
            hint="P4 sizes a scene to hold its steps; an event past the end means one was "
            "moved or lengthened afterwards without re-sizing the scene.",
        )


def _check_scene(ctx: CompileContext, work: SceneWork) -> None:
    if not work.has_plan:
        return
    plan = work.plan
    _check_mobjects(ctx, work, plan)
    for track in (*plan.tracks, plan.camera):
        for event in track.events:
            _check_event(ctx, work, track, event)


def run(ctx: CompileContext) -> None:
    for work in ctx.scenes:
        _check_scene(ctx, work)
