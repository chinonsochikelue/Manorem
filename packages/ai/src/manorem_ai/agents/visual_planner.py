"""The visual-planner agent: a beat and its narration in, a plan out.

This is the stage that decides *what the viewer sees* for one beat, and its schema
forces the reasoning to be explicit -- what to show, why, when, how, what to focus
on, what to keep on screen. It plans against a restricted skill vocabulary (the menu
for exactly the packs the scene will use), so it cannot ask for visuals the IR
generator has no words for.
"""

from __future__ import annotations

from manorem_ai.agents.base import Agent, load_prompt, render_input
from manorem_ai.agents.models import Beat, VisualPlan
from manorem_ai.provider import Completion
from manorem_ir import NarrationSegment

__all__ = ["VisualPlannerAgent"]


class VisualPlannerAgent(Agent):
    """Plan one beat's visuals as a :class:`VisualPlan`, against a skill menu."""

    def run(
        self, beat: Beat, segment: NarrationSegment, *, vocabulary: str
    ) -> Completion[VisualPlan]:
        user = render_input(beat=beat, narration=segment, available_vocabulary=vocabulary)
        return self._complete(system=load_prompt("visual_planner"), user=user, schema=VisualPlan)
