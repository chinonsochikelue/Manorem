"""``sample_frames`` -- the deterministic choice of which frames a render samples.

The rule is stated once in the module docstring and pinned here: frame 0 and the
last frame always, one every ``fps / rate`` between them, endpoints-only for a
non-positive rate. It has to be deterministic because two renders of the same plan
must sample the same instants for their manifests to compare.
"""

from __future__ import annotations

import pytest

from manorem_renderer import sample_frames


def test_includes_both_endpoints() -> None:
    marks = sample_frames(53, 15, 1.0)
    assert marks[0] == 0
    assert marks[-1] == 52


def test_is_sorted_and_unique() -> None:
    marks = sample_frames(53, 15, 1.0)
    assert list(marks) == sorted(set(marks))


def test_one_per_second_at_unit_rate() -> None:
    # 15 fps, one sample per second -> every 15th frame, plus the last.
    marks = sample_frames(46, 15, 1.0)
    assert marks == (0, 15, 30, 45)


def test_higher_rate_samples_more_densely() -> None:
    sparse = sample_frames(60, 30, 1.0)
    dense = sample_frames(60, 30, 5.0)
    assert len(dense) > len(sparse)


def test_non_positive_rate_keeps_only_endpoints() -> None:
    assert sample_frames(53, 15, 0.0) == (0, 52)
    assert sample_frames(53, 15, -4.0) == (0, 52)


@pytest.mark.parametrize("duration", [1, 0, -3])
def test_degenerate_duration_yields_single_frame(duration: int) -> None:
    assert sample_frames(duration, 15, 1.0) == (0,)


def test_deterministic() -> None:
    assert sample_frames(200, 24, 2.0) == sample_frames(200, 24, 2.0)
