"""What a renderer is asked for, and what it hands back.

Two outcomes live here, and keeping them apart is the whole point of the module.
``status`` answers *did rendering complete* -- did a video come out, or did the
backend crash or time out. ``quality`` answers *is the frame any good* -- and in
M1 it is always ``None``, because no :class:`~manorem_renderer.VisualQA` exists
yet. ``None`` means **not assessed**; it must never be read as "assessed and
passing". A render that produced a file is not a render anyone has looked at.

The manifest and the frame samples are emitted on *every* render, by every
backend, regardless of whether QA is wired up. They are the inputs a future QA
stage needs -- the manifest for the geometric checks (overlap, off-frame,
density) and the samples for the perceptual ones (readable text, contrast) -- and
they have to exist before there is anything to assess, so they land now.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from manorem_compiler import PlanBounds, Point3, Primitive, RenderPlan
from manorem_core import Diagnostic, Severity

__all__ = [
    "Capability",
    "FrameManifest",
    "MobjectSnapshot",
    "QualityReport",
    "RenderManifest",
    "RenderOptions",
    "RenderResult",
    "RenderStatus",
    "Renderer",
    "ScenePlanManifest",
]


class RenderStatus(StrEnum):
    """Whether rendering *ran to completion* -- not whether it looks good.

    Deliberately small: a backend either produced a video (``OK``), failed while
    trying (``FAILED``), or was killed for exceeding its time budget
    (``TIMEOUT``). Visual quality is a separate axis with a separate type.
    """

    OK = "ok"
    FAILED = "failed"
    TIMEOUT = "timeout"


class Capability(StrEnum):
    """What a backend can do, so a caller can pick one without a try/except.

    A future ``WebGLRenderer`` that cannot move the camera, or a stub that emits
    no real pixels, declares that here rather than failing halfway through a plan
    that needs it.
    """

    RASTER_VIDEO = "raster_video"
    FRAME_SAMPLES = "frame_samples"
    SCENE_MANIFEST = "scene_manifest"
    CAMERA_MOVES = "camera_moves"
    TRANSPARENT_BACKGROUND = "transparent_background"


@dataclass(frozen=True, slots=True)
class RenderOptions:
    """Everything a render needs that is not in the plan.

    The plan fixes *what* to draw and *when*, down to the frame; these are the
    knobs that do not change the pixels' meaning -- how hard to work, how long to
    wait, how often to sample for QA.
    """

    #: Manim quality preset name. Draft (480p15) for tests and previews.
    quality: str = "draft"
    #: Wall-clock ceiling for the render subprocess. Exceeding it is a ``TIMEOUT``,
    #: not a crash: the plan may be fine and the machine merely slow.
    timeout_s: float = 600.0
    #: How often to sample a frame for the QA seam, in hertz. One per second plus
    #: the first and last frame of every scene, which is enough to catch a scene
    #: that is empty, cropped, or unreadable without storing every frame.
    sample_rate_hz: float = 1.0
    #: Keep the per-render scratch directory instead of deleting it. Debug aid.
    keep_workspace: bool = False


class MobjectSnapshot(BaseModel):
    """One drawable as it stood at one sampled frame: where it was, was it up.

    Carries the plan's own resolved :class:`~manorem_compiler.PlanBounds`, so a QA
    check measures overlap and off-frame from numbers the compiler already
    computed rather than from pixels it would have to segment.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    primitive: Primitive
    bounds: PlanBounds
    z_index: int
    visible: bool


class FrameManifest(BaseModel):
    """The state of one sampled frame: the camera, and what was on stage."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    frame: int = Field(ge=0)
    time_s: float = Field(ge=0.0)
    camera_center: Point3
    camera_width: float = Field(gt=0.0)
    mobjects: tuple[MobjectSnapshot, ...] = ()

    @property
    def visible_mobjects(self) -> tuple[MobjectSnapshot, ...]:
        return tuple(m for m in self.mobjects if m.visible)


class ScenePlanManifest(BaseModel):
    """Every sampled frame of one scene, in frame order.

    This is the geometric record a QA stage reads: for any sampled instant it can
    say which mobjects were up, where their boxes were, and where the camera was
    looking -- all without decoding a single pixel.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    scene_id: str
    duration_frames: int = Field(ge=1)
    frames: tuple[FrameManifest, ...] = ()


class RenderManifest(BaseModel):
    """The whole plan's sampled geometry, content-addressable like the plan itself.

    Emitted on every render. A QA stage consumes this; nothing in M1 does, which
    is the point -- the seam is load-bearing before the checks that use it exist.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    plan_version: str
    project_id: str
    fps: int = Field(ge=1)
    scenes: tuple[ScenePlanManifest, ...] = ()

    def scene(self, scene_id: str) -> ScenePlanManifest | None:
        return next((s for s in self.scenes if s.scene_id == scene_id), None)


class QualityReport(BaseModel):
    """A visual-quality verdict: the ``VQA6xx`` findings a QA stage produced.

    Present only when something actually assessed the render. Its absence
    (``RenderResult.quality is None``) is *not assessed*, never *assessed and
    fine* -- the two are different states and the type refuses to conflate them.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    findings: tuple[Diagnostic, ...] = ()

    @property
    def passed(self) -> bool:
        """No error-severity finding. A warning is a note, not a failure."""
        return not any(f.severity is Severity.ERROR for f in self.findings)


@dataclass(frozen=True, slots=True)
class RenderResult:
    """The outcome of one render: the two-axis result the module exists to keep apart.

    ``status`` is about the *process*; ``quality`` is about the *picture*. A
    caller that wants "is this a good video" must check both, and must treat
    ``quality is None`` as an open question rather than a yes.
    """

    status: RenderStatus
    #: The rendered video, or ``None`` when ``status`` is not ``OK``.
    video: Path | None
    #: Sampled keyframes, always emitted on a successful render (possibly empty
    #: only when a backend cannot rasterize at all).
    frame_samples: tuple[Path, ...]
    #: The geometric record, emitted on every successful render.
    manifest: RenderManifest
    #: ``None`` = NOT ASSESSED. Never conflate with an empty passing report.
    quality: QualityReport | None = None
    #: Why a render failed or timed out, as ``RND5xx`` diagnostics.
    diagnostics: tuple[Diagnostic, ...] = field(default_factory=tuple)
    #: Wall-clock the render took, for tracing and cost.
    duration_ms: int = 0

    @property
    def ok(self) -> bool:
        return self.status is RenderStatus.OK

    @property
    def quality_assessed(self) -> bool:
        """Distinct from ``quality.passed``: was the picture looked at *at all*."""
        return self.quality is not None


@runtime_checkable
class Renderer(Protocol):
    """A backend that turns a :class:`~manorem_compiler.RenderPlan` into a video.

    The plan is finished -- numbers, enums and validated keys -- so a renderer is
    an interpreter, not a geometry engine. It declares its ``capabilities`` so a
    caller can choose one, and it emits a manifest and frame samples on every
    successful render whether or not anyone assesses them yet.
    """

    name: str
    capabilities: frozenset[Capability]

    def render(self, plan: RenderPlan, opts: RenderOptions) -> RenderResult: ...
