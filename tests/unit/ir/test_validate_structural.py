"""T1 structural validation: IR101-IR106.

Pydantic covers types, enums and ranges at parse time. These tests pin the two
things it cannot: the translation of a parse failure into the shared diagnostic
vocabulary (so the repair agent sees one contract, not two), and the cross-field
facts a schema has no way to express -- id uniqueness across sibling namespaces,
emptiness, and durations that round to zero frames at the target rate.
"""

from __future__ import annotations

import pytest

from manorem_core import Code, IRValidationError
from manorem_ir import (
    DurationExpr,
    FormatSpec,
    Scene,
    SemanticOp,
    ValidationContext,
    at_seconds,
    lasting,
    parse_project,
    spanning,
    validate_project,
    validate_scene,
)
from tests.support.diag import error_codes, only
from tests.support.ir_builders import (
    circle_obj,
    cue,
    dot_obj,
    episode,
    group,
    make_project,
    make_scene,
    scene_with,
    segment,
    show,
    text_obj,
    valid_project,
    valid_scene,
)


class TestParseProject:
    """``parse_project`` is the only door into the IR, so it owns the translation."""

    def test_round_trips_a_valid_document(self) -> None:
        data = valid_project().model_dump(mode="json")
        assert parse_project(data) == valid_project()

    def test_wrong_type_is_ir101(self) -> None:
        with pytest.raises(IRValidationError) as exc_info:
            parse_project({"id": "demo", "title": "Demo", "episodes": 5})

        assert {d.code for d in exc_info.value.diagnostics} == {Code.IR101_SCHEMA_INVALID}

    def test_kind_and_props_disagreement_is_ir101(self) -> None:
        # The discriminated union is enforced by a model validator, not the schema,
        # so this arrives as a plain value error and must still surface as IR101.
        data = valid_project().model_dump(mode="json")
        data["episodes"][0]["scenes"][0]["objects"][0]["kind"] = "circle"

        with pytest.raises(IRValidationError) as exc_info:
            parse_project(data)

        assert Code.IR101_SCHEMA_INVALID in {d.code for d in exc_info.value.diagnostics}

    def test_malformed_id_is_ir103_not_ir101(self) -> None:
        # A bad identifier is worth its own code: it is the one structural failure
        # a deterministic rule could plausibly repair by slugifying.
        with pytest.raises(IRValidationError) as exc_info:
            parse_project({"id": "Not A Slug", "title": "Demo"})

        diagnostic = exc_info.value.diagnostics[0]
        assert diagnostic.code is Code.IR103_INVALID_ID
        assert diagnostic.pointer == "/id"
        assert diagnostic.hint is not None

    def test_nested_id_error_points_at_the_offending_field(self) -> None:
        data = valid_project().model_dump(mode="json")
        data["episodes"][0]["scenes"][0]["timeline"][0]["targets"][0] = "Bad Target"

        with pytest.raises(IRValidationError) as exc_info:
            parse_project(data)

        diagnostic = exc_info.value.diagnostics[0]
        assert diagnostic.code is Code.IR103_INVALID_ID
        assert diagnostic.pointer == "/episodes/0/scenes/0/timeline/0/targets/0"

    def test_error_carries_diagnostics_not_a_string(self) -> None:
        with pytest.raises(IRValidationError) as exc_info:
            parse_project({"id": "demo"})

        assert exc_info.value.diagnostics
        assert "IR101" in str(exc_info.value)


class TestDuplicateIds:
    """IR102. Ambiguous ids make every reference to them unresolvable."""

    def test_duplicate_object_id(self) -> None:
        scene = scene_with(objects=[text_obj("title"), dot_obj("phone"), circle_obj("phone")])

        diagnostic = only(validate_scene(scene), Code.IR102_DUPLICATE_ID)
        assert diagnostic.object_id == "phone"
        assert diagnostic.pointer == "/objects"

    def test_object_and_group_sharing_an_id(self) -> None:
        # Cue targets resolve against both namespaces at once, so a collision is
        # not merely untidy -- it makes the target ambiguous.
        scene = scene_with(groups=[group("phone", ["phone"])])

        assert error_codes(validate_scene(scene)) == {Code.IR102_DUPLICATE_ID}

    def test_duplicate_cue_id(self) -> None:
        scene = scene_with(
            timeline=[
                show("show_title", ["title"], duration=lasting(1.0)),
                show("show_title", ["phone"], at=at_seconds(2.0), duration=lasting(1.5)),
            ]
        )

        assert only(validate_scene(scene), Code.IR102_DUPLICATE_ID).pointer == "/timeline"

    def test_duplicate_narration_segment_id(self) -> None:
        scene = scene_with(
            narration=[
                segment("line_one", "Where are you right now?"),
                segment("line_one", "Your phone knows.", mentions=["phone"]),
            ]
        )

        assert only(validate_scene(scene), Code.IR102_DUPLICATE_ID).pointer == "/narration"

    def test_duplicate_episode_id(self) -> None:
        project = make_project(
            episodes=[episode("main", valid_scene()), episode("main", scene_with(id="outro"))]
        )

        assert only(validate_project(project), Code.IR102_DUPLICATE_ID).object_id == "main"

    def test_scene_id_reused_across_episodes(self) -> None:
        # Scene ids are addressed project-wide for partial re-render and targeted
        # repair, so uniqueness is a project-level property, not a scene-level one.
        project = make_project(
            episodes=[episode("one", valid_scene()), episode("two", valid_scene())]
        )

        diagnostic = only(validate_project(project), Code.IR102_DUPLICATE_ID)
        assert diagnostic.object_id == "intro"
        assert diagnostic.pointer == "/episodes"


class TestEmptyContent:
    def test_scene_with_neither_objects_nor_cues_is_ir104(self) -> None:
        assert error_codes(validate_scene(make_scene())) == {Code.IR104_EMPTY_SCENE}

    def test_narration_alone_is_still_an_empty_scene(self) -> None:
        # An audio-only scene renders a blank frame; the pipeline should say so.
        scene = make_scene(narration=[segment("line_one")])

        assert error_codes(validate_scene(scene)) == {Code.IR104_EMPTY_SCENE}

    def test_objects_without_cues_is_not_empty(self) -> None:
        scene = make_scene(objects=[dot_obj("phone")])

        assert Code.IR104_EMPTY_SCENE not in validate_scene(scene).codes()

    def test_project_without_episodes_is_ir106(self) -> None:
        bag = validate_project(make_project(episodes=[]))

        assert only(bag, Code.IR106_NO_SCENES).pointer == "/episodes"

    def test_episode_without_scenes_is_ir106(self) -> None:
        bag = validate_project(make_project(episodes=[episode("main")]))

        assert only(bag, Code.IR106_NO_SCENES).pointer == "/episodes/0/scenes"


def _scene_with_pulse(duration: DurationExpr) -> Scene:
    """The baseline timeline with an explicit schedule and a custom last duration."""
    return scene_with(
        timeline=[
            show("show_title", ["title"], duration=lasting(1.0)),
            show("show_phone", ["phone"], at=at_seconds(1.2), duration=lasting(1.0)),
            cue(
                "pulse_phone",
                SemanticOp.HIGHLIGHT,
                ["phone"],
                at=at_seconds(2.2),
                duration=duration,
            ),
        ]
    )


class TestSubFrameDuration:
    """IR105. A cue shorter than one frame renders nothing at all."""

    def test_duration_under_one_frame_is_reported(self) -> None:
        bag = validate_scene(_scene_with_pulse(lasting(0.01)))

        assert error_codes(bag) == {Code.IR105_NON_POSITIVE_DURATION}
        assert only(bag, Code.IR105_NON_POSITIVE_DURATION).pointer == "/timeline/2/duration"

    def test_the_threshold_follows_the_target_frame_rate(self) -> None:
        # The same IR is fine at 60fps and degenerate at 15fps, which is precisely
        # why this cannot live in the schema.
        scene = _scene_with_pulse(lasting(0.02))

        at_15 = validate_scene(scene, ValidationContext(fps=15))
        at_60 = validate_scene(scene, ValidationContext(fps=60))

        assert Code.IR105_NON_POSITIVE_DURATION in at_15.codes()
        assert Code.IR105_NON_POSITIVE_DURATION not in at_60.codes()

    def test_project_validation_takes_fps_from_the_format(self) -> None:
        # Callers must not have to remember to pass fps; the project already knows.
        draft = make_project(_scene_with_pulse(lasting(0.02)))

        assert Code.IR105_NON_POSITIVE_DURATION in validate_project(draft).codes()
        final = draft.with_format(FormatSpec.for_quality(quality="final"))
        assert Code.IR105_NON_POSITIVE_DURATION not in validate_project(final).codes()

    def test_unresolvable_duration_is_not_reported_as_zero(self) -> None:
        # An unresolved duration is an IR203, not a zero-length cue: reporting both
        # would send the repair agent chasing a symptom.
        bag = validate_scene(_scene_with_pulse(spanning("ghost")))

        assert error_codes(bag) == {Code.IR203_UNKNOWN_NARRATION_REF}
