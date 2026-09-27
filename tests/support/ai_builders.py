"""Builders for AI-stage fixtures: briefs, outlines, scripts, plans.

The pipeline threads a chain of typed artifacts, and a test that drives it needs
one valid instance of each. These helpers supply agreeing defaults -- a brief
whose sources are all retrievable, an outline with one beat, a script with one
segment -- so a test body shows only the deviation it is about.
"""

from __future__ import annotations

from datetime import UTC, datetime

from manorem_ai.agents.models import Beat, Script, StoryOutline, VisualPlan
from manorem_ai.research import Claim, Document, ResearchBrief, SourceRef
from manorem_ir import NarrationRole, NarrationSegment

GPS_URL = "https://example.test/gps"


def gps_document() -> Document:
    return Document.of(
        GPS_URL,
        "How GPS works",
        "A receiver trilaterates its position from satellite signal timing.",
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def brief_citing(url: str = GPS_URL) -> ResearchBrief:
    """A brief with one claim citing ``url`` -- provenance passes iff it was retrieved."""
    return ResearchBrief(
        idea="How GPS determines your location.",
        claims=(
            Claim(
                id="gps_trilaterates",
                text="GPS trilaterates position from satellite timing.",
                sources=(SourceRef(url=url),),
            ),
        ),
    )


def outline(beats: int = 1) -> StoryOutline:
    return StoryOutline(
        title="How GPS Works",
        arc="question_led",
        rationale="A how-does-it-work explainer suits a question-led arc.",
        beats=tuple(
            Beat(
                id=f"beat_{i}",
                role=NarrationRole.HOOK,
                purpose="Establish the question.",
                visual_intent="Show a phone asking where it is.",
            )
            for i in range(beats)
        ),
    )


def script(segments: int = 1) -> Script:
    return Script(
        segments=tuple(
            NarrationSegment(id=f"line_{i}", text="Where are you right now?")
            for i in range(segments)
        )
    )


def plan(beat_id: str = "beat_0") -> VisualPlan:
    return VisualPlan(
        beat_id=beat_id,
        skills=("core",),
        what=("A phone.",),
        why="The phone is the subject whose location we explain.",
        when="The phone appears first and holds.",
        how="Center the phone; hold it still.",
        focus=("phone",),
        rationale="One clear subject keeps the opening legible.",
    )
