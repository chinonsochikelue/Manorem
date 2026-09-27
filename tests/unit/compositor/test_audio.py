"""``build_audio_timeline`` -- scene-local cues accumulated onto one clock.

The one thing that can go wrong here is the offset arithmetic: an ``AudioCue``
counts frames from its own scene, and the video plays scenes end to end, so a
segment in scene two must be pushed past scene one's whole length. These tests
pin that, and the M1 invariant that the timeline is silent until TTS exists.
"""

from __future__ import annotations

from manorem_compiler import AudioCue, RenderPlan, ScenePlan
from manorem_compositor import build_audio_timeline
from manorem_ir import FormatSpec, StyleTokens


def _plan(*scenes: ScenePlan) -> RenderPlan:
    return RenderPlan(
        project_id="demo",
        format=FormatSpec(),
        style=StyleTokens(),
        scenes=scenes,
    )


def _scene(scene_id: str, duration_frames: int, *cues: AudioCue) -> ScenePlan:
    return ScenePlan(
        id=scene_id,
        duration_frames=duration_frames,
        background="#000000",
        audio_cues=cues,
    )


def test_single_scene_offsets_are_scene_local() -> None:
    plan = _plan(
        _scene(
            "intro",
            90,
            AudioCue(segment_id="a", start_frame=0, duration_frames=30, role="hook", text="one"),
            AudioCue(
                segment_id="b", start_frame=30, duration_frames=45, role="context", text="two"
            ),
        )
    )
    timeline = build_audio_timeline(plan)
    assert [(s.segment_id, s.start_frame, s.end_frame) for s in timeline.segments] == [
        ("a", 0, 30),
        ("b", 30, 75),
    ]


def test_second_scene_cues_are_pushed_past_the_first() -> None:
    plan = _plan(
        _scene(
            "intro",
            90,
            AudioCue(segment_id="a", start_frame=10, duration_frames=20, role="hook", text="one"),
        ),
        _scene(
            "next",
            60,
            AudioCue(segment_id="b", start_frame=5, duration_frames=25, role="context", text="two"),
        ),
    )
    timeline = build_audio_timeline(plan)
    # Scene one is 90 frames long, so "b"'s scene-local 5 lands at global 95.
    assert [(s.segment_id, s.start_frame) for s in timeline.segments] == [("a", 10), ("b", 95)]


def test_timeline_is_silent_while_every_asset_is_none() -> None:
    plan = _plan(
        _scene(
            "intro",
            30,
            AudioCue(segment_id="a", start_frame=0, duration_frames=30, role="hook", text="one"),
        )
    )
    assert build_audio_timeline(plan).is_silent is True


def test_fps_is_carried_from_the_plan() -> None:
    plan = _plan(_scene("intro", 30))
    assert build_audio_timeline(plan).fps == FormatSpec().fps
