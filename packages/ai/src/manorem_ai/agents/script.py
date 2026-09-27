"""The script agent: an outline in, narration segments out.

The agent writes the words; it does not set the clock. Segment ``start``/``end``
are left unset here and filled by the deterministic :mod:`~manorem_ai.pacing`
model, so the timeline is arithmetic over the text rather than another thing the
model can get wrong.
"""

from __future__ import annotations

from manorem_ai.agents.base import Agent, load_prompt, render_input
from manorem_ai.agents.models import Script, StoryOutline
from manorem_ai.provider import Completion

__all__ = ["ScriptAgent"]


class ScriptAgent(Agent):
    """Write the narration for an outline as a :class:`Script`."""

    def run(self, outline: StoryOutline) -> Completion[Script]:
        return self._complete(
            system=load_prompt("script"),
            user=render_input(outline=outline),
            schema=Script,
        )
