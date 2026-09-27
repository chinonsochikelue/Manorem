"""What the passes share, and the contract each one signs.

A pass is ``run(ctx: CompileContext) -> None``. It reads what earlier passes wrote,
writes its own result into the context, and appends diagnostics; it never returns a
value and never raises for an authoring mistake. That shape is what makes the
pipeline inspectable -- after any pass you can print the context and see exactly
how far compilation got -- and what makes the driver's halting rule a single
statement rather than an exception convention.

Two things this module is careful about.

**Staged state is optional, and asking early is an error.** ``symbols`` does not
exist before P1 and ``frame`` does not exist before P6. Rather than default them to
something empty and let a mis-ordered pass silently compute nonsense, the accessors
raise :class:`~manorem_core.CompileError` naming the pass that should have run. A
pipeline bug then reads as "P7 ran before P6", not as a stack trace inside a
lowering helper.

**Diagnostics accumulate; the driver decides when to stop.** A pass reports every
problem it can see and keeps going, so one compile surfaces four layout faults
instead of the first one four times. Only the driver looks at severity.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from manorem_compiler.plan import ScenePlan
from manorem_core import CompileError, Diagnostic, DiagnosticBag, pointer
from manorem_ir import (
    RESOLUTIONS,
    Aspect,
    Easing,
    FormatSpec,
    ParamValue,
    Project,
    ResolvedTiming,
    Scene,
    SceneObject,
    SemanticOp,
    StageBounds,
    StagePoint,
    StageSize,
    StyleTokens,
    ValidationContext,
    ValidationPolicy,
)
from manorem_skills import ResolvedSkills, SyntheticObject

__all__ = [
    "CameraKey",
    "CompileContext",
    "CompileOptions",
    "CompilerPass",
    "FrameMapping",
    "SceneWork",
    "ScheduledStep",
    "SymbolTable",
]

#: Named (aspect, quality) tiers, searched when an aspect override has to pick a
#: resolution. A tuple so the lookup order is stable across runs.
_TIERS: tuple[tuple[tuple[Aspect, str], tuple[int, int]], ...] = tuple(RESOLUTIONS.items())


def _rescale(spec: FormatSpec, aspect: Aspect) -> FormatSpec:
    """Same pixel budget, new aspect.

    Changing ``aspect`` alone would fail ``FormatSpec``'s own consistency check, so
    the dimensions move with it. A spec matching a named tier is re-derived from that
    tier, which is how ``--aspect 9:16`` alone keeps the quality the author chose.
    """
    for (candidate, quality), size in _TIERS:
        if candidate is spec.aspect and size == (spec.width, spec.height):
            return FormatSpec.for_quality(aspect, quality)
    # Not a named tier: keep the binding dimension and derive the other, rounded to
    # an even pixel count because most encoders require it.
    height = spec.height if aspect.ratio >= 1.0 else spec.width
    width = round(height * aspect.ratio / 2.0) * 2
    return FormatSpec(
        aspect=aspect, width=width, height=height, fps=spec.fps, bitrate_kbps=spec.bitrate_kbps
    )


@dataclass(frozen=True, slots=True)
class CompileOptions:
    """Everything the compiler needs that is not in the IR.

    ``aspect`` and ``quality`` override the project's own ``FormatSpec`` so one
    authored IR compiles to three formats without editing it -- which is the whole
    point of keeping layout in stage space.
    """

    aspect: Aspect | None = None
    quality: str | None = None
    policy: ValidationPolicy = field(default_factory=ValidationPolicy)
    #: Run the mechanically-safe autofixers before validating. Semantic defects are
    #: never touched by them; see :mod:`manorem_compiler.autofix`.
    autofix: bool = True
    #: Fraction of the frame reserved as margin when mapping stage to world units.
    safe_margin: float = 0.06
    #: Words per minute for narration estimates. ``None`` uses the project's own.
    wpm: float | None = None

    def format_for(self, project: Project) -> FormatSpec:
        """The format to compile against: the project's, with overrides applied."""
        if self.aspect is None and self.quality is None:
            return project.format
        aspect = self.aspect if self.aspect is not None else project.format.aspect
        if self.quality is not None:
            return FormatSpec.for_quality(aspect, self.quality)
        return _rescale(project.format, aspect)


@dataclass(frozen=True, slots=True)
class SymbolTable:
    """Everything addressable in one scene, resolved once by P1.

    Later passes look ids up here rather than scanning the scene again, so a pass
    cannot disagree with validation about what an id refers to.
    """

    objects: Mapping[str, SceneObject]
    groups: Mapping[str, tuple[str, ...]]
    #: Cues in dependency order. A cue in a cycle is absent -- P1 reports it, and no
    #: later pass has to defend against one.
    cue_order: tuple[str, ...]

    def expand(self, target_id: str) -> tuple[str, ...]:
        """Object ids a cue target names: itself, or a group's members."""
        if target_id in self.objects:
            return (target_id,)
        return self.groups.get(target_id, ())


@dataclass(frozen=True, slots=True)
class ScheduledStep:
    """One primitive step with its place on the frame grid, written by P4.

    Still semantic: ``op`` is a :class:`~manorem_ir.SemanticOp`, not an animation.
    Choosing the animation is P7's job, and keeping that choice out of scheduling is
    what lets narration-anchored timing be checked without knowing what a ``flow``
    looks like.
    """

    target_id: str
    op: SemanticOp
    cue_id: str
    start_frame: int
    duration_frames: int
    easing: Easing = Easing.SMOOTH
    params: Mapping[str, ParamValue] = field(default_factory=dict)

    @property
    def end_frame(self) -> int:
        return self.start_frame + self.duration_frames


@dataclass(frozen=True, slots=True)
class CameraKey:
    """One camera move, on the frame grid but still in stage units.

    P5 decides where the camera goes; P6 converts to world units. Splitting it that
    way means the camera obeys the same aspect mapping as everything else instead of
    carrying its own.
    """

    start_frame: int
    duration_frames: int
    center: StagePoint
    #: Visible stage width. 2.0 frames the whole safe area.
    width: float
    easing: Easing = Easing.SMOOTH
    cue_id: str | None = None


@dataclass(frozen=True, slots=True)
class FrameMapping:
    """Stage space to Manim world units, for one aspect. Written by P6.

    A single uniform ``scale`` for both axes, because an anisotropic map would turn
    every circle into an ellipse in 9:16. Per-aspect fitting happens by choosing the
    scale from whichever axis binds, so the safe square always fits with margin and
    the wider axis simply has room to spare.
    """

    scale: float
    frame_width: float
    frame_height: float

    def point(self, p: StagePoint, z: float = 0.0) -> tuple[float, float, float]:
        return (p.x * self.scale, p.y * self.scale, z)

    def length(self, stage_length: float) -> float:
        return stage_length * self.scale

    def contains(self, box: StageBounds) -> bool:
        """Whether a stage box lands inside the visible frame."""
        half_w = self.frame_width / 2.0
        half_h = self.frame_height / 2.0
        return (
            box.min_x * self.scale >= -half_w
            and box.max_x * self.scale <= half_w
            and box.min_y * self.scale >= -half_h
            and box.max_y * self.scale <= half_h
        )


def _require[T](value: T | None, what: str, produced_by: str) -> T:
    if value is None:
        raise CompileError(f"{what} was requested before {produced_by} ran", diagnostics=[])
    return value


@dataclass(slots=True)
class SceneWork:
    """One scene's workspace, carried through every pass.

    Mutable on purpose. The IR models are frozen, so a pass that changes a scene
    replaces :attr:`scene` with a copy -- the mutation is visible at exactly one
    field rather than hidden in a returned tuple.

    :attr:`synthetic` deserves a note: objects P2 invents live here and *never* in
    ``scene.objects``. Keeping them out of the IR is what lets the autofix invariant
    ("the object id set is unchanged") stay checkable over a compiled corpus.
    """

    scene: Scene
    index: int
    #: JSON Pointer base for this scene, so every diagnostic points at the project.
    pointer: str
    skills: ResolvedSkills

    symbols_: SymbolTable | None = None
    timing_: ResolvedTiming | None = None
    frame_: FrameMapping | None = None
    plan_: ScenePlan | None = None

    #: Estimated stage extent per object, filled by P3 before solving.
    sizes: dict[str, StageSize] = field(default_factory=dict)
    #: Solved stage centres, filled by P3. Synthetic objects are absent.
    positions: dict[str, StagePoint] = field(default_factory=dict)
    #: Solved stage boxes, filled by P3 and read by the geometry lints and P8.
    bounds: dict[str, StageBounds] = field(default_factory=dict)
    #: Objects P2 invented: travelling packets, highlight rings, trail segments.
    synthetic: list[SyntheticObject] = field(default_factory=list)
    #: Per-target primitive steps, already on the frame grid. P2 writes them --
    #: quantizing each rule's fractional offset against its cue's resolved window --
    #: and P4 checks the result: clamps a start before zero, decides the scene's
    #: length, and reports anything that lands outside it.
    steps: list[ScheduledStep] = field(default_factory=list)
    camera_keys: list[CameraKey] = field(default_factory=list)
    #: Scene length in frames, decided by P4.
    duration_frames: int = 0

    @property
    def id(self) -> str:
        return self.scene.id

    @property
    def symbols(self) -> SymbolTable:
        return _require(self.symbols_, "symbol table", "P1 Resolve")

    @property
    def timing(self) -> ResolvedTiming:
        return _require(self.timing_, "resolved timing", "P1 Resolve")

    @property
    def frame(self) -> FrameMapping:
        return _require(self.frame_, "frame mapping", "P6 Frame")

    @property
    def plan(self) -> ScenePlan:
        return _require(self.plan_, "scene plan", "P7 Lower")

    @property
    def has_plan(self) -> bool:
        return self.plan_ is not None

    def ptr(self, *parts: str | int) -> str:
        """A pointer inside this scene, e.g. ``ptr("timeline", 3)``."""
        return f"{self.pointer}{pointer(*parts)}"

    def validation(self, ctx: CompileContext) -> ValidationContext:
        """This scene's validation context, from its own composed vocabulary.

        Per scene, not per project: ``Scene.skills`` is per scene, so one context for
        the whole compile would let a scene be validated against operations it never
        enabled. The driver and the geometry lints in P3 both go through here, which is
        what keeps "what this scene may use" a single answer.
        """
        return self.skills.validation_context(policy=ctx.options.policy, wpm=ctx.wpm, fps=ctx.fps)

    def synthetic_ids(self) -> frozenset[str]:
        return frozenset(obj.id for obj in self.synthetic)

    def steps_for(self, target_id: str) -> Iterator[ScheduledStep]:
        return (step for step in self.steps if step.target_id == target_id)


@dataclass(slots=True)
class CompileContext:
    """The whole compilation: the project, the options, every scene's workspace.

    Constructed by the driver, which resolves each scene's skills up front -- both
    because validation needs the composed vocabulary and because a pass asking a
    registry for it again could get a different answer.
    """

    project: Project
    options: CompileOptions
    format: FormatSpec
    scenes: list[SceneWork]
    bag: DiagnosticBag = field(default_factory=DiagnosticBag)
    #: Names of the passes that have run, in order. The driver's own record, and
    #: what a failure report shows to say how far the compile got.
    completed: list[str] = field(default_factory=list)

    @property
    def style(self) -> StyleTokens:
        return self.project.style

    @property
    def fps(self) -> int:
        return self.format.fps

    @property
    def wpm(self) -> float:
        return self.options.wpm if self.options.wpm is not None else self.project.narration_wpm

    def frames(self, seconds: float) -> int:
        """Quantize to the frame grid. The only place a duration becomes an integer."""
        return self.format.seconds_to_frames(seconds)

    def add(self, diagnostic: Diagnostic) -> None:
        self.bag.extend([diagnostic])

    @property
    def has_errors(self) -> bool:
        return self.bag.has_errors

    def errors(self) -> Sequence[Diagnostic]:
        return self.bag.errors

    def scene(self, scene_id: str) -> SceneWork | None:
        return next((work for work in self.scenes if work.id == scene_id), None)


class CompilerPass(Protocol):
    """One stage of lowering. Pure with respect to everything but the context."""

    @property
    def name(self) -> str:
        """Short label used in logs, timings and the ``completed`` record."""
        ...

    def run(self, ctx: CompileContext) -> None:
        """Advance the compile by one stage, appending diagnostics for defects."""
        ...
