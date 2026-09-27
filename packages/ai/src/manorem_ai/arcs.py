"""Named story arcs: the shapes a video's narration can take.

A single template applied to every subject produces identical, forgettable videos
-- so the story agent *chooses* an arc and must justify the choice. These are the
menu it picks from. Each arc is an ordered sequence of narration roles; the agent
need not fill every role, but the order is the arc's argument for how understanding
should unfold.

The arcs are data, not prose in a prompt, so the same set is available to the story
agent's prompt (rendered by :func:`arc_menu`) and to validation (an outline naming
an unknown arc is a caught error, not a silent pass).
"""

from __future__ import annotations

from dataclasses import dataclass

from manorem_ir import NarrationRole

__all__ = ["ARCS", "StoryArc", "arc_menu", "get_arc"]


@dataclass(frozen=True, slots=True)
class StoryArc:
    """One way to sequence a subject into beats."""

    name: str
    description: str
    roles: tuple[NarrationRole, ...]


_ARC_LIST: tuple[StoryArc, ...] = (
    StoryArc(
        name="question_led",
        description=(
            "Open on a question the viewer already half-wonders, build a mental model, "
            "complicate it, then resolve. Best for 'how does X work' explainers."
        ),
        roles=(
            NarrationRole.HOOK,
            NarrationRole.QUESTION,
            NarrationRole.MENTAL_MODEL,
            NarrationRole.COMPLICATION,
            NarrationRole.REVELATION,
            NarrationRole.PAYOFF,
            NarrationRole.CONCLUSION,
        ),
    ),
    StoryArc(
        name="problem_solution",
        description=(
            "Establish a concrete problem and its stakes, then walk the mechanism that "
            "solves it. Best when the subject exists to fix something."
        ),
        roles=(
            NarrationRole.HOOK,
            NarrationRole.CONTEXT,
            NarrationRole.COMPLICATION,
            NarrationRole.MENTAL_MODEL,
            NarrationRole.REVELATION,
            NarrationRole.CONCLUSION,
        ),
    ),
    StoryArc(
        name="chronological",
        description=(
            "Follow the subject as a process in time, one stage after the next. Best for "
            "pipelines, histories, and step-by-step procedures."
        ),
        roles=(
            NarrationRole.HOOK,
            NarrationRole.CONTEXT,
            NarrationRole.MENTAL_MODEL,
            NarrationRole.PAYOFF,
            NarrationRole.CONCLUSION,
        ),
    ),
    StoryArc(
        name="comparison",
        description=(
            "Set two things side by side and let the contrast carry the insight. Best "
            "for 'X vs Y' and for defining a thing by what it is not."
        ),
        roles=(
            NarrationRole.HOOK,
            NarrationRole.QUESTION,
            NarrationRole.MENTAL_MODEL,
            NarrationRole.REVELATION,
            NarrationRole.PAYOFF,
        ),
    ),
)

#: Arcs by name, the lookup the story agent and validation both use.
ARCS: dict[str, StoryArc] = {arc.name: arc for arc in _ARC_LIST}


def get_arc(name: str) -> StoryArc | None:
    return ARCS.get(name)


def arc_menu() -> str:
    """Render the arcs as the bulleted menu injected into the story prompt."""
    lines = [f"- {arc.name}: {arc.description}" for arc in _ARC_LIST]
    return "\n".join(lines)
