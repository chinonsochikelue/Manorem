"""Narration timing estimates: the clock the whole timeline is pinned to.

Cues anchor to segments symbolically, so this estimate is what "when the
narration about satellites starts" ultimately resolves to. Two properties matter
more than the exact numbers:

* it is a **pure function of the text**, so the same script always yields the same
  timeline -- which is what makes a committed RenderPlan snapshot stable;
* ``start``/``end`` are **derived, never authored**, so a segment carrying them
  has been measured against real audio and must not be re-estimated.

The second is the TTS retime seam: when real durations arrive they replace these
estimates segment by segment, and :mod:`test_resolve` holds the mixed case.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from manorem_ir import DEFAULT_WPM, NarrationRole, NarrationSegment
from tests.support.ir_builders import segment


class TestWordCount:
    """Words, counted the way a narrator would read them."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Where are you right now?", 5),
            ("One", 1),
            ("  padded   by    whitespace  ", 3),
            ("across\nlines\tand tabs", 4),
            ("hyphenated-words count once", 3),
        ],
    )
    def test_words_are_whitespace_separated_runs(self, text: str, expected: int) -> None:
        assert segment("line_one", text).word_count == expected


class TestEstimatedDuration:
    """Speaking time plus the trailing pause, and nothing else."""

    def test_the_default_rate_is_unhurried(self) -> None:
        # Explainer narration sits well below conversational speed; every timing
        # in the suite is derived from this number, so it is worth stating once.
        assert DEFAULT_WPM == 150.0

    def test_a_minute_of_words_takes_a_minute(self) -> None:
        line = segment("line_one", " ".join(["word"] * 150), pause_after=0.0)

        assert line.estimated_duration() == pytest.approx(60.0)

    def test_the_pause_is_added_to_the_speaking_time(self) -> None:
        line = segment("line_one", "Four words go here", pause_after=0.5)

        assert line.estimated_duration() == pytest.approx(4 * 60.0 / 150.0 + 0.5)

    def test_a_faster_rate_shortens_the_line(self) -> None:
        line = segment("line_one", "Where are you right now?", pause_after=0.0)

        assert line.estimated_duration(300.0) == pytest.approx(1.0)

    def test_the_segment_s_own_rate_wins(self) -> None:
        # Per-segment override: one deliberately slow line inside an otherwise
        # brisk script, without re-rating the whole project.
        line = segment("line_one", "Where are you right now?", wpm=75.0, pause_after=0.0)

        assert line.estimated_duration(300.0) == pytest.approx(4.0)

    def test_the_estimate_is_a_pure_function_of_the_text(self) -> None:
        # Restated as an assertion because a rate drawn from anywhere else -- a
        # clock, a random jitter, a cached measurement -- would silently break
        # RenderPlan snapshots without breaking anything else.
        line = segment("line_one", "Your phone knows.")

        assert line.estimated_duration() == line.estimated_duration()

    def test_a_wordless_line_is_just_its_pause(self) -> None:
        # Not a crash and not a fallback length: whether an all-whitespace line is
        # a defect is T1's judgement, and the estimator only reports the arithmetic.
        assert segment("line_one", " ", pause_after=0.4).estimated_duration() == 0.4


class TestMeasuredTimings:
    """``start``/``end`` are compiler output, and only meaningful as a pair."""

    def test_authored_segments_carry_no_timings(self) -> None:
        line = segment("line_one", "Your phone knows.")

        assert (line.start, line.end) == (None, None)
        assert not line.is_timed

    def test_both_ends_are_needed_to_count_as_timed(self) -> None:
        assert not segment("line_one", "Hi.", start=1.0).is_timed
        assert not segment("line_one", "Hi.", end=2.0).is_timed
        assert segment("line_one", "Hi.", start=1.0, end=2.0).is_timed

    def test_with_timing_returns_a_measured_copy(self) -> None:
        # The retime pass rebuilds segments rather than mutating them, so the
        # estimate-derived IR remains available to compare against.
        original = segment("line_one", "Your phone knows.")
        measured = original.with_timing(4.0, 5.5)

        assert (measured.start, measured.end) == (4.0, 5.5)
        assert measured.text == original.text
        assert not original.is_timed


class TestFieldGuards:
    """What the model refuses, so no later stage has to check it."""

    def test_the_default_role_is_context(self) -> None:
        assert segment("line_one", "Your phone knows.").role is NarrationRole.CONTEXT

    def test_empty_text_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            NarrationSegment(id="line_one", text="")

    @pytest.mark.parametrize("rate", [40.0, 0.0, -150.0, 401.0])
    def test_an_unspeakable_rate_is_refused(self, rate: float) -> None:
        with pytest.raises(ValidationError):
            segment("line_one", "Hi.", wpm=rate)

    def test_the_top_of_the_range_is_usable(self) -> None:
        # The upper bound is inclusive, so a deliberately rapid-fire line is legal
        # rather than one unit short of legal.
        assert segment("line_one", "Hi.", wpm=400.0).wpm == 400.0

    @pytest.mark.parametrize("pause", [-0.1, 10.5])
    def test_a_pause_outside_the_allowed_range_is_refused(self, pause: float) -> None:
        # A negative pause would pull the next line backwards over this one; a very
        # long one is dead air the T3 lint should never have to discover.
        with pytest.raises(ValidationError):
            segment("line_one", "Hi.", pause_after=pause)

    def test_a_negative_measurement_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            segment("line_one", "Hi.", start=-1.0, end=2.0)
