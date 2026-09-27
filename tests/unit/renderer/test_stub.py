"""``StubRenderer`` -- the offline stand-in, and the invariants every backend shares.

The stub exists so the pipeline runs without Manim or LaTeX, but it is not a toy:
it emits the same manifest and the same frame samples a real backend does, because
both come from the plan. These tests hold it to that, and to the module's central
rule -- ``quality`` is ``None`` and that means *not assessed*, never *fine*.
"""

from __future__ import annotations

import shutil

import pytest

from manorem_compiler import CompileOptions, RenderPlan, compile_project
from manorem_ir import Aspect
from manorem_renderer import (
    Capability,
    RenderOptions,
    RenderStatus,
    StubRenderer,
)
from tests.support.diag import error_codes
from tests.support.ir_builders import make_project, valid_scene

_HAS_FFMPEG = shutil.which("ffmpeg") is not None


def _plan() -> RenderPlan:
    plan, bag = compile_project(
        make_project(valid_scene()), CompileOptions(aspect=Aspect.WIDESCREEN)
    )
    assert error_codes(bag) == set(), error_codes(bag)
    return plan


def test_declares_its_capabilities() -> None:
    stub = StubRenderer()
    assert stub.name == "stub"
    assert Capability.SCENE_MANIFEST in stub.capabilities
    assert Capability.FRAME_SAMPLES in stub.capabilities
    # The stub paints solid colours; it cannot honour a camera move and says so.
    assert Capability.CAMERA_MOVES not in stub.capabilities


def test_manifest_emitted_regardless_of_ffmpeg() -> None:
    plan = _plan()
    result = StubRenderer().render(plan, RenderOptions())
    # The manifest is computed from the plan, so it stands even if the video step
    # cannot run. It must match a direct build.
    assert result.manifest.project_id == plan.project_id
    assert len(result.manifest.scenes) == len(plan.scenes)


def test_frame_samples_emitted_and_named_per_frame() -> None:
    plan = _plan()
    result = StubRenderer().render(plan, RenderOptions())
    total_sampled = sum(len(s.frames) for s in result.manifest.scenes)
    # Samples come from PIL, not ffmpeg, so they exist either way.
    assert len(result.frame_samples) == total_sampled
    for path in result.frame_samples:
        assert path.exists()
        assert path.suffix == ".png"


def test_quality_is_unassessed_never_passing() -> None:
    result = StubRenderer().render(_plan(), RenderOptions())
    assert result.quality is None
    assert result.quality_assessed is False


@pytest.mark.skipif(not _HAS_FFMPEG, reason="ffmpeg not on PATH")
def test_produces_a_video_when_ffmpeg_present() -> None:
    result = StubRenderer().render(_plan(), RenderOptions())
    assert result.status is RenderStatus.OK
    assert result.video is not None
    assert result.video.exists()
    assert result.ok is True


@pytest.mark.skipif(_HAS_FFMPEG, reason="only meaningful without ffmpeg")
def test_fails_loudly_without_ffmpeg() -> None:
    result = StubRenderer().render(_plan(), RenderOptions())
    assert result.status is RenderStatus.FAILED
    assert result.video is None
    # Even a failed video render still handed back its manifest and samples.
    assert result.frame_samples
    assert result.diagnostics
