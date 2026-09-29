"""One test per ``VQA6xx`` code, plus the seam that turns a render into a verdict.

These checks are pure functions of a :class:`RenderPlan` and its
:class:`RenderManifest`, so the fixtures are hand-built geometry rather than a real
render: a scene, a single sampled frame, and the boxes on it. That lets each test
force exactly one defect and assert exactly one code, which is the contract the
repair loop depends on -- a finding names an IR location it can patch.

The camera fills the 16:9 frame by default, so the visible stage is world x in
[-7.11, 7.11], y in [-4, 4]; ``camera_center``/``camera_width`` override that when a
test needs a narrowed or displaced viewport.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from manorem_compiler import MobjectSpec, PlanBounds, Primitive, RenderPlan
from manorem_compiler.plan import ScenePlan
from manorem_core import Code, Severity
from manorem_ir import Aspect, FormatSpec, StyleTokens
from manorem_renderer import (
    VQA_ERROR_CODES,
    GeometricVisualQA,
    RenderResult,
    RenderStatus,
    VQAConfig,
    VQAReport,
    assess_plan,
)
from manorem_renderer.results import (
    FrameManifest,
    MobjectSnapshot,
    RenderManifest,
    ScenePlanManifest,
)

#: The camera width that exactly fills a 16:9 frame (8.0 units tall).
_FULL_W = 8.0 * Aspect.WIDESCREEN.ratio

#: Default thresholds, materialised once so the helpers can default to them without
#: constructing a config in an argument default (ruff B008).
_CFG = VQAConfig()


def _bounds(cx: float, cy: float, w: float, h: float) -> PlanBounds:
    return PlanBounds(min_x=cx - w / 2, min_y=cy - h / 2, max_x=cx + w / 2, max_y=cy + h / 2)


@dataclass(frozen=True)
class Ob:
    """A drawable described once, projected into both a spec and a snapshot."""

    id: str
    primitive: Primitive
    bounds: PlanBounds
    visible: bool = True
    z: int = 0
    args: dict[str, object] = field(default_factory=dict)
    synthetic: bool = False
    members: tuple[str, ...] = ()


def _assess(
    obs: list[Ob],
    *,
    background: str = "#0E1116",
    camera_center: tuple[float, float, float] = (0.0, 0.0, 0.0),
    camera_width: float = _FULL_W,
    aspect: Aspect = Aspect.WIDESCREEN,
    cfg: VQAConfig = _CFG,
) -> set[Code]:
    """Assess one scene of ``obs`` at one frame and return the codes emitted."""
    report = _report(
        obs,
        background=background,
        camera_center=camera_center,
        camera_width=camera_width,
        aspect=aspect,
        cfg=cfg,
    )
    return {f.code for f in report.findings}


def _report(
    obs: list[Ob],
    *,
    background: str = "#0E1116",
    camera_center: tuple[float, float, float] = (0.0, 0.0, 0.0),
    camera_width: float = _FULL_W,
    aspect: Aspect = Aspect.WIDESCREEN,
    cfg: VQAConfig = _CFG,
    frames: int = 1,
) -> VQAReport:
    specs = tuple(
        MobjectSpec(
            id=o.id,
            primitive=o.primitive,
            bounds=o.bounds,
            z_index=o.z,
            args=o.args,  # type: ignore[arg-type]
            synthetic=o.synthetic,
            members=o.members,
        )
        for o in obs
    )
    scene = ScenePlan(id="s1", duration_frames=15, background=background, mobjects=specs)
    plan = RenderPlan(
        project_id="proj",
        format=FormatSpec.for_quality(aspect, "draft"),
        style=StyleTokens(),
        scenes=(scene,),
    )
    snaps = tuple(
        MobjectSnapshot(
            id=o.id, primitive=o.primitive, bounds=o.bounds, z_index=o.z, visible=o.visible
        )
        for o in obs
    )
    frame_list = tuple(
        FrameManifest(
            frame=i,
            time_s=float(i),
            camera_center=camera_center,
            camera_width=camera_width,
            mobjects=snaps,
        )
        for i in range(frames)
    )
    sm = ScenePlanManifest(scene_id="s1", duration_frames=15, frames=frame_list)
    manifest = RenderManifest(
        plan_version=plan.plan_version, project_id="proj", fps=plan.fps, scenes=(sm,)
    )
    return assess_plan(plan, manifest, cfg)


# --- clean baseline ---------------------------------------------------------


def test_clean_scene_has_no_findings() -> None:
    report = _report(
        [
            Ob("title", Primitive.TEXT, _bounds(0.0, 1.0, 4.0, 0.5), args={"color": "#F5F7FA"}),
            Ob("disc", Primitive.CIRCLE, _bounds(0.0, -1.0, 2.0, 2.0)),
        ]
    )
    assert report.findings == ()
    assert report.passed is True


# --- one test per code ------------------------------------------------------


def test_vqa601_text_overflow() -> None:
    # Text wider than the framed stage: not contained, glyphs clip.
    codes = _assess(
        [Ob("hdr", Primitive.TEXT, _bounds(0.0, 0.0, 20.0, 0.6), args={"color": "#F5F7FA"})]
    )
    assert Code.VQA601_TEXT_OVERFLOW in codes


def test_vqa602_object_off_stage_fully_outside() -> None:
    # A circle entirely outside the viewport is never seen.
    codes = _assess([Ob("stray", Primitive.CIRCLE, _bounds(50.0, 50.0, 1.0, 1.0))])
    assert Code.VQA602_OBJECT_OFF_STAGE in codes


def test_vqa602_object_off_stage_stray_sliver() -> None:
    # Pokes past the right edge but is too thin to be anything but stray geometry.
    codes = _assess(
        [Ob("wire", Primitive.LINE, _bounds(7.11, 0.0, 0.2, 0.004))],
    )
    assert Code.VQA602_OBJECT_OFF_STAGE in codes
    assert Code.VQA607_CUT_OFF_OBJECT not in codes


def test_vqa603_object_overlap() -> None:
    codes = _assess(
        [
            Ob("a", Primitive.CIRCLE, _bounds(0.0, 0.0, 2.0, 2.0)),
            Ob("b", Primitive.CIRCLE, _bounds(0.5, 0.0, 2.0, 2.0)),
        ]
    )
    assert Code.VQA603_OBJECT_OVERLAP in codes


def test_vqa603_ignores_different_z_layers() -> None:
    codes = _assess(
        [
            Ob("a", Primitive.CIRCLE, _bounds(0.0, 0.0, 2.0, 2.0), z=0),
            Ob("b", Primitive.CIRCLE, _bounds(0.5, 0.0, 2.0, 2.0), z=1),
        ]
    )
    assert Code.VQA603_OBJECT_OVERLAP not in codes


def test_vqa603_ignores_grouped_members() -> None:
    codes = _assess(
        [
            Ob("grp", Primitive.GROUP, _bounds(0.0, 0.0, 3.0, 2.0), members=("a", "b")),
            Ob("a", Primitive.CIRCLE, _bounds(0.0, 0.0, 2.0, 2.0)),
            Ob("b", Primitive.CIRCLE, _bounds(0.5, 0.0, 2.0, 2.0)),
        ]
    )
    assert Code.VQA603_OBJECT_OVERLAP not in codes


def test_vqa603_ignores_synthetic_overlay() -> None:
    # A highlight ring is meant to sit on its subject.
    codes = _assess(
        [
            Ob("node", Primitive.CIRCLE, _bounds(0.0, 0.0, 2.0, 2.0)),
            Ob("ring", Primitive.CIRCLE, _bounds(0.0, 0.0, 2.2, 2.2), synthetic=True),
        ]
    )
    assert Code.VQA603_OBJECT_OVERLAP not in codes


def test_vqa604_tiny_text() -> None:
    codes = _assess(
        [Ob("fine", Primitive.TEXT, _bounds(0.0, 0.0, 1.0, 0.1), args={"color": "#F5F7FA"})]
    )
    assert Code.VQA604_TINY_TEXT in codes


def test_vqa605_empty_frame() -> None:
    # Draws almost nothing: a single speck below the minimum scene area.
    codes = _assess([Ob("speck", Primitive.DOT, _bounds(0.0, 0.0, 0.02, 0.02))])
    assert Code.VQA605_EMPTY_FRAME in codes


def test_vqa606_bad_contrast() -> None:
    # Dark text on the dark default background.
    codes = _assess(
        [Ob("murk", Primitive.TEXT, _bounds(0.0, 0.0, 3.0, 0.5), args={"color": "#111418"})],
        background="#0E1116",
    )
    assert Code.VQA606_BAD_CONTRAST in codes


def test_vqa606_passes_high_contrast() -> None:
    codes = _assess(
        [Ob("bright", Primitive.TEXT, _bounds(0.0, 0.0, 3.0, 0.5), args={"color": "#F5F7FA"})],
        background="#0E1116",
    )
    assert Code.VQA606_BAD_CONTRAST not in codes


def test_vqa607_cut_off_object() -> None:
    # A big circle straddling the right edge renders cut off (not stray).
    codes = _assess([Ob("planet", Primitive.CIRCLE, _bounds(7.11, 0.0, 3.0, 3.0))])
    assert Code.VQA607_CUT_OFF_OBJECT in codes
    assert Code.VQA602_OBJECT_OFF_STAGE not in codes


def test_vqa608_excessive_density_is_a_warning() -> None:
    obs = [Ob(f"d{i}", Primitive.DOT, _bounds(-6.0 + i * 0.9, 0.0, 0.1, 0.1)) for i in range(13)]
    report = _report(obs)
    codes = {f.code for f in report.findings}
    assert Code.VQA608_EXCESSIVE_DENSITY in codes
    density = next(f for f in report.findings if f.code is Code.VQA608_EXCESSIVE_DENSITY)
    assert density.severity is Severity.WARNING
    # A warning does not fail the build.
    assert report.passed is True


def test_vqa609_camera_composition_is_a_warning() -> None:
    # Camera looks at empty space; the only subject sits far off-center.
    report = _report(
        [Ob("subj", Primitive.CIRCLE, _bounds(0.0, 0.0, 2.0, 2.0))],
        camera_center=(40.0, 0.0, 0.0),
    )
    codes = {f.code for f in report.findings}
    assert Code.VQA609_CAMERA_COMPOSITION in codes
    comp = next(f for f in report.findings if f.code is Code.VQA609_CAMERA_COMPOSITION)
    assert comp.severity is Severity.WARNING


# --- severity partition ------------------------------------------------------


def test_error_codes_are_exactly_601_to_607() -> None:
    assert (
        frozenset(
            {
                Code.VQA601_TEXT_OVERFLOW,
                Code.VQA602_OBJECT_OFF_STAGE,
                Code.VQA603_OBJECT_OVERLAP,
                Code.VQA604_TINY_TEXT,
                Code.VQA605_EMPTY_FRAME,
                Code.VQA606_BAD_CONTRAST,
                Code.VQA607_CUT_OFF_OBJECT,
            }
        )
        == VQA_ERROR_CODES
    )
    assert Code.VQA608_EXCESSIVE_DENSITY not in VQA_ERROR_CODES
    assert Code.VQA609_CAMERA_COMPOSITION not in VQA_ERROR_CODES


# --- dedupe and attribution --------------------------------------------------


def test_persistent_defect_reports_once_across_frames() -> None:
    report = _report(
        [Ob("stray", Primitive.CIRCLE, _bounds(50.0, 50.0, 1.0, 1.0))],
        frames=4,
    )
    offstage = [f for f in report.findings if f.code is Code.VQA602_OBJECT_OFF_STAGE]
    assert len(offstage) == 1


def test_finding_is_attributed_to_the_authored_owner() -> None:
    # A synthetic child's defect names the object the repair loop can patch.
    report = _report(
        [
            Ob("packet", Primitive.DOT, _bounds(50.0, 0.0, 0.5, 0.5), synthetic=True, members=()),
            Ob("path", Primitive.LINE, _bounds(0.0, 0.0, 4.0, 0.01), members=("packet",)),
        ]
    )
    offstage = next(f for f in report.findings if f.code is Code.VQA602_OBJECT_OFF_STAGE)
    assert offstage.object_id == "path"
    assert offstage.scene_id == "s1"


# --- GeometricVisualQA seam --------------------------------------------------


def _manifest_for(obs: list[Ob]) -> RenderManifest:
    snaps = tuple(
        MobjectSnapshot(
            id=o.id, primitive=o.primitive, bounds=o.bounds, z_index=o.z, visible=o.visible
        )
        for o in obs
    )
    frame = FrameManifest(
        frame=0, time_s=0.0, camera_center=(0.0, 0.0, 0.0), camera_width=_FULL_W, mobjects=snaps
    )
    sm = ScenePlanManifest(scene_id="s1", duration_frames=15, frames=(frame,))
    return RenderManifest(plan_version="1.0", project_id="proj", fps=15, scenes=(sm,))


def _plan_for(obs: list[Ob], *, background: str = "#0E1116") -> RenderPlan:
    specs = tuple(
        MobjectSpec(id=o.id, primitive=o.primitive, bounds=o.bounds, z_index=o.z, args=o.args)  # type: ignore[arg-type]
        for o in obs
    )
    scene = ScenePlan(id="s1", duration_frames=15, background=background, mobjects=specs)
    return RenderPlan(
        project_id="proj",
        format=FormatSpec.for_quality(Aspect.WIDESCREEN, "draft"),
        style=StyleTokens(),
        scenes=(scene,),
    )


def test_geometric_vqa_returns_none_for_failed_render() -> None:
    obs = [Ob("hdr", Primitive.TEXT, _bounds(0.0, 0.0, 20.0, 0.6), args={"color": "#F5F7FA"})]
    result = RenderResult(
        status=RenderStatus.FAILED,
        video=None,
        frame_samples=(),
        manifest=_manifest_for(obs),
    )
    assert GeometricVisualQA().assess(_plan_for(obs), result) is None


def test_geometric_vqa_assesses_an_ok_render() -> None:
    obs = [Ob("hdr", Primitive.TEXT, _bounds(0.0, 0.0, 20.0, 0.6), args={"color": "#F5F7FA"})]
    result = RenderResult(
        status=RenderStatus.OK,
        video=Path("scene.mp4"),
        frame_samples=(),
        manifest=_manifest_for(obs),
    )
    report = GeometricVisualQA().assess(_plan_for(obs), result)
    assert report is not None
    assert Code.VQA601_TEXT_OVERFLOW in {f.code for f in report.findings}


def test_geometric_vqa_name() -> None:
    assert GeometricVisualQA().name == "geometric"
