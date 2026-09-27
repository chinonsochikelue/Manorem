"""The story agent: a brief in, a chosen arc and its beats out.

The agent picks one of the named arcs in :mod:`~manorem_ai.arcs` and must justify
the choice in ``rationale`` -- the schema refuses an outline that skips it. Forcing
an explicit, defended arc choice is how the pipeline avoids pouring every subject
into the same mould.
"""

from __future__ import annotations

from manorem_ai.agents.base import Agent, load_prompt, render_input
from manorem_ai.agents.models import StoryOutline
from manorem_ai.arcs import arc_menu
from manorem_ai.provider import Completion
from manorem_ai.research import ResearchBrief

__all__ = ["StoryAgent"]


class StoryAgent(Agent):
    """Shape a brief into a :class:`StoryOutline` along a justified arc."""

    def run(self, brief: ResearchBrief) -> Completion[StoryOutline]:
        user = render_input(brief=brief, available_arcs=arc_menu())
        return self._complete(system=load_prompt("story"), user=user, schema=StoryOutline)
