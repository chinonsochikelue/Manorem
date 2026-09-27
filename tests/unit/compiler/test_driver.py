"""The compiler driver: what compiles, what halts, and what never reaches a plan.

The driver is the whole contract in miniature -- autofix, per-scene validation,
project-shape checks, the pass pipeline, and RenderPlan assembly -- so these tests
assert the two things a driver must guarantee. A well-formed project produces a
plan whose shape matches its FormatSpec; a semantically damaged one produces
errors and **no scene plan at all**, because a plan missing a satellite is worse
than a compile that stopped.
"""

from __future__ import annotations

import pytest

from manorem_compiler import CompileOptions, compile_project
from manorem_core import Code
from manorem_ir import Aspect, Project
from tests.support.diag import error_codes, only
from tests.support.ir_builders import (
    episode,
    make_project,
    scene_with,
    show,
    valid_project,
    valid_scene,
)


def test_valid_project_compiles_to_one_scene_plan() -> None:
    plan, bag = compile_project(valid_project())
    assert error_codes(bag) == set()
    assert len(plan.scenes) == 1
    scene = plan.scenes[0]
    assert scene.id == "intro"
    assert scene.duration_frames == 57
    assert len(scene.mobjects) == 2
    assert len(scene.tracks) == 2
    assert plan.total_frames == 57
    assert plan.fps == 15


@pytest.mark.parametrize(
    ("aspect", "width", "height"),
    [
        (Aspect.WIDESCREEN, 854, 480),
        (Aspect.VERTICAL, 480, 854),
        (Aspect.SQUARE, 480, 480),
    ],
)
def test_aspect_override_sets_frame_dimensions(aspect: Aspect, width: int, height: int) -> None:
    plan, bag = compile_project(valid_project(), CompileOptions(aspect=aspect, quality="draft"))
    assert error_codes(bag) == set()
    assert plan.aspect is aspect
    assert (plan.format.width, plan.format.height) == (width, height)
    # Frame count is aspect-independent: only the mapping to world units changes.
    assert plan.total_frames == 57


def test_compile_is_deterministic() -> None:
    first, _ = compile_project(valid_project(), CompileOptions(aspect=Aspect.WIDESCREEN))
    second, _ = compile_project(valid_project(), CompileOptions(aspect=Aspect.WIDESCREEN))
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_unknown_object_ref_halts_before_any_plan() -> None:
    """A cue targeting an object that does not exist is a hard error, not a drop.

    The scene is otherwise valid; the only damage is a cue pointing at ``ghost``.
    The driver must surface it and emit no scene plan -- never a plan with the
    dangling cue silently removed.
    """
    broken = scene_with(timeline=[show("boot", ["title"]), show("ghost_show", ["ghost"])])
    plan, bag = compile_project(make_project(broken))
    diag = only(bag, Code.IR201_UNKNOWN_OBJECT_REF)
    assert diag.object_id == "ghost"
    assert plan.scenes == ()


def test_project_with_no_scenes_reports_ir106() -> None:
    empty = Project(id="p", title="t", episodes=[episode("e1")])
    plan, bag = compile_project(empty)
    only(bag, Code.IR106_NO_SCENES)
    assert plan.scenes == ()


def test_scene_id_reused_across_episodes_reports_ir102() -> None:
    """Scene ids must be unique project-wide, which per-scene validation cannot see."""
    reused = Project(
        id="p",
        title="t",
        episodes=[episode("e1", valid_scene()), episode("e2", scene_with())],
    )
    plan, bag = compile_project(reused)
    only(bag, Code.IR102_DUPLICATE_ID)
    assert plan.scenes == ()
