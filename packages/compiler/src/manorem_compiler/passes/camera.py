"""P5 Camera: semantic camera cues become concrete keyframes, still in stage units.

``zoom_to(target=packet, padding=0.3)`` says what the author cares about. Turning that
into a frame needs solved bounds, which is why this pass runs after P3 -- and turning it
into world units needs the target aspect, which is why it stops short of that and leaves
it to P6. Splitting it there is what makes the camera obey the same stage→world mapping
as everything else instead of carrying its own.

Three cues move the camera, and they differ in what they change:

* ``zoom_to`` -- centre *and* width, from the targets' combined bounds plus padding.
* ``pan_to`` -- centre only. The width is whatever the previous key left, because an
  author asking to pan has said nothing about zoom and inventing one would undo a
  deliberate framing.
* ``focus`` -- the visual half is P2's dimming; the camera half is a gentle ``zoom_to``
  with a wider default padding, so a focused object is emphasised without the frame
  diving at it.

**Every key is clamped by the spec's own limits**, so a planner asking to zoom to a dot
cannot produce a frame showing one pixel. The clamp is `CameraSpec.clamp_width`, the same
method the IR's own validator uses.

**A width is only ever inherited forward.** Keys are built in cue order and each starts
from the pose the last one left, which is what makes a ``pan_to`` after a ``zoom_to``
keep the zoom. ``reset_at_end`` appends a final key back to ``initial`` so a transition
starts from a known pose rather than wherever the last cue happened to leave the frame.
"""

from __future__ import annotations

from collections.abc import Iterable

from manorem_compiler.context import CameraKey, CompileContext, SceneWork
from manorem_compiler.params import number
from manorem_core import Code
from manorem_ir import (
    CameraState,
    Cue,
    Easing,
    SemanticOp,
    StageBounds,
    StagePoint,
    Window,
    union_all,
)

__all__ = ["run"]

#: Padding a ``focus`` frames its target with, when the cue does not say. Wider than a
#: ``zoom_to``'s: focus means "look at this", not "fill the frame with it".
_FOCUS_PADDING = 0.4

#: Padding a ``zoom_to`` uses by default -- enough that the subject is not cropped by
#: the estimate's own slack.
_ZOOM_PADDING = 0.15

#: Frames a ``reset_at_end`` move takes. Short, because it is housekeeping before a
#: transition rather than a movement anyone is meant to read.
_RESET_FRAMES = 12

#: Default padding per operation, and whether the operation sets the width at all. A
#: ``pan_to`` keeps whatever width the previous key left.
_MOVES: dict[SemanticOp, float | None] = {
    SemanticOp.ZOOM_TO: _ZOOM_PADDING,
    SemanticOp.FOCUS: _FOCUS_PADDING,
    SemanticOp.PAN_TO: None,
}


def _framed(bounds: Iterable[StageBounds], padding: float) -> tuple[StagePoint, float] | None:
    """Centre and width framing every box, or ``None`` when there are none.

    Width comes from the *wider* of the box's two axes plus padding, so a tall subject
    is not cropped top and bottom in 16:9 -- the height that follows from a width is a
    property of the format, and P6 is where that is known.
    """
    box = union_all(list(bounds))
    if box is None:
        return None
    return box.center, max(box.width, box.height) + 2.0 * padding


def _target_bounds(work: SceneWork, cue: Cue) -> list[StageBounds]:
    """Solved boxes for a camera cue's targets, groups expanded.

    Reads ``work.bounds`` rather than the scene, so a synthetic object an expansion
    invented can be framed too -- ``zoom_to(packet)`` is a reasonable thing to write
    about something a ``flow`` created.
    """
    boxes: list[StageBounds] = []
    for target in cue.targets:
        for object_id in work.symbols.expand(target) or (target,):
            box = work.bounds.get(object_id)
            if box is not None:
                boxes.append(box)
    return boxes


def _report_unframeable(ctx: CompileContext, work: SceneWork, cue: Cue, ptr: str) -> None:
    ctx.bag.add(
        Code.CMP402_UNSUPPORTED_INTENT,
        f"{cue.op.value} has nothing to frame: none of its targets has a solved position",
        pointer=ptr,
        scene_id=work.id,
        hint="Its targets resolve to no objects, so there is no region to move the "
        "camera to. The compiler will not pick one.",
    )


def _key(ctx: CompileContext, cue: Cue, window: Window, pose: CameraState) -> CameraKey:
    """One move on the frame grid, holding the pose it was resolved to.

    Quantized the same way P2 quantizes a step -- start and end independently against
    the cue's own start -- so a camera move that abuts a visual cue keeps abutting it.
    """
    start_frame = ctx.frames(window.start)
    length = max(ctx.frames(window.end) - start_frame, 1)
    return CameraKey(
        start_frame=start_frame,
        duration_frames=length,
        center=pose.center,
        width=pose.width,
        easing=cue.easing if cue.easing is not None else Easing.SMOOTH,
        cue_id=cue.id,
    )


def _initial(work: SceneWork) -> CameraState:
    """The camera's opening pose: the spec's, or one framing everything on stage.

    ``auto_frame`` frames the *authored* objects, not the synthetic ones. A particle
    that exists for a fifth of a second should not decide where the scene opens.
    """
    spec = work.scene.camera
    if not spec.auto_frame:
        return spec.initial
    framed = _framed(
        (box for object_id, box in work.bounds.items() if object_id in work.symbols.objects),
        _ZOOM_PADDING,
    )
    if framed is None:
        return spec.initial
    center, width = framed
    return CameraState(center=center, width=spec.clamp_width(width))


def _moved(
    ctx: CompileContext, work: SceneWork, cue: Cue, ptr: str, pose: CameraState
) -> CameraState | None:
    """The pose one camera cue asks for, or ``None`` when it cannot be resolved.

    A ``pan_to`` keeps the incoming width; the others recompute it from the targets'
    combined extent. Either way the result goes through ``clamp_width``, so no cue can
    frame less than the spec allows.
    """
    default_padding = _MOVES[cue.op]
    padding = number(cue.params, "padding", default_padding or _ZOOM_PADDING)
    framed = _framed(_target_bounds(work, cue), padding)
    if framed is None:
        _report_unframeable(ctx, work, cue, ptr)
        return None
    center, width = framed
    spec = work.scene.camera
    return CameraState(
        center=center,
        width=pose.width if default_padding is None else spec.clamp_width(width),
    )


def _camera_scene(ctx: CompileContext, work: SceneWork) -> None:
    pointers = {cue.id: work.ptr("timeline", i) for i, cue in enumerate(work.scene.timeline)}
    pose = _initial(work)
    work.camera_keys.append(
        CameraKey(start_frame=0, duration_frames=1, center=pose.center, width=pose.width)
    )
    for cue_id in work.symbols.cue_order:
        cue = work.scene.cue_by_id(cue_id)
        window = work.timing.window(cue_id)
        if cue is None or window is None or cue.op not in _MOVES:
            continue
        # A skill claiming a camera op takes the whole cue, visuals and framing alike:
        # its expansion already emitted whatever steps it wanted, and second-guessing
        # the frame here would fight it.
        if cue.op in work.skills.expansions:
            continue
        resolved = _moved(ctx, work, cue, pointers[cue_id], pose)
        if resolved is None:
            continue
        pose = resolved
        work.camera_keys.append(_key(ctx, cue, window, pose))
    _reset(work, pose)
    work.camera_keys.sort(key=lambda key: (key.start_frame, key.duration_frames))


def _reset(work: SceneWork, pose: CameraState) -> None:
    """Return to the opening pose before the scene ends, when the spec asks for it."""
    spec = work.scene.camera
    initial = spec.initial
    if not spec.reset_at_end or (pose.center == initial.center and pose.width == initial.width):
        return
    start = max(work.duration_frames - _RESET_FRAMES, 0)
    work.camera_keys.append(
        CameraKey(
            start_frame=start,
            duration_frames=max(work.duration_frames - start, 1),
            center=initial.center,
            width=initial.width,
        )
    )


def run(ctx: CompileContext) -> None:
    for work in ctx.scenes:
        _camera_scene(ctx, work)
