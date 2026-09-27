"""Plan invariants: what P8 guarantees, asserted on the plan itself.

P8 verifies these and refuses to emit a plan that breaks them, so a compile that
returns a plan with zero errors should already satisfy them. These tests check the
plan *directly* anyway -- if a future pass regresses and P8's guard is what should
have caught it, the failure should read as "the plan is wrong", not "some error
code appeared". The corpus is deliberately small and varied (a default centered
scene, a horizontal row, a networks scene that synthesizes a link) and every member
is run through all three aspects, since the frame mapping is the only thing that
changes between them.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from manorem_compiler import CompileOptions, compile_project
from manorem_compiler.plan import RenderPlan
from manorem_ir import (
    Aspect,
    LayoutKind,
    LayoutSpec,
    RelationKind,
    Scene,
    SemanticOp,
)
from tests.support.diag import error_codes
from tests.support.ir_builders import (
    cue,
    dot_obj,
    make_project,
    make_scene,
    relationship,
    segment,
    show,
    text_obj,
    valid_scene,
)

_MANIM_FRAME_HEIGHT = 8.0


def _centered_scene() -> Scene:
    return valid_scene()


def _horizontal_scene() -> Scene:
    return make_scene(
        "row",
        intent="Three items across.",
        objects=[text_obj("a"), text_obj("b"), text_obj("c")],
        layout=LayoutSpec(kind=LayoutKind.HORIZONTAL),
        narration=[segment("n", "A single line.")],
        timeline=[show("s1", ["a"]), show("s2", ["b"]), show("s3", ["c"])],
    )


def _networks_scene() -> Scene:
    return make_scene(
        "net",
        intent="Two nodes, connected.",
        skills=["networks"],
        objects=[dot_obj("x"), dot_obj("y")],
        relationships=[relationship(RelationKind.CONNECTED_TO, "x", "y")],
        narration=[segment("n", "A single line.")],
        timeline=[
            show("s1", ["x"]),
            show("s2", ["y"]),
            cue("c1", SemanticOp.CONNECT, ["x", "y"]),
        ],
    )


_CORPUS = [_centered_scene, _horizontal_scene, _networks_scene]
_ASPECTS = [Aspect.WIDESCREEN, Aspect.VERTICAL, Aspect.SQUARE]
_CASES = [(scene.__name__, scene, aspect) for scene in _CORPUS for aspect in _ASPECTS]
_IDS = [f"{name}-{aspect.value}" for name, _, aspect in _CASES]


def _plan(scene_factory: Callable[[], Scene], aspect: Aspect) -> RenderPlan:
    plan, bag = compile_project(make_project(scene_factory()), CompileOptions(aspect=aspect))
    assert error_codes(bag) == set(), f"{scene_factory.__name__} {aspect.value}: {error_codes(bag)}"
    return plan


def _floats(value: Any) -> Iterator[float]:
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        yield float(value)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _floats(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _floats(item)


@pytest.mark.parametrize(("name", "scene", "aspect"), _CASES, ids=_IDS)
def test_plan_has_no_non_finite_values(
    name: str, scene: Callable[[], Scene], aspect: Aspect
) -> None:
    plan = _plan(scene, aspect)
    for number in _floats(plan.model_dump(mode="json")):
        assert math.isfinite(number)


@pytest.mark.parametrize(("name", "scene", "aspect"), _CASES, ids=_IDS)
def test_no_event_runs_past_its_scene_end(
    name: str, scene: Callable[[], Scene], aspect: Aspect
) -> None:
    plan = _plan(scene, aspect)
    for scene_plan in plan.scenes:
        assert scene_plan.duration_frames >= 1
        for track in (*scene_plan.tracks, scene_plan.camera):
            for event in track.events:
                assert event.duration_frames >= 1
                assert event.end_frame <= scene_plan.duration_frames


@pytest.mark.parametrize(("name", "scene", "aspect"), _CASES, ids=_IDS)
def test_every_mobject_stays_inside_the_frame(
    name: str, scene: Callable[[], Scene], aspect: Aspect
) -> None:
    plan = _plan(scene, aspect)
    half_w = _MANIM_FRAME_HEIGHT * aspect.ratio / 2.0
    half_h = _MANIM_FRAME_HEIGHT / 2.0
    for scene_plan in plan.scenes:
        for mobject in scene_plan.mobjects:
            bounds = mobject.bounds
            assert -half_w <= bounds.min_x and bounds.max_x <= half_w
            assert -half_h <= bounds.min_y and bounds.max_y <= half_h
