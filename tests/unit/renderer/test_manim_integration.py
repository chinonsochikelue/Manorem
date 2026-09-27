"""A real Manim render, end to end -- slow, and the only test that touches Manim.

Everything else in this package proves the seams without paying for a render. This
one pays: it compiles a scene, drives ``python -m manim`` in a subprocess, and
holds the output to the two things that must be exactly right -- the video is
frame-exact against the plan, and the result reports ``status=OK`` with
``quality=None`` (rendered, not assessed). Marked ``slow``; skipped without ffmpeg.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from manorem_compiler import CompileOptions, RenderPlan, compile_project
from manorem_ir import Aspect
from manorem_renderer import ManimRenderer, RenderOptions, RenderStatus
from tests.support.diag import error_codes
from tests.support.ir_builders import make_project, valid_scene

pytestmark = pytest.mark.slow

_HAS_FFMPEG = shutil.which("ffmpeg") is not None


def _plan() -> RenderPlan:
    plan, bag = compile_project(
        make_project(valid_scene()), CompileOptions(aspect=Aspect.WIDESCREEN)
    )
    assert error_codes(bag) == set(), error_codes(bag)
    return plan


@pytest.mark.skipif(not _HAS_FFMPEG, reason="ffmpeg not on PATH")
def test_manim_render_is_frame_exact_and_unassessed() -> None:
    plan = _plan()
    result = ManimRenderer().render(plan, RenderOptions(timeout_s=300.0))

    assert result.status is RenderStatus.OK, result.diagnostics
    assert result.video is not None
    assert result.video.exists()

    # Rendered is not assessed: M1 never fills quality.
    assert result.quality is None
    assert result.quality_assessed is False

    # The manifest and samples are emitted on every successful render.
    assert result.manifest.scenes
    assert result.frame_samples

    # Frame-exact: ffprobe duration equals the plan's summed frames / fps within
    # one frame. The plan owns all timing; the renderer never rescales a lane.
    expected_s = plan.total_frames / plan.fps
    measured_s = _probe_duration(result.video)
    assert abs(measured_s - expected_s) <= 1.0 / plan.fps


def _probe_duration(video: Path) -> float:
    ffprobe = shutil.which("ffprobe")
    assert ffprobe is not None, "ffprobe accompanies ffmpeg"
    out = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return float(out.stdout.strip())
