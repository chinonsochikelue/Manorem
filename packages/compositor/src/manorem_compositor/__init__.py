"""Post-production: scene concat, audio timeline, subtitles, FFmpeg muxing.

The compositor is where the frame-quantized plan becomes a container. It owns the
§26 subprocess boundary for FFmpeg (:class:`FFmpegCommand` builds an argv list,
never a shell string, and refuses any path outside the job workspace), turns the
plan's narration into SRT/WebVTT, and mux/concats the rendered scenes into one
deliverable -- reporting every failure as a ``MUX7xx`` diagnostic.
"""

from __future__ import annotations

from manorem_compositor.audio import AudioTimeline, TimedNarration, build_audio_timeline
from manorem_compositor.compositor import (
    CompositionOptions,
    CompositionResult,
    CompositionStatus,
    Compositor,
)
from manorem_compositor.ffmpeg import FFmpegCommand, FFmpegInput, workspace_relative
from manorem_compositor.subtitles import (
    SubtitleCue,
    SubtitleTrack,
    build_subtitle_track,
    to_srt,
    to_vtt,
)

__all__ = [
    "AudioTimeline",
    "CompositionOptions",
    "CompositionResult",
    "CompositionStatus",
    "Compositor",
    "FFmpegCommand",
    "FFmpegInput",
    "SubtitleCue",
    "SubtitleTrack",
    "TimedNarration",
    "build_audio_timeline",
    "build_subtitle_track",
    "to_srt",
    "to_vtt",
    "workspace_relative",
]
