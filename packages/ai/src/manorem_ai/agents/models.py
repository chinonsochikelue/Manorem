"""The typed hand-offs between pipeline stages.

Each agent has a single input type and a single output type, and those types live
here so the pipeline reads as a chain of total functions rather than a bag of
dicts. Everything is a frozen Pydantic model: it is what the provider validates a
response into, what the content-addressed store hashes, and what the next stage
consumes.

The schemas are also the model's instructions in structural form. ``VisualPlan``
makes §12's what / why / when / how / focus / persist *required fields* -- a plan
that omits the reasoning does not validate -- because the surest way to make a
model plan rather than free-associate is to refuse a response that skipped the
plan.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from manorem_core import Slug
from manorem_ir import NarrationRole, NarrationSegment

__all__ = ["Beat", "Script", "StoryOutline", "VisualPlan"]


class Beat(BaseModel):
    """One story beat: a role in the arc and what it is there to accomplish."""

    model_config = ConfigDict(frozen=True)

    id: Slug
    role: NarrationRole
    purpose: str = Field(min_length=1, max_length=600)
    #: Ids of the research claims this beat rests on, for traceability.
    claims_used: tuple[str, ...] = ()
    #: What the beat should show, in the director's words -- the seed the visual
    #: planner turns into concrete objects and cues.
    visual_intent: str = Field(min_length=1, max_length=600)


class StoryOutline(BaseModel):
    """The chosen arc and its beats, with the reason the arc fits this subject.

    ``arc`` and ``rationale`` are required so a run cannot silently default every
    subject to the same template -- picking an arc is a decision the story agent
    must own and justify.
    """

    model_config = ConfigDict(frozen=True)

    title: str = Field(min_length=1, max_length=200)
    arc: str = Field(min_length=1, max_length=60)
    rationale: str = Field(min_length=1, max_length=800)
    beats: tuple[Beat, ...] = Field(min_length=1)


class Script(BaseModel):
    """The narration, as a flat list of segments in delivery order.

    Timings are deliberately absent here: they are computed by the deterministic
    :mod:`~manorem_ai.pacing` model, never authored by the language model, so the
    same script always yields the same timeline.
    """

    model_config = ConfigDict(frozen=True)

    segments: tuple[NarrationSegment, ...] = Field(min_length=1)


class VisualPlan(BaseModel):
    """A beat's visualization intent -- the required reasoning, before any IR.

    Every field is required. A plan that cannot say *why* it shows what it shows,
    or *what* the viewer should focus on, is not a plan the IR generator should be
    asked to realize.
    """

    model_config = ConfigDict(frozen=True)

    beat_id: Slug
    #: Which skill packs the scene should be authored against.
    skills: tuple[str, ...] = Field(min_length=1)
    what: tuple[str, ...] = Field(min_length=1, description="The elements to depict.")
    why: str = Field(min_length=1, max_length=800, description="Why these, for this beat.")
    when: str = Field(min_length=1, max_length=800, description="Ordering and timing intent.")
    how: str = Field(min_length=1, max_length=800, description="Layout and animation approach.")
    focus: tuple[str, ...] = Field(min_length=1, description="What the eye should land on.")
    persist: tuple[str, ...] = Field(
        default=(), description="What stays on screen across the beat."
    )
    rationale: str = Field(min_length=1, max_length=800)
