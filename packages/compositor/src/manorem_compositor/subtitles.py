"""Subtitles from narration: SRT and WebVTT, off the same global timeline.

M1 renders silent video, so the subtitle track is the *only* place the narration
reaches a viewer -- which makes "one cue per narration segment" a contract, not a
nicety. The cues are a straight projection of :func:`.build_audio_timeline`, so
the count and the timing cannot drift from the audio seam that will later drive
TTS.

The two formats differ in three small, fixed ways and nothing else: WebVTT opens
with a ``WEBVTT`` line, separates seconds from milliseconds with a dot where SRT
uses a comma, and omits SRT's per-cue integer index. Both are written from the
identical cue list.
"""

from __future__ import annotations

from dataclasses import dataclass

from manorem_compiler import RenderPlan
from manorem_compositor.audio import build_audio_timeline

__all__ = [
    "SubtitleCue",
    "SubtitleTrack",
    "build_subtitle_track",
    "to_srt",
    "to_vtt",
]


@dataclass(frozen=True, slots=True)
class SubtitleCue:
    """One caption: a 1-based index, its window in global frames, and its text."""

    index: int
    start_frame: int
    end_frame: int
    text: str


@dataclass(frozen=True, slots=True)
class SubtitleTrack:
    """The whole caption list, plus the fps needed to turn frames into clock time."""

    fps: int
    cues: tuple[SubtitleCue, ...] = ()


def build_subtitle_track(plan: RenderPlan) -> SubtitleTrack:
    """Project the plan's narration onto a 1-based, globally-timed cue list."""
    timeline = build_audio_timeline(plan)
    cues = tuple(
        SubtitleCue(
            index=i,
            start_frame=segment.start_frame,
            end_frame=segment.end_frame,
            text=segment.text,
        )
        for i, segment in enumerate(timeline.segments, start=1)
    )
    return SubtitleTrack(fps=timeline.fps, cues=cues)


def _timestamp(frame: int, fps: int, *, ms_sep: str) -> str:
    """``HH:MM:SS<sep>mmm`` for a frame index, rounding to the nearest millisecond."""
    total_ms = round(frame * 1000 / fps)
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    seconds, milliseconds = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{ms_sep}{milliseconds:03d}"


def to_srt(track: SubtitleTrack) -> str:
    """Render the track as SubRip (``.srt``): index, comma-millisecond times, text."""
    blocks: list[str] = []
    for cue in track.cues:
        start = _timestamp(cue.start_frame, track.fps, ms_sep=",")
        end = _timestamp(cue.end_frame, track.fps, ms_sep=",")
        blocks.append(f"{cue.index}\n{start} --> {end}\n{cue.text}\n")
    return "\n".join(blocks)


def to_vtt(track: SubtitleTrack) -> str:
    """Render the track as WebVTT (``.vtt``): header, dot-millisecond times, text."""
    blocks: list[str] = ["WEBVTT\n"]
    for cue in track.cues:
        start = _timestamp(cue.start_frame, track.fps, ms_sep=".")
        end = _timestamp(cue.end_frame, track.fps, ms_sep=".")
        blocks.append(f"{start} --> {end}\n{cue.text}\n")
    return "\n".join(blocks)
