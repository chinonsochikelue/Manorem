"""P7, second half: scheduled steps become tracks, and a scene becomes a plan.

:mod:`~manorem_compiler.lower.mobjects` decided *what is on stage*; this module
decides *what happens on the timeline*. It pairs each
:class:`~manorem_compiler.context.ScheduledStep` with the drawable it acts on,
asks :func:`~manorem_compiler.lower.anims.anim_for` for the concrete animation, and
lays the result out in lanes.

**Lanes, not one track per target.** Two animations genuinely meant to run at once
on one mobject -- a dot that moves *while* it changes colour -- cannot share a
:class:`~manorem_compiler.plan.Track`, because a lane is played as
``Succession(Wait(gap), anim, ...)`` and a succession is sequential by construction.
So overlapping events on one target are split across lanes by greedy interval
partitioning: each event joins the first lane whose last event has already finished,
or opens a new one. That is exactly what ``self.play(a, b)`` does by hand, and it is
why :attr:`~manorem_compiler.plan.Track.target_id` is not unique across a scene.

**The camera is a track like any other.** P5 left its moves in stage units on
:attr:`~manorem_compiler.context.SceneWork.camera_keys`; here they map through the
same :class:`~manorem_compiler.context.FrameMapping` as everything else and land on
the reserved :data:`~manorem_compiler.plan.CAMERA_TRACK_ID` lane.

**Audio is carried, not mixed.** Narration windows P1 resolved become
:class:`~manorem_compiler.plan.AudioCue` rows -- present even in M1's silent render,
because the SRT and WebVTT are written from them.
"""

from __future__ import annotations

from manorem_compiler.context import CompileContext, SceneWork
from manorem_compiler.lower.anims import anim_for
from manorem_compiler.lower.mobjects import lower_mobjects
from manorem_compiler.plan import (
    CAMERA_TRACK_ID,
    AudioCue,
    CameraFrameAnim,
    MobjectSpec,
    PlanEvent,
    ScenePlan,
    Track,
)

__all__ = ["build_scene_plan"]


def _lanes(events: list[PlanEvent]) -> list[list[PlanEvent]]:
    """Partition one target's events into non-overlapping lanes.

    First-fit by start frame: an event joins the earliest lane already free by the
    time it begins, so two events that abut exactly share a lane and two that overlap
    do not. Deterministic because the sort key is total -- start, then length -- so
    two compiles of one scene lane the same way.
    """
    lanes: list[list[PlanEvent]] = []
    for event in sorted(events, key=lambda e: (e.start_frame, e.duration_frames)):
        for lane in lanes:
            if lane[-1].end_frame <= event.start_frame:
                lane.append(event)
                break
        else:
            lanes.append([event])
    return lanes


def _object_tracks(
    ctx: CompileContext,
    work: SceneWork,
    specs_by_id: dict[str, MobjectSpec],
) -> list[Track]:
    """One lane per concurrent animation, grouped and ordered by target."""
    mapping = work.frame
    events: dict[str, list[PlanEvent]] = {}
    for step in work.steps:
        spec = specs_by_id.get(step.target_id)
        if spec is None:
            # P2 and P3 already rejected steps whose target has no object; a step
            # arriving here without a spec would be a pipeline bug, not authoring.
            continue
        anim = anim_for(ctx, work, step, spec, mapping)
        if anim is None:
            # anim_for reported CMP402 for an intent this plan cannot express.
            continue
        events.setdefault(step.target_id, []).append(
            PlanEvent(
                start_frame=step.start_frame,
                duration_frames=step.duration_frames,
                anim=anim,
                easing=step.easing,
                cue_id=step.cue_id,
            )
        )
    tracks: list[Track] = []
    for target_id in sorted(events):
        for lane in _lanes(events[target_id]):
            tracks.append(Track(target_id=target_id, events=tuple(lane)))
    return tracks


def _camera_track(work: SceneWork) -> Track:
    """P5's stage-unit camera moves, mapped to world units on the camera lane."""
    mapping = work.frame
    return Track(
        target_id=CAMERA_TRACK_ID,
        events=tuple(
            PlanEvent(
                start_frame=key.start_frame,
                duration_frames=key.duration_frames,
                anim=CameraFrameAnim(
                    center=mapping.point(key.center), width=mapping.length(key.width)
                ),
                easing=key.easing,
                cue_id=key.cue_id,
            )
            for key in sorted(work.camera_keys, key=lambda k: k.start_frame)
        ),
    )


def _audio_cues(ctx: CompileContext, work: SceneWork) -> tuple[AudioCue, ...]:
    """Resolved narration windows as frame-grid cues for the compositor."""
    cues: list[AudioCue] = []
    for segment in work.scene.narration:
        window = work.timing.narration.get(segment.id)
        if window is None:
            continue
        start = ctx.frames(window.start)
        end = ctx.frames(window.end)
        cues.append(
            AudioCue(
                segment_id=segment.id,
                start_frame=start,
                duration_frames=max(end - start, 0),
                role=segment.role.value,
                text=segment.text,
            )
        )
    return tuple(cues)


def build_scene_plan(ctx: CompileContext, work: SceneWork) -> ScenePlan:
    """Assemble one finished :class:`~manorem_compiler.plan.ScenePlan`.

    Every symbolic decision is already made by the time this runs: positions are
    solved (P3), times are on the grid (P4), the camera is placed (P5), and the aspect
    mapping is fixed (P6). What remains is transcription.
    """
    specs = lower_mobjects(ctx, work)
    specs_by_id = {spec.id: spec for spec in specs}
    role = work.scene.background
    background = ctx.style.color_for(role) if role is not None else ctx.style.background
    return ScenePlan(
        id=work.id,
        duration_frames=max(work.duration_frames, 1),
        background=background,
        mobjects=specs,
        tracks=tuple(_object_tracks(ctx, work, specs_by_id)),
        camera=_camera_track(work),
        audio_cues=_audio_cues(ctx, work),
        transition_out_frames=ctx.frames(work.scene.transition_out.duration),
    )
