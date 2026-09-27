"""Timing expressions.

Timing is *relative and symbolic* in the IR: an author says "when the narration
about satellites starts" rather than "t = 4.2". Compiler pass P4 resolves these
into absolute frame numbers. This is what makes narration synchronization a
first-class property instead of a manual bookkeeping exercise.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from manorem_core import Slug


class AbsoluteTime(BaseModel):
    """A fixed offset from the start of the scene."""

    model_config = ConfigDict(frozen=True)

    at: Literal["absolute"] = "absolute"
    seconds: float = Field(ge=0.0, le=3600.0)


class AfterCue(BaseModel):
    """Starts once another cue has finished, plus an optional gap."""

    model_config = ConfigDict(frozen=True)

    at: Literal["after"] = "after"
    cue: Slug
    gap: float = Field(default=0.0, ge=-60.0, le=60.0)


class WithCue(BaseModel):
    """Starts alongside another cue, offset by ``offset`` seconds."""

    model_config = ConfigDict(frozen=True)

    at: Literal["with"] = "with"
    cue: Slug
    offset: float = Field(default=0.0, ge=-60.0, le=60.0)


class NarrationTime(BaseModel):
    """Anchored to a narration segment -- the mechanism that keeps visuals and
    voice-over in sync when narration timings change."""

    model_config = ConfigDict(frozen=True)

    at: Literal["narration"] = "narration"
    segment: Slug
    edge: Literal["start", "end"] = "start"
    offset: float = Field(default=0.0, ge=-60.0, le=60.0)


TimeExpr = Annotated[
    AbsoluteTime | AfterCue | WithCue | NarrationTime,
    Field(discriminator="at"),
]


class SecondsDuration(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["seconds"] = "seconds"
    seconds: float = Field(gt=0.0, le=3600.0)


class NarrationDuration(BaseModel):
    """Lasts exactly as long as a narration segment."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["narration"] = "narration"
    segment: Slug


class AutoDuration(BaseModel):
    """Let the operation's declared default decide.

    Keeps IR terse and lets a skill tune pacing for its own operations.
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["auto"] = "auto"


DurationExpr = Annotated[
    SecondsDuration | NarrationDuration | AutoDuration,
    Field(discriminator="kind"),
]


def at_seconds(seconds: float) -> AbsoluteTime:
    return AbsoluteTime(seconds=seconds)


def after(cue: str, gap: float = 0.0) -> AfterCue:
    return AfterCue(cue=cue, gap=gap)


def with_cue(cue: str, offset: float = 0.0) -> WithCue:
    return WithCue(cue=cue, offset=offset)


def at_narration(
    segment: str, edge: Literal["start", "end"] = "start", offset: float = 0.0
) -> NarrationTime:
    return NarrationTime(segment=segment, edge=edge, offset=offset)


def lasting(seconds: float) -> SecondsDuration:
    return SecondsDuration(seconds=seconds)


def spanning(segment: str) -> NarrationDuration:
    return NarrationDuration(segment=segment)


AUTO = AutoDuration()


def referenced_cue(expr: TimeExpr) -> str | None:
    """Cue id this expression depends on, if any. Used to build the timing DAG."""
    if isinstance(expr, AfterCue | WithCue):
        return expr.cue
    return None


def referenced_segment(expr: TimeExpr | DurationExpr) -> str | None:
    """Narration segment this expression depends on, if any."""
    if isinstance(expr, NarrationTime | NarrationDuration):
        return expr.segment
    return None
