"""P4 Schedule: decide how long the scene is, and hold every step inside it.

P2 already put each step on the frame grid, because quantizing a step's start and end
against its cue's absolute start is the only way two fractionally-abutting steps abut
exactly. So this pass does not compute times -- it *reconciles* them with the one
number nobody could know until every step existed: the scene's length.

Three jobs, in that order.

**Clamp what starts before zero.** A cue anchored with a negative offset -- ``With(cue,
offset=-0.5)`` on a cue at 0.2 -- resolves to a start before the scene begins. The step
is moved to frame zero and shortened by what it lost, so the moment it was aimed at is
still the moment it ends on. Losing the whole step would silently drop authored content.

**Decide the length.** The longest of: the last step's end, the narration's end, and the
author's ``duration_hint``. Narration counts because a voice-over that outlasts the
visuals would be cut off by the compositor, and §"autofix may extend a scene to fit its
narration" is exactly this rule -- applied here rather than in ``autofix.py`` because
only a scheduled timeline knows the number. The hint is a floor, not a ceiling: a scene
is extended to honour it and never truncated to obey it.

**Report what still lands outside.** After the length is known, a step past the end is a
``CMP405``, and it is an error rather than a clamp. A step that runs past its scene has
had its time computed from something the length calculation could not see -- and quietly
trimming it would produce a video where an animation is cut off mid-way with nothing
saying why. In practice the length is derived *from* the steps, so this fires for camera
keys P5 adds later and for anything a repair introduced, which is precisely when it
should be loud.
"""

from __future__ import annotations

from manorem_compiler.context import CompileContext, SceneWork, ScheduledStep
from manorem_core import Code

__all__ = ["run"]

#: Shortest scene the pass will produce, in frames. A scene of zero frames is not a
#: scene, and one frame is what an empty timeline honestly is.
_MIN_FRAMES = 1


def _clamped(work: SceneWork) -> int:
    """Pull any step starting before frame zero forward, keeping its end fixed.

    Returns how many were moved, so the caller reports one diagnostic for the scene
    rather than one per step -- a single mis-anchored cue can produce a dozen steps.
    """
    moved = 0
    for index, step in enumerate(work.steps):
        if step.start_frame >= 0:
            continue
        moved += 1
        work.steps[index] = ScheduledStep(
            target_id=step.target_id,
            op=step.op,
            cue_id=step.cue_id,
            start_frame=0,
            duration_frames=max(step.end_frame, _MIN_FRAMES),
            easing=step.easing,
            params=step.params,
        )
    return moved


def _length(ctx: CompileContext, work: SceneWork) -> int:
    """The scene's length in frames: whichever of its three claims is longest."""
    steps = max((step.end_frame for step in work.steps), default=0)
    narration = ctx.frames(max((w.end for w in work.timing.narration.values()), default=0.0))
    hint = ctx.frames(work.scene.duration_hint) if work.scene.duration_hint is not None else 0
    return max(steps, narration, hint, _MIN_FRAMES)


def _report_overrun(ctx: CompileContext, work: SceneWork) -> None:
    """Name every step finishing after the scene does."""
    for step in work.steps:
        if step.end_frame <= work.duration_frames:
            continue
        ctx.bag.add(
            Code.CMP405_EVENT_PAST_SCENE_END,
            f"{step.op.value} on {step.target_id!r} ends at frame {step.end_frame}, "
            f"after the scene's last frame ({work.duration_frames})",
            pointer=work.ptr("timeline"),
            scene_id=work.id,
            object_id=step.target_id,
            hint="Its cue is anchored past the end of the scene, or to a narration "
            "segment longer than the scene allows.",
        )


def _schedule_scene(ctx: CompileContext, work: SceneWork) -> None:
    moved = _clamped(work)
    if moved:
        ctx.bag.warn(
            Code.CMP407_UNRESOLVED_TIME,
            f"{moved} step(s) resolved to a time before the scene starts, held at frame 0",
            pointer=work.ptr("timeline"),
            scene_id=work.id,
            hint="A negative offset on a cue near the start of the scene: the steps still "
            "end when they were meant to, but they begin earlier than written.",
        )
        work.steps.sort(key=lambda s: (s.start_frame, s.target_id, s.op.value, s.cue_id))
    work.duration_frames = _length(ctx, work)
    _report_overrun(ctx, work)


def run(ctx: CompileContext) -> None:
    for work in ctx.scenes:
        _schedule_scene(ctx, work)
