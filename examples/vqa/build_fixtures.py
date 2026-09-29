"""Generate the ``examples/vqa/<defect>/plan.json`` corpus.

Each fixture is a hand-authored :class:`~manorem_compiler.RenderPlan` crafted to
exhibit exactly one Visual QA defect (or, for ``good``, none). RenderPlan JSON is
the right shape for these fixtures rather than Visual IR: the compiler's P6 pass
safe-area-clamps geometry, so authoring an off-stage or overflowing object through
the IR is deliberately hard -- but a defect *can* still reach a rendered frame, and
the QA seam reads the plan's world geometry, so that is what a fixture pins down.

Every fixture is one scene (``s1``) with visible mobjects; the manifest the checks
read is derived deterministically by :func:`~manorem_renderer.build_manifest`. Run
this module to (re)write the JSON files:

    uv run python examples/vqa/build_fixtures.py
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from manorem_compiler import (
    CAMERA_TRACK_ID,
    MobjectSpec,
    PlanBounds,
    PlanEvent,
    Primitive,
    RenderPlan,
    ScenePlan,
    Track,
)
from manorem_compiler.plan import CameraFrameAnim
from manorem_ir import Aspect, FormatSpec, StyleTokens

#: Widescreen full frame: world x in [-7.11, 7.11], y in [-4, 4].
_FULL_W = 8.0 * Aspect.WIDESCREEN.ratio
_HERE = Path(__file__).resolve().parent


def _bounds(cx: float, cy: float, w: float, h: float) -> PlanBounds:
    return PlanBounds(min_x=cx - w / 2, min_y=cy - h / 2, max_x=cx + w / 2, max_y=cy + h / 2)


def _mob(
    oid: str,
    primitive: Primitive,
    bounds: PlanBounds,
    *,
    z: int = 0,
    args: Mapping[str, object] | None = None,
    synthetic: bool = False,
    members: tuple[str, ...] = (),
) -> MobjectSpec:
    return MobjectSpec(
        id=oid,
        primitive=primitive,
        bounds=bounds,
        z_index=z,
        args=args or {},  # type: ignore[arg-type]
        synthetic=synthetic,
        members=members,
        initial_visible=True,
    )


def _plan(
    project_id: str,
    *mobjects: MobjectSpec,
    background: str = "#0E1116",
    camera: Track | None = None,
) -> RenderPlan:
    scene = ScenePlan(
        id="s1",
        duration_frames=15,
        background=background,
        mobjects=tuple(mobjects),
        camera=camera or Track(target_id=CAMERA_TRACK_ID),
    )
    return RenderPlan(
        project_id=project_id,
        format=FormatSpec.for_quality(Aspect.WIDESCREEN, "draft"),
        style=StyleTokens(),
        scenes=(scene,),
    )


_WHITE = {"color": "#F5F7FA"}


def _fixtures() -> dict[str, RenderPlan]:
    return {
        # A clean scene: legible title, one shape, both inside the stage.
        "good": _plan(
            "vqa_good",
            _mob("title", Primitive.TEXT, _bounds(0.0, 1.0, 4.0, 0.5), args=_WHITE),
            _mob("disc", Primitive.CIRCLE, _bounds(0.0, -1.0, 2.0, 2.0)),
        ),
        # VQA601: text wider than the framed stage -- glyphs clip.
        "overflow": _plan(
            "vqa_overflow",
            _mob("hdr", Primitive.TEXT, _bounds(0.0, 0.0, 20.0, 0.6), args=_WHITE),
        ),
        # VQA602: a circle entirely outside the viewport, never seen.
        "off-stage": _plan(
            "vqa_off_stage",
            _mob("stray", Primitive.CIRCLE, _bounds(50.0, 50.0, 1.0, 1.0)),
        ),
        # VQA603: two ungrouped circles collide on the same layer.
        "overlap": _plan(
            "vqa_overlap",
            _mob("a", Primitive.CIRCLE, _bounds(0.0, 0.0, 2.0, 2.0)),
            _mob("b", Primitive.CIRCLE, _bounds(0.5, 0.0, 2.0, 2.0)),
        ),
        # VQA604: text below the legibility floor.
        "tiny-text": _plan(
            "vqa_tiny_text",
            _mob("fine", Primitive.TEXT, _bounds(0.0, 0.0, 1.0, 0.1), args=_WHITE),
        ),
        # VQA605: a single speck below the minimum scene area.
        "empty-frame": _plan(
            "vqa_empty_frame",
            _mob("speck", Primitive.DOT, _bounds(0.0, 0.0, 0.02, 0.02)),
        ),
        # VQA606: dark text on the dark default background.
        "contrast": _plan(
            "vqa_contrast",
            _mob("murk", Primitive.TEXT, _bounds(0.0, 0.0, 3.0, 0.5), args={"color": "#111418"}),
        ),
        # VQA607: a large circle straddling the right edge renders cut off.
        "cut-off": _plan(
            "vqa_cut_off",
            _mob("planet", Primitive.CIRCLE, _bounds(7.11, 0.0, 3.0, 3.0)),
        ),
        # VQA608 (warning): too many mobjects on one frame.
        "density": _plan(
            "vqa_density",
            *(
                _mob(f"d{i}", Primitive.DOT, _bounds(-6.0 + i * 0.9, 0.0, 0.1, 0.1))
                for i in range(13)
            ),
        ),
        # VQA609 (warning): the camera centres on empty space.
        "camera": _plan(
            "vqa_camera",
            _mob("subj", Primitive.CIRCLE, _bounds(0.0, 0.0, 2.0, 2.0)),
            camera=Track(
                target_id=CAMERA_TRACK_ID,
                events=(
                    PlanEvent(
                        start_frame=0,
                        duration_frames=1,
                        anim=CameraFrameAnim(center=(40.0, 0.0, 0.0), width=_FULL_W),
                    ),
                ),
            ),
        ),
    }


def main() -> None:
    for name, plan in _fixtures().items():
        out = _HERE / name / "plan.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(plan.model_dump_json(indent=2) + "\n", encoding="utf-8")
        print(f"wrote {out}")


if __name__ == "__main__":
    main()
