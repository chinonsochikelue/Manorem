"""``retime_narration`` -- measured audio becomes the narration clock.

This is the pure IR transform at the heart of M3: given a per-segment duration map
it lays the scene's segments end to end on a scene-local 0-based clock, each window
being ``measured + pause_after`` wide, and writes the result into ``start``/``end``
so :func:`narration_windows` later takes its real-timing branch. The tests pin the
end-to-end arithmetic (including ``pause_after``), the partial-map fallback the
primitive is allowed to express, that it returns a fresh frozen scene, and that a
retimed scene still validates at every tier.
"""

from __future__ import annotations

import pytest

from manorem_ir import narration_windows, retime_narration, validate_project
from tests.support.ir_builders import make_project, make_scene, segment, valid_scene


def _scene_two_lines() -> object:
    return make_scene(
        intent="Two lines so the cursor has to advance.",
        narration=[
            segment("line_one", "aaaa", pause_after=0.5),  # 4 chars
            segment("line_two", "bbbbbb", pause_after=0.25),  # 6 chars
        ],
    )


def test_windows_are_laid_end_to_end_with_pause_after() -> None:
    scene = _scene_two_lines()
    retimed = retime_narration(scene, {"line_one": 2.0, "line_two": 3.0})

    first, second = retimed.narration
    # line_one: [0, 2.0 + 0.5]; line_two starts where line_one ended.
    assert first.start == pytest.approx(0.0)
    assert first.end == pytest.approx(2.5)
    assert second.start == pytest.approx(2.5)
    assert second.end == pytest.approx(2.5 + 3.0 + 0.25)


def test_measured_timing_wins_over_the_wpm_estimate() -> None:
    scene = _scene_two_lines()
    retimed = retime_narration(scene, {"line_one": 2.0, "line_two": 3.0})

    # narration_windows must honour the stored start/end, not re-estimate from words.
    windows = narration_windows(retimed, wpm=150.0)
    assert windows["line_one"].end == pytest.approx(2.5)
    # The WPM estimate for a one-word line would be (1/150)*60 + 0.5 ~= 0.9, not 2.5.
    assert windows["line_one"].end != pytest.approx(0.9)


def test_a_partial_map_leaves_other_segments_on_wpm() -> None:
    scene = _scene_two_lines()
    retimed = retime_narration(scene, {"line_two": 3.0})

    first, second = retimed.narration
    # line_one was absent: its start/end stay None (WPM fallback downstream).
    assert first.start is None and first.end is None
    # The cursor still advanced by line_one's own estimate, so line_two is placed
    # after it rather than at zero.
    assert second.start == pytest.approx(first.estimated_duration())
    assert second.end == pytest.approx(first.estimated_duration() + 3.0 + 0.25)


def test_empty_map_is_full_wpm_fallback() -> None:
    scene = _scene_two_lines()
    retimed = retime_narration(scene, {})
    assert all(seg.start is None and seg.end is None for seg in retimed.narration)


def test_retime_returns_a_fresh_frozen_scene() -> None:
    scene = _scene_two_lines()
    retimed = retime_narration(scene, {"line_one": 2.0, "line_two": 3.0})

    assert retimed is not scene
    # The source scene is untouched -- the primitive is pure.
    assert all(seg.start is None for seg in scene.narration)
    with pytest.raises(ValueError, match=r"frozen|Instance is frozen"):
        retimed.narration[0].start = 9.0  # type: ignore[misc]


def test_a_retimed_scene_still_validates_cleanly() -> None:
    # Writing real windows must not break any validation tier -- the guardrail that
    # keeps timing a safe, additive change rather than a new way to make bad IR.
    scene = valid_scene()
    durations = {seg.id: 1.0 for seg in scene.narration}
    retimed = retime_narration(scene, durations)

    bag = validate_project(make_project(retimed))
    assert not bag.has_errors, bag.errors
