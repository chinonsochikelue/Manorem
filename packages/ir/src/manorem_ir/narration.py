"""Narration segments.

Narration is part of the IR, not an afterthought bolted on at compositing time:
cues anchor to segments symbolically, so re-timing the voice-over re-times the
visuals rather than desynchronizing them.

Timings are *derived*, never authored. In M1 they come from a words-per-minute
model; when TTS lands they come from real audio durations. Either way the
producer is :mod:`manorem_compiler`, and ``start``/``end`` are left ``None``
in hand-written IR.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field

from manorem_core import Slug
from manorem_ir.enums import NarrationRole

_WORD_RE = re.compile(r"\S+")

#: Fallback speaking rate. Explainer narration sits well below conversational
#: speed; the default is deliberately unhurried.
DEFAULT_WPM = 150.0


class NarrationSegment(BaseModel):
    """One spoken beat within a scene."""

    model_config = ConfigDict(frozen=True)

    id: Slug
    role: NarrationRole = NarrationRole.CONTEXT
    text: str = Field(min_length=1, max_length=1200)
    wpm: float | None = Field(
        default=None,
        gt=40.0,
        le=400.0,
        description="Per-segment speaking-rate override; falls back to the project rate.",
    )
    #: Object ids this line talks about. Feeds the future narration/visual
    #: mismatch check -- a segment naming a satellite while nothing satellite-ish
    #: is on screen is a real defect, and it is only detectable if the link is
    #: recorded here at authoring time.
    mentions: list[Slug] = Field(default_factory=list, max_length=32)
    #: Research claim ids backing this line, for traceability back to sources.
    claims: list[str] = Field(default_factory=list, max_length=32)
    #: Silence held after the line, e.g. to let a visual land.
    pause_after: float = Field(default=0.3, ge=0.0, le=10.0)

    # --- derived by the compiler; absent in authored IR ---------------------
    start: float | None = Field(default=None, ge=0.0, le=3600.0)
    end: float | None = Field(default=None, ge=0.0, le=3600.0)

    @property
    def word_count(self) -> int:
        return len(_WORD_RE.findall(self.text))

    def estimated_duration(self, default_wpm: float = DEFAULT_WPM) -> float:
        """Speaking time plus the trailing pause, in seconds.

        Deliberately a pure function of the text: the same script always yields
        the same timeline, which is what makes RenderPlan snapshots stable.
        """
        rate = self.wpm if self.wpm is not None else default_wpm
        return (self.word_count / rate) * 60.0 + self.pause_after

    @property
    def is_timed(self) -> bool:
        return self.start is not None and self.end is not None

    def with_timing(self, start: float, end: float) -> NarrationSegment:
        return self.model_copy(update={"start": start, "end": end})
