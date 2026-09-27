"""``FFmpegCommand`` -- the argv builder that is the §26 boundary for the post step.

Two things are load-bearing here and both are tested directly: the argv is a
deterministic, workspace-relative vector (so a golden can pin it and a shell can
never reinterpret it), and any path outside the job workspace is refused at
construction with :class:`~manorem_core.UnsafePathError`, never clamped.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from manorem_compositor import FFmpegCommand, FFmpegInput
from manorem_core import UnsafePathError


def test_argv_is_workspace_relative_and_ordered(tmp_path: Path) -> None:
    command = FFmpegCommand(
        workspace=tmp_path,
        output=tmp_path / "final.mp4",
        inputs=(FFmpegInput(path=tmp_path / "concat.txt", options=("-f", "concat", "-safe", "0")),),
        output_options=("-c", "copy"),
    )
    # No absolute temp path leaks in; the shape is exe, -y, per-input options then
    # -i, then output options, then output -- and every path is relative.
    assert command.argv() == [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        "concat.txt",
        "-c",
        "copy",
        "final.mp4",
    ]


def test_argv_carries_filter_complex_before_output_options(tmp_path: Path) -> None:
    command = FFmpegCommand(
        workspace=tmp_path,
        output=tmp_path / "out.mp4",
        inputs=(FFmpegInput(path=tmp_path / "a.mp4"), FFmpegInput(path=tmp_path / "b.mp4")),
        filter_complex="[0:v][1:v]concat=n=2:v=1[v]",
        output_options=("-map", "[v]"),
    )
    assert command.argv() == [
        "ffmpeg",
        "-y",
        "-i",
        "a.mp4",
        "-i",
        "b.mp4",
        "-filter_complex",
        "[0:v][1:v]concat=n=2:v=1[v]",
        "-map",
        "[v]",
        "out.mp4",
    ]


def test_overwrite_flag_can_be_dropped(tmp_path: Path) -> None:
    command = FFmpegCommand(workspace=tmp_path, output=tmp_path / "out.mp4", overwrite=False)
    assert "-y" not in command.argv()


def test_input_path_outside_workspace_is_refused(tmp_path: Path) -> None:
    outside = tmp_path.parent / "elsewhere.mp4"
    with pytest.raises(UnsafePathError):
        FFmpegCommand(
            workspace=tmp_path,
            output=tmp_path / "out.mp4",
            inputs=(FFmpegInput(path=outside),),
        )


def test_output_path_outside_workspace_is_refused(tmp_path: Path) -> None:
    with pytest.raises(UnsafePathError):
        FFmpegCommand(workspace=tmp_path, output=tmp_path.parent / "out.mp4")


def test_dotdot_escape_is_refused(tmp_path: Path) -> None:
    # A lexical check would let this through; resolving first is what catches it.
    with pytest.raises(UnsafePathError):
        FFmpegCommand(
            workspace=tmp_path,
            output=tmp_path / ".." / "out.mp4",
        )
