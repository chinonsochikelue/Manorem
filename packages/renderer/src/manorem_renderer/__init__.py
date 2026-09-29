"""The renderer: a RenderPlan in, silent video out, and no codegen between.

This package is the §26 boundary made concrete. A renderer takes a fully lowered,
numeric :class:`~manorem_compiler.RenderPlan` and interprets it -- there is no path
on which model-authored text becomes executed Python. What Step 5 built:

* a ``Renderer`` protocol with ``name`` and ``capabilities`` (:mod:`.results`),
* ``manorem_renderer.manim.plan_scene`` -- a fixed ``MovingCameraScene`` that
  re-validates the plan and drives it through mobject/animation factory tables,
* ``ManimRenderer`` (subprocess-isolated, timed) and a fast ``StubRenderer``,
* a ``RenderResult`` whose ``status`` (did it render) and ``quality`` (was it any
  good -- ``None`` until a Visual QA stage exists) are separate by type,

with ``frame_samples`` and a ``RenderManifest`` emitted on every render so the
Visual QA stage can drop in later without touching the renderer again.

The ``manorem_renderer.manim`` subpackage is intentionally *not* imported here:
it pulls in Manim, and both :class:`ManimRenderer` and the fast test suite must
stay free of that dependency. It is imported only inside the render subprocess.
"""

from __future__ import annotations

from manorem_renderer.frames import sample_frames
from manorem_renderer.manifest import MANIM_FRAME_HEIGHT, build_manifest
from manorem_renderer.renderer import ManimGLRenderer, ManimRenderer, WebGLRenderer
from manorem_renderer.results import (
    Capability,
    FrameManifest,
    MobjectSnapshot,
    QualityReport,
    Renderer,
    RenderManifest,
    RenderOptions,
    RenderResult,
    RenderStatus,
    ScenePlanManifest,
)
from manorem_renderer.stub import StubRenderer
from manorem_renderer.vqa import (
    VQA_ERROR_CODES,
    GeometricVisualQA,
    VQAConfig,
    VQAReport,
    assess_plan,
)

__all__ = [
    "MANIM_FRAME_HEIGHT",
    "VQA_ERROR_CODES",
    "Capability",
    "FrameManifest",
    "GeometricVisualQA",
    "ManimGLRenderer",
    "ManimRenderer",
    "MobjectSnapshot",
    "QualityReport",
    "RenderManifest",
    "RenderOptions",
    "RenderResult",
    "RenderStatus",
    "Renderer",
    "ScenePlanManifest",
    "StubRenderer",
    "VQAConfig",
    "VQAReport",
    "WebGLRenderer",
    "assess_plan",
    "build_manifest",
    "sample_frames",
]
