"""``Compositor`` -- concat, captions and mux, with every failure a ``MUX7xx``.

The compositor is mostly wiring, so these tests target its contract rather than
FFmpeg itself: an empty or missing input is a ``MUX702``; a mux that cannot run
is a ``MUX701``; the caption sidecars are written whether or not the video
survives. The one test that needs a working FFmpeg is guarded by a skip so CI
stays green without it.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from manorem_compiler import CompileOptions, RenderPlan, compile_project
from manorem_compositor import CompositionOptions, Compositor
from manorem_core import Code
from manorem_ir import Aspect
from tests.support.ir_builders import make_project, valid_scene

_HAS_FFMPEG = shutil.which("ffmpeg") is not None


def _plan() -> RenderPlan:
    plan, _ = compile_project(make_project(valid_scene()), CompileOptions(aspect=Aspect.WIDESCREEN))
    return plan


def _fake_video(workspace: Path, name: str = "scene.mp4") -> Path:
    path = workspace / name
    path.write_bytes(b"not a real video, but it exists")
    return path


def test_empty_inputs_is_mux702(tmp_path: Path) -> None:
    result = Compositor().compose(_plan(), (), tmp_path)
    assert not result.ok
    assert result.video is None
    assert [d.code for d in result.diagnostics] == [Code.MUX702_MISSING_INPUT]


def test_missing_input_file_is_mux702(tmp_path: Path) -> None:
    result = Compositor().compose(_plan(), (tmp_path / "absent.mp4",), tmp_path)
    assert not result.ok
    assert [d.code for d in result.diagnostics] == [Code.MUX702_MISSING_INPUT]


def test_unlaunchable_ffmpeg_is_mux701(tmp_path: Path) -> None:
    video = _fake_video(tmp_path)
    result = Compositor().compose(
        _plan(),
        (video,),
        tmp_path,
        CompositionOptions(executable="manorem-no-such-ffmpeg"),
    )
    assert not result.ok
    assert [d.code for d in result.diagnostics] == [Code.MUX701_COMPOSITE_FAILED]


def test_subtitles_are_written_even_when_the_mux_fails(tmp_path: Path) -> None:
    video = _fake_video(tmp_path)
    result = Compositor().compose(
        _plan(),
        (video,),
        tmp_path,
        CompositionOptions(executable="manorem-no-such-ffmpeg"),
    )
    assert result.subtitles_srt is not None and result.subtitles_srt.exists()
    assert result.subtitles_vtt is not None and result.subtitles_vtt.exists()
    assert result.subtitles_vtt.read_text(encoding="utf-8").startswith("WEBVTT")


@pytest.mark.skipif(not _HAS_FFMPEG, reason="ffmpeg not on PATH")
def test_composites_a_single_video_when_ffmpeg_present(tmp_path: Path) -> None:
    source = tmp_path / "scene.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=64x64:r=15",
            "-t",
            "0.5",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        capture_output=True,
        timeout=60,
        check=True,
    )
    result = Compositor().compose(_plan(), (source,), tmp_path)
    assert result.ok
    assert result.video is not None and result.video.exists()
    assert result.diagnostics == ()
