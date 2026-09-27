"""``build_manifest`` -- the geometric record, computed from the plan not the pixels.

Every backend emits this, and every backend must emit the *same* one for the same
plan, because it is derived from the RenderPlan alone. These tests pin that: the
manifest's frames are exactly ``sample_frames`` says they are, its scene shape
mirrors the plan, and two builds of one plan are equal. Nothing here renders.
"""

from __future__ import annotations

from manorem_compiler import CompileOptions, RenderPlan, compile_project
from manorem_ir import Aspect
from manorem_renderer import build_manifest, sample_frames
from tests.support.diag import error_codes
from tests.support.ir_builders import make_project, valid_scene


def _plan(aspect: Aspect = Aspect.WIDESCREEN) -> RenderPlan:
    plan, bag = compile_project(make_project(valid_scene()), CompileOptions(aspect=aspect))
    assert error_codes(bag) == set(), error_codes(bag)
    return plan


def test_carries_plan_identity() -> None:
    plan = _plan()
    manifest = build_manifest(plan, sample_rate_hz=1.0)
    assert manifest.plan_version == plan.plan_version
    assert manifest.project_id == plan.project_id
    assert manifest.fps == plan.fps


def test_one_scene_manifest_per_scene() -> None:
    plan = _plan()
    manifest = build_manifest(plan, sample_rate_hz=1.0)
    assert len(manifest.scenes) == len(plan.scenes)
    for scene, scene_manifest in zip(plan.scenes, manifest.scenes, strict=True):
        assert scene_manifest.scene_id == scene.id
        assert scene_manifest.duration_frames == scene.duration_frames


def test_frames_are_exactly_the_sampled_indices() -> None:
    plan = _plan()
    manifest = build_manifest(plan, sample_rate_hz=1.0)
    for scene, scene_manifest in zip(plan.scenes, manifest.scenes, strict=True):
        expected = sample_frames(scene.duration_frames, plan.fps, 1.0)
        assert tuple(f.frame for f in scene_manifest.frames) == expected


def test_scene_lookup() -> None:
    plan = _plan()
    manifest = build_manifest(plan, sample_rate_hz=1.0)
    first = plan.scenes[0].id
    found = manifest.scene(first)
    assert found is not None
    assert found.scene_id == first
    assert manifest.scene("does_not_exist") is None


def test_pure_and_deterministic() -> None:
    plan = _plan()
    assert build_manifest(plan, sample_rate_hz=1.0) == build_manifest(plan, sample_rate_hz=1.0)


def test_sample_rate_changes_frame_count_not_geometry() -> None:
    plan = _plan()
    sparse = build_manifest(plan, sample_rate_hz=1.0)
    dense = build_manifest(plan, sample_rate_hz=5.0)
    sparse_scene = sparse.scenes[0]
    dense_scene = dense.scenes[0]
    assert len(dense_scene.frames) >= len(sparse_scene.frames)
    # The camera width at frame 0 is a property of the plan, not of how often we
    # sampled it -- both builds must agree on it.
    assert sparse_scene.frames[0].camera_width == dense_scene.frames[0].camera_width
