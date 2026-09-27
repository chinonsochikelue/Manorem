"""Deterministic pacing: same script and rate, same timeline, every time."""

from __future__ import annotations

from manorem_ai import pace_script
from manorem_core import Code
from manorem_ir import NarrationSegment
from tests.support.diag import warning_codes


def _segments(*texts: str) -> tuple[NarrationSegment, ...]:
    return tuple(NarrationSegment(id=f"s{i}", text=t) for i, t in enumerate(texts))


def test_pacing_is_deterministic() -> None:
    segments = _segments("one two three", "four five six")
    first = pace_script(segments, wpm=150.0)
    second = pace_script(segments, wpm=150.0)
    assert [s.model_dump() for s in first.segments] == [s.model_dump() for s in second.segments]
    assert first.total_seconds == second.total_seconds


def test_pacing_assigns_monotonic_timings() -> None:
    report = pace_script(_segments("a b c", "d e f g"), wpm=120.0)
    starts = [s.start for s in report.segments]
    assert all(start is not None for start in starts)
    ordered = [start for start in starts if start is not None]
    assert ordered == sorted(ordered)
    assert report.total_seconds > 0.0


def test_long_segment_warns_overflow() -> None:
    # ~200 words at 120 wpm is ~100s of speech on one beat -- an overflow lint.
    long_text = " ".join(["word"] * 200)
    report = pace_script(_segments(long_text), wpm=120.0)
    assert Code.IR301_NARRATION_OVERFLOW in warning_codes(report.diagnostics)


def test_dead_air_warns() -> None:
    segment = NarrationSegment(id="s", text="brief", pause_after=5.0)
    report = pace_script((segment,), wpm=150.0)
    assert Code.IR302_DEAD_AIR in warning_codes(report.diagnostics)
