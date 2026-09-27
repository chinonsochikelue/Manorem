"""The backend line-up and the two-axis result contract.

``ManimRenderer`` is the real backend; the GL/WebGL entries are declared for
capability gating but refuse to run in M1. And ``RenderResult`` keeps *did it
render* apart from *is it any good* -- these tests pin the second axis so no
future caller quietly reads ``quality is None`` as a pass.
"""

from __future__ import annotations

from typing import cast

import pytest

from manorem_compiler import RenderPlan
from manorem_core import Code, Diagnostic, Severity
from manorem_renderer import (
    Capability,
    ManimGLRenderer,
    ManimRenderer,
    QualityReport,
    RenderManifest,
    RenderOptions,
    RenderResult,
    RenderStatus,
    WebGLRenderer,
)


def test_manim_renderer_advertises_camera_and_qa_seam() -> None:
    renderer = ManimRenderer()
    assert renderer.name == "manim"
    assert Capability.CAMERA_MOVES in renderer.capabilities
    assert Capability.FRAME_SAMPLES in renderer.capabilities
    assert Capability.SCENE_MANIFEST in renderer.capabilities


@pytest.mark.parametrize("cls", [ManimGLRenderer, WebGLRenderer])
def test_declared_but_unbuilt_backends_refuse_to_run(cls: type) -> None:
    renderer = cls()
    # They still declare capabilities so callers can gate on them today...
    assert renderer.capabilities
    # ...but calling render raises rather than returning a misleading result. The
    # args are never read (the method raises first), so a cast keeps the test honest.
    with pytest.raises(NotImplementedError):
        renderer.render(cast("RenderPlan", None), RenderOptions())


def _manifest() -> RenderManifest:
    return RenderManifest(plan_version="1.0", project_id="p", fps=15, scenes=())


def test_quality_none_is_not_assessed() -> None:
    result = RenderResult(
        status=RenderStatus.OK, video=None, frame_samples=(), manifest=_manifest(), quality=None
    )
    assert result.ok is True
    assert result.quality_assessed is False


def test_quality_present_even_when_empty_is_assessed() -> None:
    # An empty passing report is a *verdict*; None is the absence of one. The two
    # must not collapse -- an assessed-and-clean render is not the M1 default.
    report = QualityReport(findings=())
    result = RenderResult(
        status=RenderStatus.OK, video=None, frame_samples=(), manifest=_manifest(), quality=report
    )
    assert result.quality_assessed is True
    assert result.quality is not None
    assert result.quality.passed is True


def test_quality_report_fails_on_an_error_finding() -> None:
    finding = Diagnostic(code=Code.RND501_RENDERER_FAILED, severity=Severity.ERROR, message="boom")
    report = QualityReport(findings=(finding,))
    assert report.passed is False
