"""Symbolic timing resolution: the numbers every later stage divides.

Two consumers must agree about these values -- the T2/T3 validators report timing
defects from them, and compiler pass P4 quantizes the same values to frames. So
these tests pin the *arithmetic*, not merely the shape: a cue that starts a fifth
of a second late here becomes a narration desync in the finished video.

Resolution is deliberately **total** and deliberately **honest**: a partly broken
timeline still yields times for every well-formed cue, and reports what it could
not resolve rather than defaulting it to zero. Several tests exist only to hold
that line, because a cue silently starting at t=0 is exactly the kind of
plausible-looking wrongness this layer exists to catch.

Nothing here validates. These are the raw numbers; which of them count as *bad
pacing* is :mod:`test_validate_pacing`'s business.
"""

from __future__ import annotations

import pytest

from manorem_ir import (
    AUTO,
    DurationExpr,
    OperationDecl,
    OperationRegistry,
    Scene,
    SemanticOp,
    TimeExpr,
    Window,
    after,
    at_narration,
    at_seconds,
    lasting,
    narration_windows,
    resolve_timing,
    spanning,
    with_cue,
)
from manorem_ir.resolve import FALLBACK_DURATION
from tests.support.ir_builders import cue, make_scene, scene_with, segment, show, valid_scene

_HALF = lasting(0.5)


def _one_cue(at: TimeExpr, duration: DurationExpr = _HALF) -> Scene:
    """The baseline narration, with a single cue named ``beat`` on the timeline.

    Replacing the whole timeline leaves the two narration windows -- ``line_one``
    [0, 2.3] and ``line_two`` [2.3, 3.8] -- as the only thing a start can be
    measured against, so an anchored expression has exactly one right answer.
    """
    return scene_with(
        timeline=[cue("beat", SemanticOp.HIGHLIGHT, ["phone"], at=at, duration=duration)]
    )


class TestNarrationWindows:
    """Where each line sits on the scene clock, before any cue is placed."""

    def test_segments_are_laid_end_to_end(self) -> None:
        # 5 words then 3 at 150wpm, each with the default 0.3s pause after it.
        windows = narration_windows(valid_scene())

        assert (windows["line_one"].start, windows["line_one"].end) == pytest.approx((0.0, 2.3))
        assert (windows["line_two"].start, windows["line_two"].end) == pytest.approx((2.3, 3.8))

    def test_a_measured_segment_is_used_verbatim(self) -> None:
        # The retime seam: a segment carrying both ends has been measured against
        # real audio, so the estimate must not override it -- and the next line
        # continues from where the measurement actually ended, not from the guess.
        scene = scene_with(
            narration=[
                segment("line_one", "Hi.", start=10.0, end=12.0),
                segment("line_two", "Bye."),
            ]
        )
        windows = narration_windows(scene)

        assert (windows["line_one"].start, windows["line_one"].end) == (10.0, 12.0)
        assert (windows["line_two"].start, windows["line_two"].end) == pytest.approx((12.0, 12.7))

    def test_a_half_timed_segment_falls_back_to_the_estimate(self) -> None:
        # One end is not a measurement. Trusting it would place the line at 10s
        # and give it an invented length; the estimate is the honest answer.
        scene = scene_with(narration=[segment("line_one", "Hi.", start=10.0)])
        window = narration_windows(scene)["line_one"]

        assert (window.start, window.end) == pytest.approx((0.0, 0.7))

    def test_a_segment_can_override_the_rate(self) -> None:
        scene = scene_with(
            narration=[segment("line_one", "Where are you right now?", wpm=300.0, pause_after=0.0)]
        )

        assert narration_windows(scene)["line_one"].duration == pytest.approx(1.0)

    def test_the_project_rate_scales_every_estimate(self) -> None:
        windows = narration_windows(valid_scene(), wpm=300.0)

        assert (windows["line_one"].end, windows["line_two"].end) == pytest.approx((1.3, 2.2))

    def test_the_pause_is_inside_the_window(self) -> None:
        # So a cue anchored to a line's *end* lands after the silence, which is
        # what "let the visual land" means when an author writes ``pause_after``.
        held = scene_with(narration=[segment("line_one", "Hi.", pause_after=0.8)])
        brisk = scene_with(narration=[segment("line_one", "Hi.", pause_after=0.0)])

        assert narration_windows(held)["line_one"].end - narration_windows(brisk)[
            "line_one"
        ].end == pytest.approx(0.8)

    def test_no_narration_means_no_windows(self) -> None:
        assert narration_windows(make_scene()) == {}


class TestCueStarts:
    """Resolving ``at`` into seconds from the start of the scene."""

    def test_an_absolute_time_is_taken_as_written(self) -> None:
        assert resolve_timing(_one_cue(at_seconds(2.5))).starts["beat"] == 2.5

    def test_after_a_cue_adds_its_length_then_the_gap(self) -> None:
        # The baseline chain: 0.0, then 0.0+1.0+0.2, then 1.2+1.0+0.0.
        timing = resolve_timing(valid_scene())

        assert timing.starts == pytest.approx(
            {"show_title": 0.0, "show_phone": 1.2, "pulse_phone": 2.2}
        )

    def test_a_negative_gap_overlaps_the_previous_cue(self) -> None:
        # Cues are not obliged to queue up: a negative gap is how an author says
        # "begin this one while that one is still finishing".
        scene = scene_with(
            timeline=[
                show("show_title", ["title"], duration=lasting(1.0)),
                show("show_phone", ["phone"], at=after("show_title", -0.4), duration=lasting(1.0)),
            ]
        )

        assert resolve_timing(scene).starts["show_phone"] == pytest.approx(0.6)

    def test_with_a_cue_measures_from_its_start(self) -> None:
        # ``after`` measures from the end, ``with`` from the start. Confusing the
        # two fails silently -- both yield a plausible number -- so it is pinned
        # against a base cue long enough that the two answers cannot coincide.
        scene = scene_with(
            timeline=[
                show("show_title", ["title"], duration=lasting(3.0)),
                show(
                    "show_phone", ["phone"], at=with_cue("show_title", 0.5), duration=lasting(1.0)
                ),
            ]
        )

        assert resolve_timing(scene).starts["show_phone"] == pytest.approx(0.5)

    @pytest.mark.parametrize(
        ("at", "expected"),
        [
            (at_narration("line_one"), 0.0),
            (at_narration("line_one", "end"), 2.3),
            (at_narration("line_two"), 2.3),
            (at_narration("line_two", "end"), 3.8),
            (at_narration("line_two", "start", -0.5), 1.8),
        ],
    )
    def test_a_narration_anchor_resolves_to_that_edge(self, at: TimeExpr, expected: float) -> None:
        assert resolve_timing(_one_cue(at)).starts["beat"] == pytest.approx(expected)


class TestCueDurations:
    """Resolving ``duration``, whose default comes from the operation table."""

    def test_an_explicit_length_is_taken_as_written(self) -> None:
        assert resolve_timing(_one_cue(at_seconds(0.0), lasting(2.5))).durations["beat"] == 2.5

    @pytest.mark.parametrize(
        ("op", "expected"),
        [
            (SemanticOp.SHOW, 1.0),
            (SemanticOp.HIDE, 0.6),
            (SemanticOp.HIGHLIGHT, 0.8),
            (SemanticOp.FLOW, 1.5),
        ],
    )
    def test_auto_takes_the_declared_default(self, op: SemanticOp, expected: float) -> None:
        # Pacing per operation is a property of the vocabulary, not of each cue: a
        # hide is brisker than a show, and an author never has to know the number.
        scene = scene_with(timeline=[cue("beat", op, ["phone"], duration=AUTO)])

        assert resolve_timing(scene).durations["beat"] == expected

    def test_a_skill_can_retune_pacing_through_the_registry(self) -> None:
        # How a skill tunes its own operations. The registry is a parameter, so a
        # skill that loads cannot quietly re-time every other scene in the project.
        registry = OperationRegistry()
        registry.register(
            OperationDecl(op=SemanticOp.SHOW, summary="A slower show.", default_duration=2.5)
        )
        scene = scene_with(timeline=[show("show_title", ["title"], duration=AUTO)])

        assert resolve_timing(scene, registry=registry).durations["show_title"] == 2.5
        assert resolve_timing(scene).durations["show_title"] == 1.0

    def test_an_undeclared_operation_falls_back(self) -> None:
        # Reached only when the op is already an IR205 error. Resolution stays
        # total so validation can report that, instead of raising on the way there.
        scene = scene_with(timeline=[show("show_title", ["title"], duration=AUTO)])

        assert resolve_timing(scene, registry=OperationRegistry(())).durations["show_title"] == (
            FALLBACK_DURATION
        )

    def test_spanning_a_narration_segment_borrows_its_length(self) -> None:
        timing = resolve_timing(_one_cue(at_seconds(0.0), spanning("line_one")))

        assert timing.durations["beat"] == pytest.approx(2.3)

    def test_spanning_a_missing_segment_leaves_the_length_absent(self) -> None:
        # Absent, not zero and not a fallback: the cue has no knowable length,
        # which is what IR203 reports. Inventing one would also resolve whatever
        # follows it, turning one clear finding into a scene of subtly wrong times.
        timing = resolve_timing(_one_cue(at_seconds(0.0), spanning("ghost")))

        assert "beat" not in timing.durations
        assert timing.window("beat") == Window(start=0.0, end=0.0)


class TestWhatCannotBeResolved:
    """The honest half: reporting a missing time instead of inventing one."""

    def test_a_dangling_dependency_is_reported_not_defaulted(self) -> None:
        timing = resolve_timing(_one_cue(after("nowhere")))

        assert timing.unresolved == frozenset({"beat"})
        assert "beat" not in timing.starts

    def test_after_needs_both_a_start_and_a_length(self) -> None:
        # ``base`` resolves, but its length does not, so nothing can be placed
        # behind it. Both halves are required, and a missing length is not zero.
        scene = scene_with(
            timeline=[
                cue("base", SemanticOp.SHOW, ["title"], duration=spanning("ghost")),
                show("follower", ["phone"], at=after("base"), duration=lasting(1.0)),
            ]
        )
        timing = resolve_timing(scene)

        assert timing.starts["base"] == 0.0
        assert timing.unresolved == frozenset({"follower"})

    def test_a_self_cycle(self) -> None:
        timing = resolve_timing(_one_cue(after("beat")))

        assert timing.cycles == (("beat",),)
        assert timing.unresolved == frozenset({"beat"})

    def test_a_two_cue_cycle(self) -> None:
        scene = scene_with(
            timeline=[
                show("first", ["title"], at=after("second"), duration=lasting(1.0)),
                show("second", ["phone"], at=after("first"), duration=lasting(1.0)),
            ]
        )
        timing = resolve_timing(scene)

        assert [set(cycle) for cycle in timing.cycles] == [{"first", "second"}]
        assert timing.unresolved == frozenset({"first", "second"})

    def test_a_cue_downstream_of_a_cycle_is_unresolved_but_not_part_of_it(self) -> None:
        # The distinction is what makes IR204 readable: it names the two cues that
        # actually reference each other, and the fallout is not reported as more
        # cycles for an author to go looking for.
        scene = scene_with(
            timeline=[
                show("first", ["title"], at=after("second"), duration=lasting(1.0)),
                show("second", ["phone"], at=after("first"), duration=lasting(1.0)),
                show("bystander", ["phone"], at=after("second"), duration=lasting(1.0)),
            ]
        )
        timing = resolve_timing(scene)

        assert [set(cycle) for cycle in timing.cycles] == [{"first", "second"}]
        assert timing.unresolved == frozenset({"first", "second", "bystander"})

    def test_two_independent_cycles_are_both_reported(self) -> None:
        scene = scene_with(
            timeline=[
                show("loop_a_in", ["title"], at=after("loop_a_out"), duration=lasting(1.0)),
                show("loop_a_out", ["title"], at=after("loop_a_in"), duration=lasting(1.0)),
                show("loop_b_in", ["phone"], at=after("loop_b_out"), duration=lasting(1.0)),
                show("loop_b_out", ["phone"], at=after("loop_b_in"), duration=lasting(1.0)),
            ]
        )

        assert [set(cycle) for cycle in resolve_timing(scene).cycles] == [
            {"loop_a_in", "loop_a_out"},
            {"loop_b_in", "loop_b_out"},
        ]

    def test_a_healthy_timeline_reports_neither(self) -> None:
        timing = resolve_timing(valid_scene())

        assert timing.cycles == ()
        assert timing.unresolved == frozenset()


class TestWindow:
    """Intervals are half-open, so back-to-back cues are not simultaneous."""

    def test_duration(self) -> None:
        assert Window(start=1.5, end=4.0).duration == 2.5

    @pytest.mark.parametrize(
        ("other", "expected"),
        [
            (Window(start=1.0, end=2.0), False),
            (Window(start=-1.0, end=0.0), False),
            (Window(start=0.5, end=2.0), True),
            (Window(start=0.25, end=0.75), True),
            (Window(start=-1.0, end=5.0), True),
        ],
    )
    def test_overlaps(self, other: Window, expected: bool) -> None:
        base = Window(start=0.0, end=1.0)

        assert base.overlaps(other) is expected
        assert other.overlaps(base) is expected


class TestResolvedTimingSurface:
    """The questions callers actually ask: when, for how long, and when it ends."""

    def test_a_window_pairs_a_start_with_its_length(self) -> None:
        window = resolve_timing(valid_scene()).window("show_phone")

        assert window is not None
        assert (window.start, window.end) == pytest.approx((1.2, 2.2))

    def test_an_unknown_cue_has_no_window(self) -> None:
        assert resolve_timing(valid_scene()).window("nowhere") is None

    def test_the_end_is_the_last_finish_not_the_last_declaration(self) -> None:
        # A long cue declared first still sets the scene's length -- the number
        # ``scene_duration`` reports and every T3 threshold then divides.
        scene = scene_with(
            timeline=[
                show("show_title", ["title"], duration=lasting(5.0)),
                show("show_phone", ["phone"], at=at_seconds(1.0), duration=lasting(0.5)),
            ]
        )

        assert resolve_timing(scene).end == 5.0

    def test_an_empty_timeline_ends_at_zero(self) -> None:
        assert resolve_timing(make_scene()).end == 0.0


class TestResolutionIsIndependentOfOrder:
    """Authored IR is not required to arrive topologically sorted."""

    def test_a_cue_declared_before_its_dependency_still_resolves(self) -> None:
        # Resolution iterates to a fixpoint instead of sorting, so a timeline
        # written in narrative order resolves the same as one in causal order --
        # which is what lets a generator emit cues in the order it thought of them.
        baseline = valid_scene()
        reversed_order = scene_with(timeline=list(reversed(baseline.timeline)))

        assert resolve_timing(reversed_order).starts == pytest.approx(
            resolve_timing(baseline).starts
        )

    def test_repeated_calls_agree(self) -> None:
        # Determinism all the way down is what makes a committed RenderPlan
        # snapshot a usable regression gate rather than a source of noise.
        scene = valid_scene()

        assert resolve_timing(scene) == resolve_timing(scene)
