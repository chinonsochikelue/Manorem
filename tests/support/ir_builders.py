"""Builders for IR fixtures used across the test suite.

A valid scene is one where objects, narration and timeline all agree with each
other, which is a lot of setup to restate in every test. These helpers supply the
agreeing parts so a test body shows only its own deviation from valid -- and so
:func:`valid_scene` can serve as the "zero diagnostics" baseline that keeps the
validator honest about false positives.
"""

from __future__ import annotations

from typing import Any

from manorem_ir import (
    AUTO,
    ArrowProps,
    CircleProps,
    Cue,
    DotProps,
    DurationExpr,
    Episode,
    Group,
    GroupProps,
    MathProps,
    NarrationSegment,
    ObjectKind,
    ParamValue,
    Project,
    RelationKind,
    Relationship,
    Scene,
    SceneObject,
    SemanticOp,
    TextProps,
    TimeExpr,
    after,
    at_seconds,
    lasting,
)

# --- objects ---------------------------------------------------------------


def text_obj(object_id: str, content: str = "Hello", **kwargs: Any) -> SceneObject:
    return SceneObject(
        id=object_id, kind=ObjectKind.TEXT, props=TextProps(content=content), **kwargs
    )


def math_obj(object_id: str, latex: str = r"c = 299792458", **kwargs: Any) -> SceneObject:
    return SceneObject(id=object_id, kind=ObjectKind.MATH, props=MathProps(latex=latex), **kwargs)


def dot_obj(object_id: str, **kwargs: Any) -> SceneObject:
    return SceneObject(id=object_id, kind=ObjectKind.DOT, props=DotProps(), **kwargs)


def circle_obj(object_id: str, radius: float = 0.3, **kwargs: Any) -> SceneObject:
    return SceneObject(
        id=object_id, kind=ObjectKind.CIRCLE, props=CircleProps(radius=radius), **kwargs
    )


def group_obj(object_id: str, members: list[str], **kwargs: Any) -> SceneObject:
    return SceneObject(
        id=object_id, kind=ObjectKind.GROUP, props=GroupProps(members=members), **kwargs
    )


def arrow_obj(object_id: str, start: str, end: str, **kwargs: Any) -> SceneObject:
    return SceneObject(
        id=object_id,
        kind=ObjectKind.ARROW,
        props=ArrowProps(start=start, end=end),
        **kwargs,
    )


# --- structure -------------------------------------------------------------


def group(group_id: str, members: list[str], **kwargs: Any) -> Group:
    """A structural group -- the sibling namespace to objects, not an object."""
    return Group(id=group_id, members=members, **kwargs)


def relationship(kind: RelationKind, source: str, target: str, **kwargs: Any) -> Relationship:
    return Relationship(kind=kind, source=source, target=target, **kwargs)


# --- cues and narration ----------------------------------------------------


def cue(
    cue_id: str,
    op: SemanticOp,
    targets: list[str],
    *,
    at: TimeExpr | None = None,
    duration: DurationExpr | None = None,
    **params: ParamValue,
) -> Cue:
    return Cue(
        id=cue_id,
        op=op,
        targets=targets,
        at=at if at is not None else at_seconds(0.0),
        duration=duration if duration is not None else AUTO,
        params=dict(params),
    )


def show(
    cue_id: str,
    targets: list[str],
    *,
    at: TimeExpr | None = None,
    duration: DurationExpr | None = None,
) -> Cue:
    return cue(cue_id, SemanticOp.SHOW, targets, at=at, duration=duration)


def segment(segment_id: str, text: str = "A single short line.", **kwargs: Any) -> NarrationSegment:
    return NarrationSegment(id=segment_id, text=text, **kwargs)


# --- scenes and projects ---------------------------------------------------


def make_scene(scene_id: str = "intro", **kwargs: Any) -> Scene:
    fields: dict[str, Any] = {"name": "Intro"}
    fields.update(kwargs)
    return Scene(id=scene_id, **fields)


def episode(episode_id: str, *scenes: Scene, **kwargs: Any) -> Episode:
    fields: dict[str, Any] = {"title": episode_id.replace("_", " ").title()}
    fields.update(kwargs)
    return Episode(id=episode_id, scenes=list(scenes), **fields)


def make_project(*scenes: Scene, **kwargs: Any) -> Project:
    fields: dict[str, Any] = {
        "title": "Test project",
        "episodes": [Episode(id="main", title="Main", scenes=list(scenes))],
    }
    fields.update(kwargs)
    return Project(id="test_project", **fields)


def valid_scene() -> Scene:
    """A scene that must validate with **zero** diagnostics, at any tier.

    Deliberately ordinary: a title appears, a subject appears, the subject is
    highlighted while the narration talks about it. If a new check starts firing
    on this, the check is wrong -- not the fixture.
    """
    return make_scene(
        intent="Establish the question the video answers.",
        objects=[text_obj("title", "Where am I?"), dot_obj("phone")],
        narration=[
            segment("line_one", "Where are you right now?"),
            segment("line_two", "Your phone knows.", mentions=["phone"]),
        ],
        timeline=[
            show("show_title", ["title"], duration=lasting(1.0)),
            show("show_phone", ["phone"], at=after("show_title", 0.2), duration=lasting(1.0)),
            cue(
                "pulse_phone",
                SemanticOp.HIGHLIGHT,
                ["phone"],
                at=after("show_phone"),
                duration=lasting(1.0),
            ),
        ],
    )


def valid_project() -> Project:
    return make_project(valid_scene())


def scene_with(**updates: Any) -> Scene:
    """:func:`valid_scene` with fields replaced.

    The test body then contains exactly one thing: the damage it is about. Field
    values are validated when constructed, but the replacement itself is not
    re-validated -- which is the point, since these tests exercise the checks
    that run *after* parsing.
    """
    return valid_scene().model_copy(update=updates)
