"""Subtitles: one cue per narration segment, formatted as SRT and WebVTT.

M1's video is silent, so the caption track is the narration's only channel to the
viewer -- "one cue per segment" is the contract these tests defend. They also pin
the two format differences that matter (comma vs dot milliseconds, the ``WEBVTT``
header) against a plan compiled the real way, so the count is exercised end to end
rather than on a hand-built stub.
"""

from __future__ import annotations

from manorem_compiler import CompileOptions, compile_project
from manorem_compositor import build_subtitle_track, to_srt, to_vtt
from manorem_compositor.subtitles import SubtitleCue, SubtitleTrack
from manorem_ir import Aspect
from tests.support.diag import error_codes
from tests.support.ir_builders import make_project, valid_scene


def _plan_from_valid_scene() -> tuple[int, int]:
    """Compile the baseline scene; return (narration segment count, subtitle cues)."""
    project = make_project(valid_scene())
    plan, bag = compile_project(project, CompileOptions(aspect=Aspect.WIDESCREEN))
    assert error_codes(bag) == set(), error_codes(bag)
    segments = sum(len(scene.narration) for scene in project.episodes[0].scenes)
    track = build_subtitle_track(plan)
    return segments, len(track.cues)


def test_one_cue_per_narration_segment() -> None:
    segments, cues = _plan_from_valid_scene()
    assert cues == segments


def test_cue_indices_are_one_based_and_contiguous() -> None:
    project = make_project(valid_scene())
    plan, _ = compile_project(project, CompileOptions(aspect=Aspect.WIDESCREEN))
    track = build_subtitle_track(plan)
    assert [c.index for c in track.cues] == list(range(1, len(track.cues) + 1))


def _sample_track() -> SubtitleTrack:
    return SubtitleTrack(
        fps=15,
        cues=(
            SubtitleCue(index=1, start_frame=0, end_frame=18, text="First line."),
            SubtitleCue(index=2, start_frame=18, end_frame=45, text="Second line."),
        ),
    )


def test_srt_uses_comma_milliseconds_and_indices() -> None:
    srt = to_srt(_sample_track())
    # 18 frames at 15fps is 1.200s; SRT separates ms with a comma.
    assert "1\n00:00:00,000 --> 00:00:01,200\nFirst line.\n" in srt
    assert "2\n00:00:01,200 --> 00:00:03,000\nSecond line.\n" in srt


def test_vtt_has_header_and_dot_milliseconds_and_no_index() -> None:
    vtt = to_vtt(_sample_track())
    assert vtt.startswith("WEBVTT\n")
    assert "00:00:00.000 --> 00:00:01.200\nFirst line.\n" in vtt
    # The VTT body carries no SubRip-style integer index line.
    assert "\n1\n" not in vtt


def test_empty_track_still_renders_valid_documents() -> None:
    empty = SubtitleTrack(fps=15)
    assert to_srt(empty) == ""
    assert to_vtt(empty).startswith("WEBVTT")
