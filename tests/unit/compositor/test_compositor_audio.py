"""The compositor's one audio input -- a voiced plan grows a filtergraph.

A silent plan keeps M1's exact stream-copy argv (regression-safe); the moment a
plan's cues carry assets the compositor adds each WAV as an ``adelay``-ed input,
mixes them with ``amix``, and maps the mixed track beside the copied video. These
tests pin that argv shape, that the silent path is unchanged, and that an audio-mux
launch failure is reported as ``MUX703`` (distinct from the ``MUX701`` of a plain
concat), without needing ffmpeg on PATH.
"""

from __future__ import annotations

from pathlib import Path

from manorem_compiler import AudioCue, RenderPlan, ScenePlan
from manorem_compositor import CompositionOptions, Compositor
from manorem_core import Code
from manorem_ir import FormatSpec, StyleTokens

_FPS = FormatSpec().fps


def _voiced_plan() -> RenderPlan:
    return RenderPlan(
        project_id="demo",
        format=FormatSpec(),
        style=StyleTokens(),
        scenes=(
            ScenePlan(
                id="intro",
                duration_frames=90,
                background="#000000",
                audio_cues=(
                    AudioCue(
                        segment_id="a",
                        start_frame=0,
                        duration_frames=30,
                        role="hook",
                        text="one",
                        asset="audio/a.wav",
                    ),
                    AudioCue(
                        segment_id="b",
                        start_frame=30,
                        duration_frames=45,
                        role="context",
                        text="two",
                        asset="audio/b.wav",
                    ),
                ),
            ),
        ),
    )


def _silent_plan() -> RenderPlan:
    return RenderPlan(
        project_id="demo",
        format=FormatSpec(),
        style=StyleTokens(),
        scenes=(ScenePlan(id="intro", duration_frames=90, background="#000000", audio_cues=()),),
    )


def _materialize(workspace: Path, plan: RenderPlan) -> Path:
    """Write the scene video and every referenced WAV into the workspace."""
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "audio").mkdir(parents=True, exist_ok=True)
    for scene in plan.scenes:
        for cue in scene.audio_cues:
            if cue.asset is not None:
                (workspace / cue.asset).write_bytes(b"RIFF....WAVE")
    video = workspace / "scene.mp4"
    video.write_bytes(b"not a real video, but it exists")
    return video


def test_voiced_plan_argv_has_adelay_amix_and_mapped_aac(tmp_path: Path) -> None:
    plan = _voiced_plan()
    video = _materialize(tmp_path, plan)
    srt = tmp_path / "final.srt"
    srt.write_text("", encoding="utf-8")

    command = Compositor()._build_command(plan, (video,), tmp_path, srt, CompositionOptions())
    argv = command.argv()

    # Three inputs: the concat demuxer (video) plus one per voiced cue.
    assert argv.count("-i") == 3
    assert "-filter_complex" in argv
    graph = argv[argv.index("-filter_complex") + 1]
    # delay in ms comes straight from the global frame grid.
    assert f"[1:a]adelay={round(0 * 1000 / _FPS)}|{round(0 * 1000 / _FPS)}[a0]" in graph
    assert f"[2:a]adelay={round(30 * 1000 / _FPS)}|{round(30 * 1000 / _FPS)}[a1]" in graph
    assert "[a0][a1]amix=inputs=2:normalize=0[aout]" in graph
    # The copied video is mapped beside the mixed, AAC-encoded audio.
    assert argv[-9:] == [
        "-map",
        "0:v",
        "-map",
        "[aout]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "final.mp4",
    ]


def test_silent_plan_argv_is_the_unchanged_stream_copy(tmp_path: Path) -> None:
    plan = _silent_plan()
    video = _materialize(tmp_path, plan)
    srt = tmp_path / "final.srt"
    srt.write_text("", encoding="utf-8")

    command = Compositor()._build_command(plan, (video,), tmp_path, srt, CompositionOptions())
    argv = command.argv()

    assert "-filter_complex" not in argv
    assert argv.count("-i") == 1
    assert argv[-3:] == ["-c", "copy", "final.mp4"]


def test_audio_mux_launch_failure_is_mux703(tmp_path: Path) -> None:
    plan = _voiced_plan()
    video = _materialize(tmp_path, plan)

    result = Compositor().compose(
        plan,
        (video,),
        tmp_path,
        CompositionOptions(executable="manorem-no-such-ffmpeg"),
    )
    assert not result.ok
    # A voiced plan's mux failure is MUX703, never the silent concat's MUX701.
    assert [d.code for d in result.diagnostics] == [Code.MUX703_AUDIO_MUX_FAILED]


def test_silent_mux_launch_failure_is_still_mux701(tmp_path: Path) -> None:
    plan = _silent_plan()
    video = _materialize(tmp_path, plan)

    result = Compositor().compose(
        plan,
        (video,),
        tmp_path,
        CompositionOptions(executable="manorem-no-such-ffmpeg"),
    )
    assert not result.ok
    assert [d.code for d in result.diagnostics] == [Code.MUX701_COMPOSITE_FAILED]
