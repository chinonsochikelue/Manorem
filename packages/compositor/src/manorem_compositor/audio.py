"""The narration timeline, projected onto one global frame grid.

A :class:`~manorem_compiler.plan.AudioCue` is *scene-local*: its ``start_frame``
counts from the start of the scene it lives in, because a scene is compiled in
isolation. The finished video is the scenes played back to back, so anything that
spans the whole video -- the subtitle track, and one day the mixed audio -- needs
those windows on a single clock. This module does that accumulation once, and is
the single source of truth for global narration timing; :mod:`.subtitles` is a
projection of it rather than a second copy of the arithmetic.

**Silent until voiced, by design not omission.** Every cue's ``asset`` is
``None`` in authored IR and stays that way whenever audio is disabled, so
:attr:`AudioTimeline.is_silent` is ``True`` and the compositor adds no audio
input. When the pipeline attaches synthesized clips the numbers are unchanged and
the seam stays put -- the timeline still says when each segment plays, only now
with a file behind it for the compositor to mix.
"""

from __future__ import annotations

from dataclasses import dataclass

from manorem_compiler import RenderPlan

__all__ = ["AudioTimeline", "TimedNarration", "build_audio_timeline"]


@dataclass(frozen=True, slots=True)
class TimedNarration:
    """One narration segment placed on the whole-video frame grid."""

    segment_id: str
    #: Frames from the start of the *video*, not the scene.
    start_frame: int
    duration_frames: int
    role: str
    text: str
    #: Storage key of rendered speech once TTS exists; ``None`` throughout M1.
    asset: str | None = None

    @property
    def end_frame(self) -> int:
        return self.start_frame + self.duration_frames


@dataclass(frozen=True, slots=True)
class AudioTimeline:
    """Every narration segment of a plan, on one clock, in play order."""

    fps: int
    segments: tuple[TimedNarration, ...] = ()

    @property
    def is_silent(self) -> bool:
        """No segment carries an audio asset -- the M1 state."""
        return all(segment.asset is None for segment in self.segments)


def build_audio_timeline(plan: RenderPlan) -> AudioTimeline:
    """Accumulate each scene's local audio cues onto the global frame grid.

    Scenes are laid end to end, matching :attr:`RenderPlan.total_frames` and the
    single silent video the renderer emits, so a segment's global start is the
    running total of preceding scene lengths plus its own scene-local offset.
    """
    segments: list[TimedNarration] = []
    offset = 0
    for scene in plan.scenes:
        for cue in scene.audio_cues:
            segments.append(
                TimedNarration(
                    segment_id=cue.segment_id,
                    start_frame=offset + cue.start_frame,
                    duration_frames=cue.duration_frames,
                    role=cue.role,
                    text=cue.text,
                    asset=cue.asset,
                )
            )
        offset += scene.duration_frames
    return AudioTimeline(fps=plan.fps, segments=tuple(segments))
