"""Deterministic narration pacing -- timings the model never gets to invent.

Where the segments *are* is a language decision; how long they *take* is
arithmetic, and arithmetic belongs here, not in a prompt. Given a script and a
speaking rate, this walks the segments in order, assigns each a start and end from
its own word count, and returns the timed script plus any pacing lints it noticed.

Determinism is the whole point: the same script and the same rate always produce
the same timeline, which is what lets a RenderPlan built downstream be snapshot
-stable. The lints are ``IR3xx`` warnings -- advisory, promotable to errors by
policy later -- because a script that reads well can still pace badly, and that is
worth surfacing before it reaches the compiler.
"""

from __future__ import annotations

from dataclasses import dataclass

from manorem_core import Code, DiagnosticBag, pointer
from manorem_ir import DEFAULT_WPM, NarrationSegment

__all__ = ["PacingReport", "pace_script"]

#: A single segment longer than this reads as a wall of narration over one static
#: frame -- usually a sign the beat should be split.
_LONG_SEGMENT_S = 22.0

#: A trailing pause longer than this is dead air unless something is landing.
_LONG_PAUSE_S = 3.0


@dataclass(frozen=True, slots=True)
class PacingReport:
    """Segments with derived timings, the total, and the lints that fired."""

    segments: tuple[NarrationSegment, ...]
    total_seconds: float
    diagnostics: DiagnosticBag


def pace_script(
    segments: tuple[NarrationSegment, ...],
    *,
    wpm: float = DEFAULT_WPM,
    target_seconds: float | None = None,
) -> PacingReport:
    """Assign start/end to each segment and flag pacing problems.

    ``target_seconds`` is an optional budget (e.g. a scene's ``duration_hint``);
    exceeding it is an overflow lint, not a hard failure -- the scheduler will
    still extend to fit rather than truncate the voice-over.
    """
    bag = DiagnosticBag()
    timed: list[NarrationSegment] = []
    cursor = 0.0

    for index, segment in enumerate(segments):
        duration = segment.estimated_duration(wpm)
        speaking = duration - segment.pause_after
        start = cursor
        end = start + speaking
        timed.append(segment.with_timing(start, end))
        cursor = start + duration

        if speaking > _LONG_SEGMENT_S:
            bag.warn(
                Code.IR301_NARRATION_OVERFLOW,
                f"segment {segment.id!r} runs {speaking:.1f}s of narration on one beat",
                pointer=pointer("segments", index),
                object_id=segment.id,
                hint="Consider splitting this into two beats so the visual can change.",
            )
        if segment.pause_after > _LONG_PAUSE_S:
            bag.warn(
                Code.IR302_DEAD_AIR,
                f"segment {segment.id!r} holds {segment.pause_after:.1f}s of silence after it",
                pointer=pointer("segments", index),
                object_id=segment.id,
            )

    if target_seconds is not None and cursor > target_seconds:
        bag.warn(
            Code.IR301_NARRATION_OVERFLOW,
            f"narration totals {cursor:.1f}s against a {target_seconds:.1f}s budget",
            pointer=pointer("segments"),
        )

    return PacingReport(segments=tuple(timed), total_seconds=cursor, diagnostics=bag)
