"""Serialization fidelity: the IR has to survive being written down.

The IR is not an in-process data structure that happens to be Pydantic. It is a
*persisted artifact* -- the AI emits JSON, a human edits JSON, the pipeline stores
JSON keyed by its own hash, and the repair agent patches JSON at a pointer. So
"the models parse" is not the property that matters. These are:

* **round-tripping loses nothing** -- not the discriminated union arms, not the
  timing expressions, not the placement modes. A dropped field is an edit that
  silently reverts;
* **the digest is a function of meaning, not of layout** -- key order and
  whitespace must not change it, or content addressing stops deduplicating and
  every unchanged scene re-renders;
* **absent stays distinguishable from defaulted** where the difference is a
  claim: ``duration_hint=None`` means "as long as the content needs", and a
  missing ``start`` means "not yet measured against real audio".

Together these are what make a committed RenderPlan golden a usable regression
gate and per-scene render caching correct rather than merely fast.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from manorem_core import canonical_json, sha256_of
from manorem_ir import (
    AUTO,
    CUT,
    IR_VERSION,
    AnchorPlacement,
    ArrowProps,
    Aspect,
    AudioClip,
    AudioTimeline,
    AxesProps,
    CameraSpec,
    CameraState,
    ChartProps,
    ChartSeries,
    CircleProps,
    Cue,
    DiagramProps,
    DotProps,
    Episode,
    FormatSpec,
    GlobeProps,
    GraphEdge,
    GraphNode,
    GraphProps,
    GroupProps,
    IconProps,
    ImageProps,
    LayoutKind,
    LayoutSlot,
    LayoutSpec,
    LineProps,
    MapProps,
    MathProps,
    NarrationRole,
    NetworkProps,
    ObjectKind,
    ObjectProps,
    ParticlesProps,
    Placement,
    PolygonProps,
    Project,
    RectangleProps,
    Scene,
    SceneObject,
    SemanticOp,
    Side,
    SlotPlacement,
    StagePlacement,
    StagePoint,
    SvgProps,
    TextProps,
    TimelineEntry,
    TimelineProps,
    Transition,
    TransitionKind,
    after,
    at_narration,
    at_seconds,
    lasting,
    parse_project,
    spanning,
    with_cue,
)
from tests.support.ir_builders import (
    cue,
    make_project,
    scene_with,
    segment,
    text_obj,
    valid_project,
    valid_scene,
)

#: One props payload per declared object kind, so the widest union in the IR is
#: swept rather than sampled. Local to this module: nothing else needs it, and a
#: shared helper would go stale without anything failing.
_PROPS_BY_KIND: dict[ObjectKind, ObjectProps] = {
    ObjectKind.TEXT: TextProps(content="Where are you?", role="title"),
    ObjectKind.MATH: MathProps(latex=r"c \approx 3 \times 10^8"),
    ObjectKind.CIRCLE: CircleProps(radius=0.4, filled=True),
    ObjectKind.RECTANGLE: RectangleProps(width=0.8, height=0.5, corner_radius=0.1),
    ObjectKind.LINE: LineProps(
        start=StagePoint(x=-0.5, y=0.0), end=StagePoint(x=0.5, y=0.0), dashed=True
    ),
    ObjectKind.ARROW: ArrowProps(start="obj_text", end=StagePoint(x=0.6, y=0.6), curved=True),
    ObjectKind.DOT: DotProps(radius=0.05),
    ObjectKind.POLYGON: PolygonProps(
        points=[
            StagePoint(x=0.0, y=0.5),
            StagePoint(x=0.5, y=-0.5),
            StagePoint(x=-0.5, y=-0.5),
        ]
    ),
    ObjectKind.GRAPH: GraphProps(
        nodes=[GraphNode(id="a"), GraphNode(id="b", label="B")],
        edges=[GraphEdge(source="a", target="b", directed=True)],
    ),
    ObjectKind.CHART: ChartProps(
        chart_type="line",
        series=[ChartSeries(label="drift", values=[1.0, 2.5, 4.0])],
        categories=["t0", "t1", "t2"],
    ),
    ObjectKind.IMAGE: ImageProps(asset="assets/phone.png", width=0.6),
    ObjectKind.ICON: IconProps(name="satellite", size=0.3),
    ObjectKind.MAP: MapProps(region="north_america", projection="mercator"),
    ObjectKind.GLOBE: GlobeProps(radius=0.9, latitude=37.8, longitude=-122.4),
    ObjectKind.TIMELINE: TimelineProps(
        entries=[TimelineEntry(label="signal sent", position=0.0)], orientation="vertical"
    ),
    ObjectKind.DIAGRAM: DiagramProps(boxes=["ask", "measure", "solve"], style="layered"),
    ObjectKind.NETWORK: NetworkProps(
        nodes=[GraphNode(id="sat"), GraphNode(id="phone")],
        edges=[GraphEdge(source="sat", target="phone")],
        topology="star",
    ),
    ObjectKind.PARTICLES: ParticlesProps(count=24, spread=0.5),
    ObjectKind.AXES: AxesProps(x_range=(0.0, 5.0, 1.0), y_range=(-1.0, 1.0, 0.5), show_grid=True),
    ObjectKind.SVG: SvgProps(asset="assets/satellite.svg"),
    ObjectKind.GROUP: GroupProps(members=["obj_dot", "obj_circle"]),
}


def _reparse(project: Project) -> Project:
    """Send a project through JSON text and back, the way storage does."""
    return Project.model_validate_json(project.model_dump_json())


def _every_kind() -> list[SceneObject]:
    return [
        SceneObject(id=f"obj_{kind.value}", kind=kind, props=props)
        for kind, props in _PROPS_BY_KIND.items()
    ]


class TestProjectRoundTrip:
    """A project survives the trip to JSON and back unchanged."""

    def test_the_baseline_survives_intact(self) -> None:
        original = valid_project()

        assert _reparse(original) == original

    def test_an_empty_project_survives_intact(self) -> None:
        # Not a degenerate case to skip: this is the shape the pipeline persists
        # before any scene has been generated.
        original = make_project()

        assert _reparse(original) == original

    def test_the_ir_version_is_recorded_in_the_document(self) -> None:
        # Stored IR outlives the build that wrote it, so a reader must be able to
        # tell which schema it is holding before trusting any other field.
        payload = json.loads(valid_project().model_dump_json())

        assert payload["ir_version"] == IR_VERSION

    def test_parse_project_accepts_what_the_models_emit(self) -> None:
        # ``parse_project`` is the untrusted-input door. The pipeline's own output
        # has to go through it, or generation and storage disagree about the schema.
        original = valid_project()

        assert parse_project(json.loads(original.model_dump_json())) == original

    def test_a_malformed_ir_version_is_refused(self) -> None:
        payload = json.loads(valid_project().model_dump_json())
        payload["ir_version"] = "next"

        with pytest.raises(ValidationError):
            Project.model_validate(payload)


class TestDiscriminatedUnions:
    """Every union arm must come back as the arm it went in as.

    A discriminator that quietly coerces to the first structurally compatible arm
    is the classic Pydantic failure here, and it would stay invisible until a
    renderer read the wrong field.
    """

    @pytest.mark.parametrize(
        "placement",
        [
            SlotPlacement(slot="left"),
            AnchorPlacement(ref="title", side=Side.ABOVE, gap=0.25),
            StagePlacement(point=StagePoint(x=0.4, y=-0.2)),
        ],
    )
    def test_placement_modes_survive(self, placement: Placement) -> None:
        original = SceneObject(
            id="caption",
            kind=ObjectKind.TEXT,
            props=TextProps(content="Where are you?"),
            placement=placement,
        )
        restored = SceneObject.model_validate_json(original.model_dump_json())

        assert restored == original
        assert type(restored.placement) is type(placement)

    @pytest.mark.parametrize(
        "at",
        [
            at_seconds(1.5),
            after("show_title", 0.4),
            with_cue("show_title", -0.2),
            at_narration("line_one", "end", 0.3),
        ],
    )
    def test_time_expressions_survive(self, at: Any) -> None:
        original = Cue(id="beat", op=SemanticOp.HIGHLIGHT, targets=["phone"], at=at)
        restored = Cue.model_validate_json(original.model_dump_json())

        assert restored == original
        assert type(restored.at) is type(at)

    @pytest.mark.parametrize("duration", [lasting(2.0), spanning("line_one"), AUTO])
    def test_duration_expressions_survive(self, duration: Any) -> None:
        original = Cue(
            id="beat",
            op=SemanticOp.HIGHLIGHT,
            targets=["phone"],
            at=at_seconds(0.0),
            duration=duration,
        )
        restored = Cue.model_validate_json(original.model_dump_json())

        assert restored == original
        assert type(restored.duration) is type(duration)

    def test_every_object_kind_round_trips(self) -> None:
        original = scene_with(objects=_every_kind(), timeline=[], groups=[], relationships=[])
        restored = Scene.model_validate_json(original.model_dump_json())

        assert restored == original
        assert {o.kind for o in restored.objects} == frozenset(ObjectKind)
        assert [type(o.props) for o in restored.objects] == [
            type(o.props) for o in original.objects
        ]

    def test_a_props_payload_disagreeing_with_its_kind_is_refused(self) -> None:
        # The cross-check exists so a mismatch surfaces here rather than as a
        # renderer error far from its cause.
        with pytest.raises(ValidationError):
            SceneObject(id="caption", kind=ObjectKind.MATH, props=TextProps(content="Hi"))

    def test_extra_props_fields_are_refused(self) -> None:
        # ``extra="forbid"`` on props: a model inventing a plausible-sounding key
        # must be told, not silently ignored into a render that lacks the effect.
        with pytest.raises(ValidationError):
            TextProps.model_validate({"content": "Hi", "glow": True})


class TestSymbolicEndpointsSurvive:
    """An arrow endpoint is a point or an id, and the two must not collapse."""

    def test_an_id_endpoint_stays_a_string(self) -> None:
        original = SceneObject(
            id="link",
            kind=ObjectKind.ARROW,
            props=ArrowProps(start="phone", end="satellite"),
        )
        restored = SceneObject.model_validate_json(original.model_dump_json())

        assert restored == original
        assert restored.referenced_ids == {"phone", "satellite"}

    def test_a_point_endpoint_stays_a_point(self) -> None:
        original = SceneObject(
            id="link",
            kind=ObjectKind.ARROW,
            props=ArrowProps(start=StagePoint(x=-0.5, y=0.0), end=StagePoint(x=0.5, y=0.0)),
        )
        restored = SceneObject.model_validate_json(original.model_dump_json())

        assert restored == original
        assert restored.referenced_ids == set()


class TestCanonicalHashing:
    """Content addressing: the digest tracks meaning, not formatting."""

    def test_identical_ir_hashes_alike(self) -> None:
        assert valid_project().content_hash() == valid_project().content_hash()

    def test_a_round_trip_does_not_change_the_digest(self) -> None:
        # If it did, storing a project and reading it back would miss the cache
        # and re-render every unchanged scene.
        original = valid_project()

        assert _reparse(original).content_hash() == original.content_hash()

    def test_key_order_does_not_change_the_digest(self) -> None:
        payload = json.loads(valid_project().model_dump_json())
        shuffled = dict(reversed(list(payload.items())))

        assert sha256_of(shuffled) == sha256_of(payload)

    def test_indentation_does_not_change_the_digest(self) -> None:
        payload = json.loads(valid_project().model_dump_json())

        assert sha256_of(json.loads(json.dumps(payload, indent=4))) == sha256_of(payload)

    def test_a_changed_value_changes_the_digest(self) -> None:
        # The other half of the contract: a digest that ignored real edits would
        # serve a stale render forever.
        original = valid_project()
        edited = original.model_copy(update={"title": "Something else"})

        assert edited.content_hash() != original.content_hash()

    def test_retargeting_the_aspect_changes_the_digest(self) -> None:
        # One IR serves three aspects, but a RenderPlan is per-format -- so the
        # project digest has to distinguish them or the plans collide in storage.
        original = valid_project()
        vertical = original.with_format(FormatSpec.for_quality(Aspect.VERTICAL))

        assert vertical.content_hash() != original.content_hash()
        assert list(vertical.scenes) == list(original.scenes)

    def test_canonical_json_is_compact_and_sorted(self) -> None:
        text = canonical_json(FormatSpec())

        assert " " not in text
        assert list(json.loads(text)) == sorted(json.loads(text))


class TestAbsentVersusDefaulted:
    """Omission is a claim of its own, and has to survive as one."""

    def test_no_duration_hint_stays_absent(self) -> None:
        # ``None`` means "as long as the content needs"; any number would cap it.
        scene = next(_reparse(valid_project()).scenes)

        assert scene.duration_hint is None

    def test_a_duration_hint_survives_as_written(self) -> None:
        original = make_project(scene_with(duration_hint=6.5))

        assert next(_reparse(original).scenes).duration_hint == 6.5

    def test_omitted_measurements_stay_absent(self) -> None:
        # Both ends present means "measured against real audio". Defaulting them to
        # 0.0 in storage would make every estimated line look measured.
        line = next(_reparse(valid_project()).scenes).narration[0]

        assert (line.start, line.end) == (None, None)
        assert not line.is_timed

    def test_measurements_survive_the_retime_seam(self) -> None:
        timed = segment("line_one", "Hi.").with_timing(4.0, 5.5)
        original = make_project(scene_with(narration=[timed]))
        line = next(_reparse(original).scenes).narration[0]

        assert (line.start, line.end) == (4.0, 5.5)
        assert line.is_timed


class TestNestedStructuresSurvive:
    """The parts of the tree the scene-shaped baseline does not reach."""

    def test_a_split_layout_keeps_its_slots(self) -> None:
        original = scene_with(
            layout=LayoutSpec(
                kind=LayoutKind.SPLIT,
                slots=[LayoutSlot(name="left", weight=2.0), LayoutSlot(name="right")],
            )
        )
        restored = Scene.model_validate_json(original.model_dump_json())

        assert restored == original
        assert restored.layout.slot_names == frozenset({"left", "right"})

    def test_camera_state_survives(self) -> None:
        original = scene_with(
            camera=CameraSpec(
                initial=CameraState(center=StagePoint(x=0.3, y=-0.1), width=1.5),
                auto_frame=True,
                follow="phone",
                reset_at_end=True,
            )
        )

        assert Scene.model_validate_json(original.model_dump_json()) == original

    def test_transitions_survive(self) -> None:
        original = scene_with(
            transition_in=CUT,
            transition_out=Transition(kind=TransitionKind.CROSSFADE, duration=0.5),
        )
        restored = Scene.model_validate_json(original.model_dump_json())

        assert restored == original
        assert restored.transition_out.overlaps
        assert not restored.transition_in.overlaps

    def test_an_audio_timeline_survives(self) -> None:
        # Built by the compositor rather than authored, but persisted with the
        # episode, so it round-trips like everything else.
        original = Episode(
            id="main",
            title="Main",
            scenes=[valid_scene()],
            audio=AudioTimeline(
                clips=[
                    AudioClip(
                        id="line_one", asset="audio/line_one.wav", start=0.0, kind="narration"
                    )
                ]
            ),
        )
        restored = Episode.model_validate_json(original.model_dump_json())

        assert restored == original
        assert restored.audio is not None
        assert not restored.audio.is_silent

    def test_narration_roles_survive(self) -> None:
        original = scene_with(
            narration=[
                segment("line_one", "A question.", role=NarrationRole.HOOK),
                segment("line_two", "An answer.", role=NarrationRole.PAYOFF),
            ]
        )
        restored = Scene.model_validate_json(original.model_dump_json())

        assert [s.role for s in restored.narration] == [NarrationRole.HOOK, NarrationRole.PAYOFF]

    def test_cue_params_survive_by_type(self) -> None:
        # ``ParamValue`` is the §26 boundary: numbers, strings, flags and flat
        # lists only. An int must not come back as a float -- a count is not a
        # measurement, and the renderer indexes with one of them.
        original = scene_with(
            timeline=[
                cue(
                    "show_title",
                    SemanticOp.SHOW,
                    ["title"],
                    style="write",
                    count=3,
                    spread=0.25,
                    loop=True,
                    order=["a", "b"],
                    weights=[0.5, 1.5],
                )
            ]
        )
        restored = Scene.model_validate_json(original.model_dump_json())
        params = restored.timeline[0].params

        assert restored == original
        assert params["count"] == 3
        assert isinstance(params["count"], int)
        assert isinstance(params["loop"], bool)
        assert params["order"] == ["a", "b"]


class TestJsonPointerAddressability:
    """Repair patches address the IR by pointer, so the shape must be stable."""

    def test_lists_stay_lists_so_indices_mean_something(self) -> None:
        # A patch at ``/episodes/0/scenes/0/timeline/1`` is only meaningful if
        # serialization preserves order and never reshapes a list into a map.
        payload = json.loads(valid_project().model_dump_json())
        timeline = payload["episodes"][0]["scenes"][0]["timeline"]

        assert [entry["id"] for entry in timeline] == [c.id for c in valid_scene().timeline]

    def test_declaration_order_is_preserved(self) -> None:
        original = make_project(scene_with(objects=[text_obj("first"), text_obj("second")]))
        restored = _reparse(original)

        assert [o.id for o in next(restored.scenes).objects] == ["first", "second"]
