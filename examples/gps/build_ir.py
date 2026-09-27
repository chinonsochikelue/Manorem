"""Generate ``examples/gps/ir.json`` -- the hand-authored GPS explainer.

This is the reference Visual IR for Slice 1: nine scenes that walk through how a
phone locates itself, authored entirely in the semantic vocabulary. It names no
Manim class, carries no world coordinate, and states timing relative to narration
and to other cues -- the compiler owns every absolute number.

Run it (``python examples/gps/build_ir.py``) to regenerate the committed JSON
after an IR schema change. The JSON is the artifact the CLI renders; this script
is how it stays readable and re-derivable rather than edited by hand.

Stage space is ``[-1, 1]`` on both axes. A few objects use explicit ``Stage``
placement: the trilateration geometry only reads correctly when the distance
circles actually meet over the phone, and that is a genuine hand-tuned intent, not
something to defer to a layout solver.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Literal

from manorem_ir import (
    AUTO,
    CircleProps,
    Cue,
    DotProps,
    DurationExpr,
    Episode,
    FormatSpec,
    NarrationSegment,
    ObjectKind,
    ParamValue,
    Project,
    RelationKind,
    Relationship,
    Scene,
    SceneObject,
    SemanticOp,
    StagePlacement,
    StagePoint,
    TextProps,
    TimeExpr,
    after,
    at_narration,
    at_seconds,
    lasting,
    with_cue,
)
from manorem_ir.enums import Aspect, NarrationRole

# --- object helpers --------------------------------------------------------

#: Where each satellite sits in stage space, and the phone they all range to.
_PHONE_AT = StagePoint(x=0.0, y=-0.15)
_SATS_AT: dict[str, StagePoint] = {
    "sat_1": StagePoint(x=-0.62, y=0.6),
    "sat_2": StagePoint(x=0.66, y=0.55),
    "sat_3": StagePoint(x=0.1, y=-0.78),
    "sat_4": StagePoint(x=0.8, y=-0.05),
}


def _at(point: StagePoint) -> StagePlacement:
    return StagePlacement(point=point)


def _phone(placement: StagePlacement | None = None) -> SceneObject:
    return SceneObject(
        id="phone",
        kind=ObjectKind.DOT,
        props=DotProps(radius=0.05),
        label="Your phone",
        placement=placement or _at(_PHONE_AT),
    )


def _sat(sat_id: str) -> SceneObject:
    return SceneObject(
        id=sat_id,
        kind=ObjectKind.DOT,
        props=DotProps(radius=0.04),
        label=sat_id.replace("_", " ").title(),
        placement=_at(_SATS_AT[sat_id]),
    )


def _range_circle(sat_id: str, circle_id: str) -> SceneObject:
    """A distance circle: centred on a satellite, its radius the stage distance to
    the phone, so three of them cross exactly where the phone stands."""
    centre = _SATS_AT[sat_id]
    radius = math.hypot(centre.x - _PHONE_AT.x, centre.y - _PHONE_AT.y)
    return SceneObject(
        id=circle_id,
        kind=ObjectKind.CIRCLE,
        props=CircleProps(radius=round(radius, 4), filled=False),
        placement=_at(centre),
    )


def _text(
    text_id: str,
    content: str,
    role: Literal["title", "heading", "body", "caption"] = "body",
    *,
    y: float = 0.75,
) -> SceneObject:
    return SceneObject(
        id=text_id,
        kind=ObjectKind.TEXT,
        props=TextProps(content=content, role=role),
        placement=_at(StagePoint(x=0.0, y=y)),
    )


def _seg(
    seg_id: str,
    text: str,
    role: NarrationRole = NarrationRole.CONTEXT,
    mentions: list[str] | None = None,
) -> NarrationSegment:
    return NarrationSegment(id=seg_id, role=role, text=text, mentions=mentions or [])


def _connected(*sat_ids: str) -> list[Relationship]:
    """A ``connected_to`` link from each satellite to the phone, so a ``flow``
    along it satisfies the ``networks`` skill's IR209 constraint."""
    return [
        Relationship(kind=RelationKind.CONNECTED_TO, source=sat_id, target="phone")
        for sat_id in sat_ids
    ]


# --- cue helper ------------------------------------------------------------


def _cue(
    cue_id: str,
    op: SemanticOp,
    targets: list[str],
    *,
    at: TimeExpr | None = None,
    duration: DurationExpr | None = None,
    why: str | None = None,
    **params: ParamValue,
) -> Cue:
    return Cue(
        id=cue_id,
        op=op,
        targets=targets,
        at=at if at is not None else at_seconds(0.0),
        duration=duration if duration is not None else AUTO,
        why=why,
        params=dict(params),
    )


# --- scenes ----------------------------------------------------------------


def _scene_1_phone_asks() -> Scene:
    return Scene(
        id="phone_asks",
        name="The question",
        intent="Open on the everyday magic: the phone knows where you are.",
        objects=[_text("title", "Where am I?", role="title"), _phone()],
        narration=[
            _seg(
                "hook", "Your phone always seems to know exactly where you are.", NarrationRole.HOOK
            ),
            _seg(
                "ask",
                "But how does it work out that little blue dot?",
                NarrationRole.QUESTION,
                ["phone"],
            ),
        ],
        timeline=[
            _cue(
                "show_title",
                SemanticOp.SHOW,
                ["title"],
                at=at_narration("hook"),
                duration=lasting(1.2),
            ),
            _cue(
                "show_phone",
                SemanticOp.SHOW,
                ["phone"],
                at=after("show_title", 0.2),
                duration=lasting(1.0),
            ),
            _cue(
                "ask_phone",
                SemanticOp.HIGHLIGHT,
                ["phone"],
                at=at_narration("ask"),
                duration=lasting(1.0),
            ),
        ],
    )


def _scene_2_satellites_revealed() -> Scene:
    sats = ["sat_1", "sat_2", "sat_3", "sat_4"]
    return Scene(
        id="satellites_revealed",
        name="The satellites",
        intent="Reveal the constellation overhead that makes it possible.",
        objects=[_phone(), *[_sat(s) for s in sats]],
        narration=[
            _seg(
                "orbit",
                "High above you, a fleet of GPS satellites circles the Earth.",
                NarrationRole.CONTEXT,
            ),
            _seg(
                "inview",
                "At any moment, several of them are in view of your phone.",
                NarrationRole.CONTEXT,
                ["sat_1"],
            ),
        ],
        timeline=[
            _cue(
                "show_phone",
                SemanticOp.SHOW,
                ["phone"],
                at=at_narration("orbit"),
                duration=lasting(0.8),
            ),
            _cue(
                "show_sats",
                SemanticOp.SHOW,
                sats,
                at=after("show_phone", 0.2),
                duration=lasting(1.2),
            ),
            _cue(
                "blink_sats",
                SemanticOp.HIGHLIGHT,
                sats,
                at=at_narration("inview"),
                duration=lasting(1.0),
            ),
        ],
    )


def _scene_3_signals_arrive() -> Scene:
    sats = ["sat_1", "sat_2", "sat_3"]
    return Scene(
        id="signals_arrive",
        name="The signals",
        intent="Each satellite broadcasts; the signals race down to the phone.",
        skills=["core", "networks"],
        objects=[_phone(), *[_sat(s) for s in sats]],
        relationships=_connected(*sats),
        narration=[
            _seg("broadcast", "Each satellite constantly broadcasts the time and its position."),
            _seg(
                "race",
                "Those signals race down to your phone at the speed of light.",
                mentions=["phone"],
            ),
        ],
        timeline=[
            _cue(
                "show_phone", SemanticOp.SHOW, ["phone"], at=at_seconds(0.0), duration=lasting(0.6)
            ),
            _cue(
                "show_sats",
                SemanticOp.SHOW,
                sats,
                at=after("show_phone", 0.1),
                duration=lasting(0.8),
            ),
            _cue(
                "flow_1",
                SemanticOp.FLOW,
                ["sat_1", "phone"],
                at=at_narration("race"),
                duration=lasting(1.2),
            ),
            _cue(
                "flow_2",
                SemanticOp.FLOW,
                ["sat_2", "phone"],
                at=with_cue("flow_1", 0.15),
                duration=lasting(1.2),
            ),
            _cue(
                "flow_3",
                SemanticOp.FLOW,
                ["sat_3", "phone"],
                at=with_cue("flow_1", 0.3),
                duration=lasting(1.2),
            ),
        ],
    )


def _scene_4_one_radius() -> Scene:
    return Scene(
        id="one_radius",
        name="One distance",
        intent="Travel time becomes a distance -- a whole circle of possible spots.",
        objects=[_sat("sat_1"), _phone(), _range_circle("sat_1", "circle_1")],
        narration=[
            _seg("timing", "The signal's travel time tells the phone how far that satellite is."),
            _seg(
                "circle",
                "That one distance places you somewhere on a circle around it.",
                mentions=["circle_1"],
            ),
        ],
        timeline=[
            _cue("show_sat", SemanticOp.SHOW, ["sat_1"], at=at_seconds(0.0), duration=lasting(0.6)),
            _cue(
                "show_phone",
                SemanticOp.SHOW,
                ["phone"],
                at=after("show_sat", 0.1),
                duration=lasting(0.6),
            ),
            _cue(
                "draw_circle",
                SemanticOp.SHOW,
                ["circle_1"],
                at=at_narration("circle"),
                duration=lasting(1.2),
                style="draw",
            ),
            _cue(
                "pulse_circle",
                SemanticOp.HIGHLIGHT,
                ["circle_1"],
                at=after("draw_circle"),
                duration=lasting(0.8),
            ),
        ],
    )


def _scene_5_two_radii() -> Scene:
    sats = ["sat_1", "sat_2"]
    circles = ["circle_1", "circle_2"]
    return Scene(
        id="two_radii",
        name="Two distances",
        intent="A second circle cuts the possibilities down to two crossing points.",
        objects=[
            _phone(),
            *[_sat(s) for s in sats],
            _range_circle("sat_1", "circle_1"),
            _range_circle("sat_2", "circle_2"),
        ],
        narration=[
            _seg("second", "Add a second satellite, and you get a second circle."),
            _seg("cross", "You must be standing where the two circles cross.", mentions=["phone"]),
        ],
        timeline=[
            _cue("show_sats", SemanticOp.SHOW, sats, at=at_seconds(0.0), duration=lasting(0.8)),
            _cue(
                "show_phone",
                SemanticOp.SHOW,
                ["phone"],
                at=after("show_sats", 0.1),
                duration=lasting(0.5),
            ),
            _cue(
                "draw_circles",
                SemanticOp.SHOW,
                circles,
                at=after("show_phone", 0.1),
                duration=lasting(1.2),
                style="draw",
            ),
            _cue(
                "mark_cross",
                SemanticOp.HIGHLIGHT,
                ["phone"],
                at=at_narration("cross"),
                duration=lasting(0.8),
            ),
        ],
    )


def _scene_6_three_radii() -> Scene:
    sats = ["sat_1", "sat_2", "sat_3"]
    circles = ["circle_1", "circle_2", "circle_3"]
    return Scene(
        id="three_radii",
        name="Three distances",
        intent="A third circle pins the location to a single point.",
        objects=[
            _phone(),
            *[_sat(s) for s in sats],
            _range_circle("sat_1", "circle_1"),
            _range_circle("sat_2", "circle_2"),
            _range_circle("sat_3", "circle_3"),
        ],
        narration=[
            _seg("third", "A third satellite adds a third circle."),
            _seg(
                "point",
                "All three meet at exactly one point -- and that point is you.",
                mentions=["phone"],
            ),
        ],
        timeline=[
            _cue("show_sats", SemanticOp.SHOW, sats, at=at_seconds(0.0), duration=lasting(0.8)),
            _cue(
                "show_phone",
                SemanticOp.SHOW,
                ["phone"],
                at=after("show_sats", 0.1),
                duration=lasting(0.5),
            ),
            _cue(
                "draw_circles",
                SemanticOp.SHOW,
                circles,
                at=after("show_phone", 0.1),
                duration=lasting(1.4),
                style="draw",
            ),
            _cue(
                "mark_point",
                SemanticOp.HIGHLIGHT,
                ["phone"],
                at=at_narration("point"),
                duration=lasting(1.0),
            ),
        ],
    )


def _scene_7_intersection() -> Scene:
    circles = ["circle_1", "circle_2", "circle_3"]
    return Scene(
        id="intersection",
        name="The fix",
        intent="Zoom in on the meeting point the three distances agree on.",
        objects=[
            _phone(),
            _range_circle("sat_1", "circle_1"),
            _range_circle("sat_2", "circle_2"),
            _range_circle("sat_3", "circle_3"),
        ],
        narration=[
            _seg("agree", "The one place all three distances agree on is your location."),
            _seg("zoom", "The phone settles on where the math meets.", mentions=["phone"]),
        ],
        timeline=[
            _cue(
                "show_circles",
                SemanticOp.SHOW,
                circles,
                at=at_seconds(0.0),
                duration=lasting(1.0),
                style="draw",
            ),
            _cue(
                "show_phone",
                SemanticOp.SHOW,
                ["phone"],
                at=after("show_circles", 0.1),
                duration=lasting(0.6),
            ),
            _cue(
                "focus_phone",
                SemanticOp.FOCUS,
                ["phone"],
                at=at_narration("zoom"),
                duration=lasting(1.5),
                padding=0.4,
            ),
            _cue(
                "pulse_phone",
                SemanticOp.HIGHLIGHT,
                ["phone"],
                at=after("focus_phone"),
                duration=lasting(0.8),
            ),
        ],
    )


def _scene_8_timing_error() -> Scene:
    return Scene(
        id="timing_error",
        name="The catch",
        intent="It all hinges on the clock: a tiny timing error is a huge distance error.",
        objects=[
            _text("formula", "distance = speed x time", role="heading"),
            _sat("sat_1"),
            _phone(),
            _range_circle("sat_1", "circle_1"),
        ],
        narration=[
            _seg("clock", "But the whole trick rests on impeccably accurate clocks."),
            _seg(
                "error",
                "A billionth of a second off, and the distance is wrong by metres.",
                mentions=["formula"],
            ),
        ],
        timeline=[
            _cue(
                "show_formula",
                SemanticOp.SHOW,
                ["formula"],
                at=at_narration("clock"),
                duration=lasting(1.0),
                style="write",
            ),
            _cue(
                "show_sat",
                SemanticOp.SHOW,
                ["sat_1"],
                at=after("show_formula", 0.1),
                duration=lasting(0.5),
            ),
            _cue(
                "show_phone",
                SemanticOp.SHOW,
                ["phone"],
                at=after("show_sat", 0.1),
                duration=lasting(0.5),
            ),
            _cue(
                "show_circle",
                SemanticOp.SHOW,
                ["circle_1"],
                at=after("show_phone", 0.1),
                duration=lasting(0.8),
                style="draw",
            ),
            _cue(
                "wobble",
                SemanticOp.HIGHLIGHT,
                ["circle_1"],
                at=at_narration("error"),
                duration=lasting(1.0),
                style="flash",
            ),
        ],
    )


def _scene_9_pull_back() -> Scene:
    sats = ["sat_1", "sat_2", "sat_3", "sat_4"]
    return Scene(
        id="pull_back",
        name="The fourth",
        intent="A fourth satellite solves the clock too; pull back on the finished fix.",
        objects=[
            _phone(),
            *[_sat(s) for s in sats],
            _text("closing", "Four satellites. One point.", role="heading", y=-0.85),
        ],
        narration=[
            _seg("fourth", "So a fourth satellite is added to solve for the clock as well."),
            _seg(
                "closing",
                "Four numbers, one point -- and your phone knows exactly where you are.",
                NarrationRole.CONCLUSION,
                ["phone"],
            ),
        ],
        timeline=[
            _cue(
                "show_phone", SemanticOp.SHOW, ["phone"], at=at_seconds(0.0), duration=lasting(0.5)
            ),
            _cue(
                "show_sats",
                SemanticOp.SHOW,
                sats,
                at=after("show_phone", 0.1),
                duration=lasting(1.0),
            ),
            _cue(
                "show_closing",
                SemanticOp.SHOW,
                ["closing"],
                at=after("show_sats", 0.2),
                duration=lasting(1.0),
                style="write",
            ),
            _cue(
                "pull_back",
                SemanticOp.ZOOM_TO,
                sats,
                at=at_narration("closing"),
                duration=lasting(1.5),
                padding=0.3,
            ),
        ],
    )


# --- assembly --------------------------------------------------------------


def build_project() -> Project:
    """Assemble the nine scenes into the GPS explainer project."""
    scenes = [
        _scene_1_phone_asks(),
        _scene_2_satellites_revealed(),
        _scene_3_signals_arrive(),
        _scene_4_one_radius(),
        _scene_5_two_radii(),
        _scene_6_three_radii(),
        _scene_7_intersection(),
        _scene_8_timing_error(),
        _scene_9_pull_back(),
    ]
    return Project(
        id="gps",
        title="How GPS Determines Your Location",
        idea="How GPS determines your location.",
        format=FormatSpec.for_quality(Aspect.WIDESCREEN, "draft"),
        episodes=[Episode(id="main", title="How GPS Determines Your Location", scenes=scenes)],
    )


def main() -> None:
    project = build_project()
    out = Path(__file__).with_name("ir.json")
    out.write_text(project.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out} ({project.scene_count} scenes)")


if __name__ == "__main__":
    main()
