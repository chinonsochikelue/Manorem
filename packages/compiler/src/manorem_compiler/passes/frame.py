"""P6 Frame: the one place stage space becomes Manim world units.

Everything upstream is authored in stage space -- ``[-1, 1]`` on both axes, the unit
square being the safe area. That is what lets one scene render to 16:9, 9:16 and 1:1
without editing it, and it only holds while exactly one pass knows the conversion. This
is that pass, and :class:`~manorem_compiler.context.FrameMapping` is its whole output:
a scale and the frame's world dimensions.

**The scale is a single number for both axes.** An anisotropic map would fit the safe
area to any frame perfectly and turn every circle into an ellipse in 9:16 -- so per-aspect
fitting happens by choosing *which axis binds* instead. The scale comes from the shorter
side of the frame, minus the safe margin, so the safe square always fits with room and
the longer axis simply has space to spare. In 16:9 that means the height binds and there
is width left over; in 9:16 the width binds. Both keep circles round.

**Manim's frame height is fixed at 8.0 world units** whatever the pixel resolution, so
the frame's world size follows from the aspect alone and a draft render and a final one
share coordinates exactly. That is what makes a 480p golden a real check on a 1080p
delivery.

**Camera widths are clamped here, not earlier.** P5 clamps against the spec's own limits,
which are stage-space policy; this pass additionally refuses a frame wider than the world
can show. A key asking to see more than the whole frame would otherwise silently zoom out
past the background.
"""

from __future__ import annotations

from manorem_compiler.context import CameraKey, CompileContext, FrameMapping, SceneWork

__all__ = ["run"]

#: Manim's world-space frame height, in world units. Fixed by the library regardless of
#: pixel resolution, which is why a 480p plan and a 1080p plan hold the same numbers.
MANIM_FRAME_HEIGHT = 8.0

#: Half the stage's extent on one axis: stage space spans ``[-1, 1]``, so the safe area
#: is two units wide and the scale maps *half* of it onto half the frame.
_STAGE_HALF = 1.0


def _mapping(ctx: CompileContext) -> FrameMapping:
    """Stage-to-world scale for the target aspect, and the frame it fits inside."""
    frame_height = MANIM_FRAME_HEIGHT
    frame_width = MANIM_FRAME_HEIGHT * ctx.format.aspect.ratio
    usable = min(frame_width, frame_height) * (1.0 - 2.0 * ctx.options.safe_margin)
    return FrameMapping(
        scale=usable / (2.0 * _STAGE_HALF),
        frame_width=frame_width,
        frame_height=frame_height,
    )


def _clamped_keys(work: SceneWork, mapping: FrameMapping) -> None:
    """Hold every camera key's width inside what the frame can actually show.

    In stage units, because the keys are still stage-space here -- P7 is what turns
    them into world coordinates. The bound is the frame's own width expressed back in
    stage units, so a key asking to see the whole frame is left alone and one asking
    for more is pulled in rather than zooming out past the background.
    """
    limit = mapping.frame_width / mapping.scale
    for index, key in enumerate(work.camera_keys):
        if key.width <= limit:
            continue
        work.camera_keys[index] = CameraKey(
            start_frame=key.start_frame,
            duration_frames=key.duration_frames,
            center=key.center,
            width=limit,
            easing=key.easing,
            cue_id=key.cue_id,
        )


def run(ctx: CompileContext) -> None:
    mapping = _mapping(ctx)
    for work in ctx.scenes:
        # One mapping for the whole project: the aspect is a project-level format
        # decision, and per-scene scales would make a cross-scene transition rescale
        # everything mid-cut.
        work.frame_ = mapping
        _clamped_keys(work, mapping)
