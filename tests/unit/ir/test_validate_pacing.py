"""T3 pacing and geometry lints: IR301-IR306.

Unlike T1 and T2, nothing here means the IR is *wrong* -- it means the video
would probably be bad. That difference is expressed as severity: these are
WARNINGs a caller may ignore, promotable to errors by policy when preparing a
final cut. So every test asserts the **warning** set and, separately, that no
error crept in; and one test pins the promotion, because a lint that changed
which findings appear -- rather than only how loud they are -- would break the
guarantee the baseline module rests on.

These checks are still geometric and arithmetic, computed from the IR and the
solved layout. They establish that nothing runs off the frame and nothing sits in
silence. They cannot establish that a frame is *readable* -- that is the Visual QA
stage's job, under its own ``VQA6xx`` codes.
"""

from __future__ import annotations

import pytest

from manorem_core import Code, Severity
from manorem_ir import (
    SAFE_AREA,
    Scene,
    SemanticOp,
    StageBounds,
    ValidationContext,
    ValidationPolicy,
    at_seconds,
    check_geometry,
    lasting,
    resolve_timing,
    scene_duration,
    validate_scene,
)
from tests.support.diag import error_codes, find, only, rendered, warning_codes
from tests.support.ir_builders import (
    cue,
    dot_obj,
    make_scene,
    scene_with,
    segment,
    show,
    valid_scene,
)

_STRICT = ValidationContext(policy=ValidationPolicy(strict_lints=True))

#: A box in the middle of the stage: the fixed partner in the overlap tests, so
#: only the other box varies between them.
_CENTER = StageBounds(min_x=-0.5, min_y=-0.5, max_x=0.5, max_y=0.5)

_OFF_STAGE = StageBounds(min_x=0.8, min_y=-0.2, max_x=1.4, max_y=0.2)


def _crowd(count: int, *, hide_first: bool = False) -> Scene:
    """``count`` dots, shown in one cue -- optionally cleared before the rest.

    The narration and objects are replaced wholesale, so the only pacing property
    left in play is concurrency.
    """
    objects = [dot_obj(f"sat_{index}") for index in range(count)]
    ids = [o.id for o in objects]
    first, rest = (ids[:7], ids[7:]) if hide_first else (ids, [])
    timeline = [show("show_first", first, duration=lasting(1.0))]
    if rest:
        timeline += [
            cue("hide_first", SemanticOp.HIDE, first, at=at_seconds(2.0), duration=lasting(0.6)),
            show("show_rest", rest, at=at_seconds(2.0), duration=lasting(1.0)),
        ]
    return scene_with(
        objects=objects,
        narration=[segment("line_one", "Look up.", pause_after=0.0)],
        duration_hint=3.0,
        timeline=timeline,
    )


class TestNarrationOverflow:
    """IR301. Narration is never truncated, so the scene must make room for it."""

    def test_narration_longer_than_the_scene(self) -> None:
        # The baseline's two lines run 3.8s at the default 150wpm.
        bag = validate_scene(scene_with(duration_hint=2.0))

        assert warning_codes(bag) == {Code.IR301_NARRATION_OVERFLOW}
        assert error_codes(bag) == set()
        diagnostic = only(bag, Code.IR301_NARRATION_OVERFLOW)
        assert diagnostic.pointer == "/duration_hint"
        assert diagnostic.hint is not None

    def test_a_scene_with_room_to_spare_is_silent(self) -> None:
        # 3.8s of narration inside a 5.0s scene: over the line at 2.0s, clean here.
        assert rendered(validate_scene(scene_with(duration_hint=5.0))) == []

    def test_no_hint_means_the_narration_defines_the_length(self) -> None:
        # Without a cap there is nothing to overflow: the scene is as long as its
        # content needs, which is what lets the baseline omit the hint entirely.
        assert Code.IR301_NARRATION_OVERFLOW not in validate_scene(valid_scene()).codes()


class TestDeadAir:
    """IR302. Stillness longer than the policy allows, at either end or between."""

    def test_gap_before_the_first_cue(self) -> None:
        scene = scene_with(
            duration_hint=12.0,
            timeline=[show("show_title", ["title"], at=at_seconds(10.0), duration=lasting(1.0))],
        )
        bag = validate_scene(scene)

        assert warning_codes(bag) == {Code.IR302_DEAD_AIR}
        assert error_codes(bag) == set()
        diagnostic = only(bag, Code.IR302_DEAD_AIR)
        assert diagnostic.pointer == "/timeline"
        assert "nothing happening before" in diagnostic.message

    def test_stillness_after_the_last_cue(self) -> None:
        scene = scene_with(
            duration_hint=8.0,
            timeline=[show("show_title", ["title"], duration=lasting(1.0))],
        )
        bag = validate_scene(scene)

        assert warning_codes(bag) == {Code.IR302_DEAD_AIR}
        assert "after the last cue" in only(bag, Code.IR302_DEAD_AIR).message

    def test_each_hole_is_reported_once(self) -> None:
        # Two holes are two findings, not one summary and not four: the author has
        # two places to fix, and the repair loop must not see duplicates.
        scene = scene_with(
            duration_hint=14.0,
            timeline=[
                show("show_title", ["title"], duration=lasting(1.0)),
                show("show_phone", ["phone"], at=at_seconds(5.0), duration=lasting(1.0)),
                cue(
                    "pulse_phone",
                    SemanticOp.HIGHLIGHT,
                    ["phone"],
                    at=at_seconds(12.0),
                    duration=lasting(1.0),
                ),
            ],
        )
        bag = validate_scene(scene)

        assert warning_codes(bag) == {Code.IR302_DEAD_AIR}
        assert len(find(bag, Code.IR302_DEAD_AIR)) == 2

    @pytest.mark.parametrize(("start", "expected"), [(3.4, set()), (3.6, {Code.IR302_DEAD_AIR})])
    def test_the_threshold_is_the_policy_value(self, start: float, expected: set[Code]) -> None:
        # ``max_dead_air`` defaults to 2.5s, so a 2.4s hole is pacing and a 2.6s
        # hole is a finding. Where that line sits is a judgement call about the
        # material, which is why it is policy rather than a constant.
        scene = scene_with(
            duration_hint=6.0,
            timeline=[
                show("show_title", ["title"], duration=lasting(1.0)),
                show("show_phone", ["phone"], at=at_seconds(start), duration=lasting(1.0)),
            ],
        )

        assert warning_codes(validate_scene(scene)) == expected


class TestSceneTooDense:
    """IR303. Too much on stage at once, counted from the show and hide cues."""

    def test_over_the_limit(self) -> None:
        bag = validate_scene(_crowd(13))

        assert warning_codes(bag) == {Code.IR303_SCENE_TOO_DENSE}
        assert error_codes(bag) == set()
        assert only(bag, Code.IR303_SCENE_TOO_DENSE).pointer == "/objects"

    def test_exactly_at_the_limit_is_allowed(self) -> None:
        assert warning_codes(validate_scene(_crowd(12))) == set()

    def test_clearing_the_stage_first_keeps_the_count_down(self) -> None:
        # The measure is concurrency, not a running total -- so hiding earlier
        # objects, which is exactly what the hint suggests, must clear the finding.
        assert warning_codes(validate_scene(_crowd(13, hide_first=True))) == set()


class TestSceneTooShort:
    """IR306. Below the minimum, nobody can read what appeared."""

    def test_scene_under_the_minimum(self) -> None:
        scene = scene_with(
            duration_hint=0.5,
            narration=[segment("line_one", "Hi.", pause_after=0.0)],
            timeline=[show("show_title", ["title"], duration=lasting(0.4))],
        )
        bag = validate_scene(scene)

        assert warning_codes(bag) == {Code.IR306_SCENE_TOO_SHORT}
        assert error_codes(bag) == set()
        diagnostic = only(bag, Code.IR306_SCENE_TOO_SHORT)
        assert diagnostic.pointer == "/"
        assert diagnostic.hint is not None

    def test_an_empty_scene_is_not_also_too_short(self) -> None:
        # A zero-length scene is IR104's business; adding IR306 would hand the
        # repair loop two findings for one missing scene body.
        bag = validate_scene(make_scene())

        assert error_codes(bag) == {Code.IR104_EMPTY_SCENE}
        assert warning_codes(bag) == set()


class TestGeometryLints:
    """IR304/IR305, run by the compiler once pass P3 has solved positions.

    ``check_geometry`` takes solved bounds rather than a scene, because the IR
    carries no coordinates: these are the only two codes that cannot be computed
    from authored IR alone.
    """

    def test_overlap_beyond_the_allowed_ratio(self) -> None:
        # 0.25 of the smaller 0.36 box is covered -- 69%, well past the 35% limit.
        bounds = {
            "title": _CENTER,
            "phone": StageBounds(min_x=0.0, min_y=0.0, max_x=0.6, max_y=0.6),
        }
        bag = check_geometry("intro", bounds)

        assert warning_codes(bag) == {Code.IR304_OBJECT_OVERLAP}
        diagnostic = only(bag, Code.IR304_OBJECT_OVERLAP)
        assert diagnostic.pointer == "/objects"
        assert diagnostic.scene_id == "intro"
        assert diagnostic.hint is not None

    def test_incidental_overlap_is_allowed(self) -> None:
        # Clipped corners are how tight layouts look; only occlusion is a finding.
        bounds = {
            "title": _CENTER,
            "phone": StageBounds(min_x=0.4, min_y=0.4, max_x=1.0, max_y=1.0),
        }

        assert rendered(check_geometry("intro", bounds)) == []

    def test_box_outside_the_safe_area(self) -> None:
        bag = check_geometry("intro", {"phone": _OFF_STAGE})

        assert warning_codes(bag) == {Code.IR305_OFF_STAGE}
        assert only(bag, Code.IR305_OFF_STAGE).pointer == "/objects"

    def test_the_safe_area_itself_fits(self) -> None:
        # Content is authored against this box in every aspect, and pass P6 maps it
        # to world units per format -- so filling it exactly must be legal.
        assert (SAFE_AREA.min_x, SAFE_AREA.min_y, SAFE_AREA.max_x, SAFE_AREA.max_y) == (
            -1.0,
            -1.0,
            1.0,
            1.0,
        )
        assert check_geometry("intro", {"phone": SAFE_AREA}).items == []

    def test_no_bounds_means_nothing_to_report(self) -> None:
        assert check_geometry("intro", {}).items == []

    def test_findings_are_addressed_under_the_given_base(self) -> None:
        # The compiler checks whole projects, so the pointer has to nest.
        bag = check_geometry("intro", {"phone": _OFF_STAGE}, base="/episodes/0/scenes/0")

        assert only(bag, Code.IR305_OFF_STAGE).pointer == "/episodes/0/scenes/0/objects"


class TestStrictLintPromotion:
    """Policy changes how loud a finding is, never which findings exist."""

    def test_a_lint_becomes_an_error_and_stops_being_autofixable(self) -> None:
        scene = scene_with(
            duration_hint=8.0,
            timeline=[show("show_title", ["title"], duration=lasting(1.0))],
        )

        lenient = only(validate_scene(scene), Code.IR302_DEAD_AIR)
        strict = only(validate_scene(scene, _STRICT), Code.IR302_DEAD_AIR)

        assert lenient.severity is Severity.WARNING and lenient.autofixable
        assert strict.severity is Severity.ERROR and not strict.autofixable
        assert (strict.code, strict.pointer, strict.message) == (
            lenient.code,
            lenient.pointer,
            lenient.message,
        )

    def test_geometry_lints_are_promoted_by_the_same_policy(self) -> None:
        bag = check_geometry("intro", {"phone": _OFF_STAGE}, _STRICT)

        assert error_codes(bag) == {Code.IR305_OFF_STAGE}


class TestSceneDuration:
    """How long a scene actually is -- the number every T3 threshold divides."""

    def test_the_hint_wins_when_given(self) -> None:
        scene = scene_with(duration_hint=9.0)

        assert scene_duration(scene, resolve_timing(scene)) == 9.0

    def test_otherwise_the_content_decides(self) -> None:
        # Narration outlasts the timeline in the baseline (3.8s against 3.2s), so
        # the scene has to hold for the voice-over, not just for the visuals.
        scene = valid_scene()

        assert scene_duration(scene, resolve_timing(scene)) == pytest.approx(3.8)

    def test_visuals_outlasting_narration_also_count(self) -> None:
        scene = scene_with(
            narration=[segment("line_one", "Hi.", pause_after=0.0)],
            timeline=[show("show_title", ["title"], at=at_seconds(4.0), duration=lasting(1.0))],
        )

        assert scene_duration(scene, resolve_timing(scene)) == pytest.approx(5.0)

    def test_an_empty_scene_is_zero_length(self) -> None:
        scene = make_scene()

        assert scene_duration(scene, resolve_timing(scene)) == 0.0
