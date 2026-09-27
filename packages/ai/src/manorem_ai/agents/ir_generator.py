"""The IR-generator agent: a visual plan in, exactly one :class:`Scene` out.

Generation is per scene, never per project -- Gemini's schema-nesting limits rule
out emitting a whole ``Project`` at once, and a scene is the natural unit of
authoring, rendering and repair anyway. The agent is given the skill vocabulary the
plan selected and nothing else, so the closed menu of object kinds and semantic ops
is the only thing it can reach for.
"""

from __future__ import annotations

from manorem_ai.agents.base import Agent, load_prompt, render_input
from manorem_ai.agents.models import VisualPlan
from manorem_ai.provider import Completion
from manorem_ir import NarrationSegment, Scene

__all__ = ["IRGeneratorAgent"]


class IRGeneratorAgent(Agent):
    """Realize one :class:`VisualPlan` as a single validated :class:`Scene`."""

    def run(
        self, plan: VisualPlan, segment: NarrationSegment, *, vocabulary: str
    ) -> Completion[Scene]:
        user = render_input(visual_plan=plan, narration=segment, available_vocabulary=vocabulary)
        return self._complete(system=load_prompt("ir_generator"), user=user, schema=Scene)
