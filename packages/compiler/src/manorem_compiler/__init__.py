"""The compiler: Visual IR in, RenderPlan out, nothing else in between.

One entry point, :func:`~manorem_compiler.driver.compile_project`, runs nine passes in
a fixed order over a shared :class:`~manorem_compiler.context.CompileContext`. Each
pass is a pure function of the IR and the options, which is what makes the compiler's
output snapshot-testable and what makes the whole 16:9 / 9:16 / 1:1 contract testable
without rendering a single frame.

Everything a caller needs is re-exported here, so a downstream package imports from
``manorem_compiler`` and never from a pass module -- the pass layout is free to change
without breaking the renderer or the CLI.
"""

from __future__ import annotations

from manorem_compiler.autofix import AutofixResult, autofix_project
from manorem_compiler.context import (
    CameraKey,
    CompileContext,
    CompileOptions,
    CompilerPass,
    FrameMapping,
    SceneWork,
    ScheduledStep,
    SymbolTable,
)
from manorem_compiler.driver import compile_project
from manorem_compiler.layout import (
    BUILTIN_SOLVERS,
    DEGRADED_KINDS,
    GRID_EPS,
    estimate_size,
    estimate_sizes,
    quantize,
    slot_regions,
    solver_for,
)
from manorem_compiler.lower import anim_for, build_scene_plan, lower_mobjects
from manorem_compiler.passes import PASSES, Pass
from manorem_compiler.plan import (
    CAMERA_TRACK_ID,
    PLAN_VERSION,
    AudioCue,
    MobjectSpec,
    PlanAnim,
    PlanBounds,
    PlanEvent,
    PlanValue,
    Point3,
    Primitive,
    RenderPlan,
    ScenePlan,
    Track,
)

__all__ = [
    "BUILTIN_SOLVERS",
    "CAMERA_TRACK_ID",
    "DEGRADED_KINDS",
    "GRID_EPS",
    "PASSES",
    "PLAN_VERSION",
    "AudioCue",
    "AutofixResult",
    "CameraKey",
    "CompileContext",
    "CompileOptions",
    "CompilerPass",
    "FrameMapping",
    "MobjectSpec",
    "Pass",
    "PlanAnim",
    "PlanBounds",
    "PlanEvent",
    "PlanValue",
    "Point3",
    "Primitive",
    "RenderPlan",
    "ScenePlan",
    "SceneWork",
    "ScheduledStep",
    "SymbolTable",
    "Track",
    "anim_for",
    "autofix_project",
    "build_scene_plan",
    "compile_project",
    "estimate_size",
    "estimate_sizes",
    "lower_mobjects",
    "quantize",
    "slot_regions",
    "solver_for",
]
