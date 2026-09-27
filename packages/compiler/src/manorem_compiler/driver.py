"""The driver: Visual IR in, RenderPlan out, and a single rule for stopping.

This is the only place the nine passes are sequenced, and it is deliberately thin:
resolve each scene's skills, validate every scene against its own composed
vocabulary, then run :data:`~manorem_compiler.passes.PASSES` in order until a pass
leaves an error in the bag. Everything hard lives in the passes; the driver's whole
job is to decide *when to stop* and to keep a record of *how far it got*.

**Autofix runs first, and only on mechanically safe things.** When
``options.autofix`` is set, :func:`~manorem_compiler.autofix.autofix_project` pads and
normalizes ahead of validation. It never touches a semantic defect -- an unknown
reference or a missing object stays an error and reaches the caller (and, in the AI
pipeline, the bounded repair agent) untouched.

**Validation is per scene, not per project.** ``Scene.skills`` is per scene, so each
scene is checked against exactly the operations it enabled; a project-wide context
would let a scene pass against vocabulary it never opted into. The two genuinely
project-wide facts -- that there is at least one scene, and that scene ids do not
collide across episodes, since a scene id addresses a render job project-wide -- are
checked here directly.

**The halting rule is one statement.** A pass reports every fault it can see and
returns; the driver looks at severity. After each pass, if the bag holds an error,
the pipeline stops. Passes that did run are recorded in ``ctx.completed``, so a
failure report can say the compile reached P4 and stopped -- the plan is then whatever
was assembled from the scenes that got as far as P7, which is nothing when an earlier
pass halted the run.
"""

from __future__ import annotations

from manorem_compiler.autofix import autofix_project
from manorem_compiler.context import CompileContext, CompileOptions, SceneWork
from manorem_compiler.passes import PASSES
from manorem_compiler.plan import RenderPlan
from manorem_core import Code, DiagnosticBag, pointer
from manorem_ir import Project, validate_scene
from manorem_skills import default_registry

__all__ = ["compile_project"]


def _scene_works(project: Project) -> list[SceneWork]:
    """One workspace per scene, across every episode, with skills resolved once.

    The skill vocabulary is resolved here rather than inside a pass so that
    validation and the passes see the same answer -- a registry consulted twice
    could compose differently, and then a scene would be checked against one
    vocabulary and lowered against another.
    """
    registry = default_registry()
    works: list[SceneWork] = []
    index = 0
    for ep_index, episode in enumerate(project.episodes):
        for sc_index, scene in enumerate(episode.scenes):
            works.append(
                SceneWork(
                    scene=scene,
                    index=index,
                    pointer=pointer("episodes", ep_index, "scenes", sc_index),
                    skills=registry.resolve(scene.skills),
                )
            )
            index += 1
    return works


def _check_project_shape(project: Project, bag: DiagnosticBag) -> None:
    """The two structural facts no single scene can see on its own."""
    if not any(episode.scenes for episode in project.episodes):
        bag.add(
            Code.IR106_NO_SCENES,
            "project has no scenes to compile",
            pointer=pointer("episodes"),
            hint="A project needs at least one episode containing at least one scene.",
        )
    seen: set[str] = set()
    for ep_index, episode in enumerate(project.episodes):
        for sc_index, scene in enumerate(episode.scenes):
            if scene.id in seen:
                bag.add(
                    Code.IR102_DUPLICATE_ID,
                    f"duplicate scene id {scene.id!r}",
                    pointer=pointer("episodes", ep_index, "scenes", sc_index),
                    object_id=scene.id,
                    hint="Scene ids address render jobs project-wide and must be unique.",
                )
            seen.add(scene.id)


def compile_project(
    project: Project, options: CompileOptions | None = None
) -> tuple[RenderPlan, DiagnosticBag]:
    """Compile a Visual IR project to a RenderPlan, collecting every diagnostic.

    The returned plan is meaningful only when the bag holds no error; on failure it
    carries whatever scenes reached P7 before the halt, which the caller should treat
    as diagnostic context, not output.
    """
    options = options or CompileOptions()
    if options.autofix:
        project = autofix_project(project).project
    fmt = options.format_for(project)

    ctx = CompileContext(
        project=project,
        options=options,
        format=fmt,
        scenes=_scene_works(project),
    )

    _check_project_shape(project, ctx.bag)
    for work in ctx.scenes:
        ctx.bag.extend(validate_scene(work.scene, ctx=work.validation(ctx), base=work.pointer))

    if not ctx.has_errors:
        for compiler_pass in PASSES:
            compiler_pass.run(ctx)
            ctx.completed.append(compiler_pass.name)
            if ctx.has_errors:
                break

    plan = RenderPlan(
        project_id=project.id,
        format=fmt,
        style=project.style,
        scenes=tuple(work.plan for work in ctx.scenes if work.has_plan),
    )
    return plan, ctx.bag
