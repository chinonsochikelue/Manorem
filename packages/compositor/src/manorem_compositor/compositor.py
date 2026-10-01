"""Post-production: concat the rendered scenes, write subtitles, mux to one file.

This is the last stage of the pipeline and the one that finally leaves the
frame-grid world for a container. Its job is small and its rules are strict:
everything it touches lives inside a single job workspace, every FFmpeg call is
an argv list built by :class:`~manorem_compositor.FFmpegCommand`, and every
failure comes back as a ``MUX7xx`` :class:`~manorem_core.Diagnostic` rather than
an exception or a half-written file.

**One combined video today, N scenes tomorrow.** M1's renderer emits a single
silent video for the whole plan, so the common case is a one-element
``videos``. The concat demuxer handles one input as happily as many, so the same
code path scales to per-scene rendering later without a rewrite.

**Subtitles are always written; audio when there is any.** The SRT and WebVTT
sidecars are produced from the plan's narration on every call, success or
failure, because they are a channel to the viewer that survives a mux failure.
Audio mixing (:mod:`.audio`) stays dormant while every narration segment's
``asset`` is ``None`` -- the silent plan keeps M1's exact ``-c copy`` argv -- and
switches on the moment the pipeline attaches synthesized clips: each voiced
segment becomes an ``adelay``-ed input mixed into one track and muxed over the
copied video, with any audio-stage failure reported as ``MUX703``.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from manorem_compiler import RenderPlan
from manorem_compositor.audio import AudioTimeline, build_audio_timeline
from manorem_compositor.ffmpeg import FFmpegCommand, FFmpegInput, workspace_relative
from manorem_compositor.subtitles import build_subtitle_track, to_srt, to_vtt
from manorem_core import Code, Diagnostic, Severity

__all__ = [
    "CompositionOptions",
    "CompositionResult",
    "CompositionStatus",
    "Compositor",
]


class CompositionStatus(StrEnum):
    """Whether the mux ran to completion. Quality is not this stage's concern."""

    OK = "ok"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class CompositionOptions:
    """Knobs that do not change what the video says, only how it is muxed."""

    #: Burn captions into the pixels instead of writing a soft sidecar. Off by
    #: default: sidecars stay editable and re-timeable, burn-in does not.
    burn_in_subtitles: bool = False
    #: FFmpeg program name, resolved on ``PATH``.
    executable: str = "ffmpeg"
    #: Wall-clock ceiling for the mux subprocess.
    timeout_s: float = 300.0


@dataclass(frozen=True, slots=True)
class CompositionResult:
    """What the compositor produced: the muxed file, its captions, and why if not."""

    status: CompositionStatus
    #: The final container, or ``None`` when the mux did not complete.
    video: Path | None
    #: Sidecar captions, written on every call regardless of the video's fate.
    subtitles_srt: Path | None
    subtitles_vtt: Path | None
    diagnostics: tuple[Diagnostic, ...] = field(default_factory=tuple)
    duration_ms: int = 0

    @property
    def ok(self) -> bool:
        return self.status is CompositionStatus.OK


class Compositor:
    """Joins rendered scenes and their captions into one deliverable."""

    def compose(
        self,
        plan: RenderPlan,
        videos: tuple[Path, ...],
        workspace: Path,
        opts: CompositionOptions | None = None,
    ) -> CompositionResult:
        """Concat ``videos``, write SRT/VTT from ``plan``, and mux into ``workspace``.

        ``videos`` must already live inside ``workspace`` -- the pipeline places
        renderer output there. An empty list or a path that does not exist is a
        ``MUX702``; a failed or timed-out FFmpeg call is a ``MUX701``. The caption
        sidecars are written before FFmpeg runs, so they survive a mux failure.
        """
        start = time.monotonic()
        options = opts or CompositionOptions()

        srt_path, vtt_path = self._write_subtitles(plan, workspace)

        missing = self._missing_inputs(videos)
        if missing is not None:
            return self._failed(missing, srt_path, vtt_path, start)

        timeline = build_audio_timeline(plan)
        command = self._build_command(plan, videos, workspace, srt_path, options)
        fail_code = (
            Code.MUX701_COMPOSITE_FAILED if timeline.is_silent else Code.MUX703_AUDIO_MUX_FAILED
        )
        diagnostic = self._run(command, workspace, options, fail_code)
        if diagnostic is not None:
            return self._failed(diagnostic, srt_path, vtt_path, start)

        return CompositionResult(
            status=CompositionStatus.OK,
            video=command.output,
            subtitles_srt=srt_path,
            subtitles_vtt=vtt_path,
            duration_ms=int((time.monotonic() - start) * 1000),
        )

    def _write_subtitles(self, plan: RenderPlan, workspace: Path) -> tuple[Path, Path]:
        track = build_subtitle_track(plan)
        srt_path = workspace / "final.srt"
        vtt_path = workspace / "final.vtt"
        workspace_relative(workspace, srt_path)
        workspace_relative(workspace, vtt_path)
        workspace.mkdir(parents=True, exist_ok=True)
        srt_path.write_text(to_srt(track), encoding="utf-8")
        vtt_path.write_text(to_vtt(track), encoding="utf-8")
        return srt_path, vtt_path

    def _missing_inputs(self, videos: tuple[Path, ...]) -> Diagnostic | None:
        if not videos:
            return Diagnostic(
                code=Code.MUX702_MISSING_INPUT,
                severity=Severity.ERROR,
                message="no scene videos to composite",
            )
        for video in videos:
            if not video.exists():
                return Diagnostic(
                    code=Code.MUX702_MISSING_INPUT,
                    severity=Severity.ERROR,
                    message=f"scene video does not exist: {video.name}",
                )
        return None

    def _build_command(
        self,
        plan: RenderPlan,
        videos: tuple[Path, ...],
        workspace: Path,
        srt_path: Path,
        options: CompositionOptions,
    ) -> FFmpegCommand:
        """Build the mux command, adding an audio filtergraph when the plan is voiced.

        Input 0 is always the concat demuxer (video). A silent plan keeps M1's exact
        argv -- ``-c copy`` (or the burn-in video filter) and no audio -- so its
        golden is regression-safe. When :func:`build_audio_timeline` reports voiced
        segments, each becomes an ``adelay``-ed ``-i`` input, they are ``amix``-ed
        into one track, and the output maps the copied video alongside the mixed
        audio (``-c:a aac``).
        """
        concat_list = workspace / "concat.txt"
        lines = [f"file '{workspace_relative(workspace, v)}'" for v in videos]
        concat_list.write_text("\n".join(lines) + "\n", encoding="utf-8")
        concat_input = FFmpegInput(path=concat_list, options=("-f", "concat", "-safe", "0"))

        timeline = build_audio_timeline(plan)
        if timeline.is_silent:
            return self._build_silent_command(concat_input, workspace, srt_path, options)
        return self._build_audio_command(timeline, concat_input, workspace, srt_path, options)

    def _build_silent_command(
        self,
        concat_input: FFmpegInput,
        workspace: Path,
        srt_path: Path,
        options: CompositionOptions,
    ) -> FFmpegCommand:
        """M1's exact path: stream-copy the concat, or burn captions into the pixels."""
        if options.burn_in_subtitles:
            subtitle_name = workspace_relative(workspace, srt_path)
            output_options: tuple[str, ...] = (
                "-vf",
                f"subtitles={subtitle_name}",
                "-pix_fmt",
                "yuv420p",
            )
        else:
            # Stream copy: the renderer's scenes share one codec, so concat needs
            # no re-encode when we are not burning captions into the pixels.
            output_options = ("-c", "copy")

        return FFmpegCommand(
            workspace=workspace,
            output=workspace / "final.mp4",
            inputs=(concat_input,),
            output_options=output_options,
            executable=options.executable,
        )

    def _build_audio_command(
        self,
        timeline: AudioTimeline,
        concat_input: FFmpegInput,
        workspace: Path,
        srt_path: Path,
        options: CompositionOptions,
    ) -> FFmpegCommand:
        """Mux the voiced segments over the copied video on one global clock.

        Each voiced :class:`~manorem_compositor.audio.TimedNarration` is delayed to
        its global ``start_frame`` with ``adelay`` (one value per channel) and the
        delayed streams are summed by ``amix`` with ``normalize=0`` so a segment's
        loudness does not sag as the count grows. The video is stream-copied (or
        subtitle-burned, when asked) and mapped beside the mixed ``[aout]``; the
        delays come straight from the frame grid, so audio lands exactly where the
        subtitles say it does.
        """
        voiced = [seg for seg in timeline.segments if seg.asset is not None]
        inputs = [concat_input]
        filters: list[str] = []

        if options.burn_in_subtitles:
            subtitle_name = workspace_relative(workspace, srt_path)
            filters.append(f"[0:v]subtitles={subtitle_name}[v]")
            video_map = "[v]"
            video_options: tuple[str, ...] = ("-pix_fmt", "yuv420p")
        else:
            video_map = "0:v"
            video_options = ("-c:v", "copy")

        for index, seg in enumerate(voiced):
            assert seg.asset is not None  # filtered above
            inputs.append(FFmpegInput(path=workspace / seg.asset))
            delay_ms = round(seg.start_frame * 1000 / timeline.fps)
            filters.append(f"[{index + 1}:a]adelay={delay_ms}|{delay_ms}[a{index}]")
        mixed = "".join(f"[a{index}]" for index in range(len(voiced)))
        filters.append(f"{mixed}amix=inputs={len(voiced)}:normalize=0[aout]")

        return FFmpegCommand(
            workspace=workspace,
            output=workspace / "final.mp4",
            inputs=tuple(inputs),
            filter_complex=";".join(filters),
            output_options=(
                "-map",
                video_map,
                "-map",
                "[aout]",
                *video_options,
                "-c:a",
                "aac",
            ),
            executable=options.executable,
        )

    def _run(
        self,
        command: FFmpegCommand,
        workspace: Path,
        options: CompositionOptions,
        fail_code: Code = Code.MUX701_COMPOSITE_FAILED,
    ) -> Diagnostic | None:
        """Run the mux; return ``fail_code`` on any failure, or ``None`` on success.

        ``fail_code`` is ``MUX701`` for a plain concat and ``MUX703`` once an audio
        filtergraph is in play, so a mix/mux failure is distinguishable from a
        video-only concat failure without inspecting the argv.
        """
        try:
            completed = subprocess.run(
                command.argv(),
                cwd=workspace,
                capture_output=True,
                timeout=options.timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return Diagnostic(
                code=fail_code,
                severity=Severity.ERROR,
                message=f"ffmpeg timed out after {options.timeout_s:g}s while compositing",
            )
        except OSError as exc:
            return Diagnostic(
                code=fail_code,
                severity=Severity.ERROR,
                message=f"could not launch ffmpeg ({options.executable!r}): {exc}",
            )
        if completed.returncode != 0 or not command.output.exists():
            return Diagnostic(
                code=fail_code,
                severity=Severity.ERROR,
                message=f"ffmpeg exited {completed.returncode} while compositing",
            )
        return None

    def _failed(
        self, diagnostic: Diagnostic, srt_path: Path, vtt_path: Path, start: float
    ) -> CompositionResult:
        return CompositionResult(
            status=CompositionStatus.FAILED,
            video=None,
            subtitles_srt=srt_path,
            subtitles_vtt=vtt_path,
            diagnostics=(diagnostic,),
            duration_ms=int((time.monotonic() - start) * 1000),
        )
