"""The scene manifest: what the plan says was on stage, frame by frame.

Computed from the :class:`~manorem_compiler.RenderPlan` alone -- never from
pixels -- because everything a geometric QA check needs is already in the plan:
resolved world bounds (P6 wrote them down), a camera track, and the events that
bring a mobject on and take it off. So the manifest is pure, deterministic, and
identical across backends: the stub and Manim produce the same manifest for the
same plan, and it can be built without rendering anything at all.

Two approximations are deliberate for M1. A mobject's bounds are its *resolved*
box, not its box mid-``move_to`` -- the plan does not re-solve geometry per frame,
and a QA stage that needs swept bounds can integrate the track itself. And
visibility is tracked by which events introduce or retire a mobject, not by
opacity: a ``set_opacity`` to zero still reads as present, because it is.
"""

from __future__ import annotations

from manorem_compiler import Point3, RenderPlan, ScenePlan, Track
from manorem_ir import Aspect
from manorem_renderer.frames import sample_frames
from manorem_renderer.results import (
    FrameManifest,
    MobjectSnapshot,
    RenderManifest,
    ScenePlanManifest,
)

__all__ = ["MANIM_FRAME_HEIGHT", "build_manifest"]

#: Manim's world frame is eight units tall at every aspect; only the width
#: changes. The default camera therefore spans ``8 * ratio`` world units, which is
#: exactly what pass P6 assumes when it maps stage space to world units.
MANIM_FRAME_HEIGHT = 8.0

#: Animation kinds that bring a mobject onto the stage.
_INTRODUCE: frozenset[str] = frozenset({"create", "write", "draw", "fade_in", "grow"})
#: Animation kinds that take a mobject off it.
_REMOVE: frozenset[str] = frozenset({"fade_out", "uncreate", "shrink"})


def _default_camera_width(aspect: Aspect) -> float:
    return MANIM_FRAME_HEIGHT * aspect.ratio


def _visibility_marks(scene: ScenePlan) -> dict[str, list[tuple[int, bool]]]:
    """Per-mobject on/off transitions, as ``(frame, becomes_visible)`` pairs.

    An introduce marks the target visible at its start; a remove marks it hidden
    at its end. A ``replacement_transform`` both introduces its ``into`` target
    and retires the source, which is the one case where one event touches two ids.
    """
    marks: dict[str, list[tuple[int, bool]]] = {}
    for track in scene.tracks:
        for event in track.events:
            anim = event.anim
            if anim.kind in _INTRODUCE:
                marks.setdefault(track.target_id, []).append((event.start_frame, True))
            elif anim.kind in _REMOVE:
                marks.setdefault(track.target_id, []).append((event.end_frame, False))
            elif anim.kind == "replacement_transform":
                marks.setdefault(track.target_id, []).append((event.end_frame, False))
                marks.setdefault(anim.into, []).append((event.start_frame, True))
            elif anim.kind == "transform":
                marks.setdefault(anim.into, []).append((event.start_frame, True))
    return marks


def _visible_at(frame: int, *, initial: bool, transitions: list[tuple[int, bool]]) -> bool:
    """Whether a mobject is up at ``frame``, given its initial state and marks.

    The state is the last transition at or before ``frame``; a removal and an
    introduction on the same frame resolves to hidden, since an object cannot both
    appear and vanish at one instant and vanishing is the safer report.
    """
    state = initial
    for at, becomes in sorted(transitions, key=lambda m: (m[0], m[1])):
        if at <= frame:
            state = becomes
        else:
            break
    return state


def _camera_at(frame: int, camera: Track, aspect: Aspect) -> tuple[Point3, float]:
    """The camera centre and width at ``frame``.

    Step-held from the most recent camera move whose start is at or before the
    frame: a move is treated as committed from the instant it begins, which is
    coarse but monotonic and matches how a snapshot reads an in-progress pan.
    """
    center: Point3 = (0.0, 0.0, 0.0)
    width = _default_camera_width(aspect)
    for event in camera.events:
        if event.start_frame <= frame and event.anim.kind == "camera_frame":
            center = event.anim.center
            width = event.anim.width
    return center, width


def _frame_manifest(scene: ScenePlan, frame: int, fps: int, aspect: Aspect) -> FrameManifest:
    marks = _visibility_marks(scene)
    center, width = _camera_at(frame, scene.camera, aspect)
    snapshots = tuple(
        MobjectSnapshot(
            id=mob.id,
            primitive=mob.primitive,
            bounds=mob.bounds,
            z_index=mob.z_index,
            visible=_visible_at(
                frame, initial=mob.initial_visible, transitions=marks.get(mob.id, [])
            ),
        )
        for mob in scene.mobjects
    )
    return FrameManifest(
        frame=frame,
        time_s=frame / fps,
        camera_center=center,
        camera_width=width,
        mobjects=snapshots,
    )


def _scene_manifest(
    scene: ScenePlan, fps: int, aspect: Aspect, sample_rate_hz: float
) -> ScenePlanManifest:
    frames = sample_frames(scene.duration_frames, fps, sample_rate_hz)
    return ScenePlanManifest(
        scene_id=scene.id,
        duration_frames=scene.duration_frames,
        frames=tuple(_frame_manifest(scene, f, fps, aspect) for f in frames),
    )


def build_manifest(plan: RenderPlan, *, sample_rate_hz: float = 1.0) -> RenderManifest:
    """The whole plan's sampled geometry, built without rendering a pixel.

    Emitted by every backend on every successful render. Nothing in M1 reads it;
    it exists so the Visual QA stage is a wiring change later rather than a
    renderer retrofit.
    """
    aspect = plan.format.aspect
    fps = plan.format.fps
    return RenderManifest(
        plan_version=plan.plan_version,
        project_id=plan.project_id,
        fps=fps,
        scenes=tuple(_scene_manifest(scene, fps, aspect, sample_rate_hz) for scene in plan.scenes),
    )
