"""The script agent: an outline in, narration segments out.

The agent writes the words; it does not set the clock. Segment ``start``/``end``
are left unset here and filled by the deterministic :mod:`~manorem_ai.pacing`
model, so the timeline is arithmetic over the text rather than another thing the
model can get wrong.

The brief travels alongside the outline so every factual line can name the claim
it draws on. Those ids are not decoration: :func:`~manorem_ai.traceability.validate_traceability`
resolves each one against the research artifact afterwards, so a segment citing
a claim that does not exist cannot quietly become narration.
"""

from __future__ import annotations

from manorem_ai.agents.base import Agent, load_prompt, render_input
from manorem_ai.agents.models import Script, StoryOutline
from manorem_ai.provider import Completion
from manorem_ai.research import ResearchBrief

__all__ = ["ScriptAgent"]


class ScriptAgent(Agent):
    """Write the narration for an outline as a :class:`Script`."""

    def run(self, outline: StoryOutline, brief: ResearchBrief | None = None) -> Completion[Script]:
        sections: dict[str, object] = {"outline": outline}
        if brief is not None:
            sections["brief"] = brief
        return self._complete(
            system=load_prompt("script"),
            user=render_input(**sections),
            schema=Script,
        )
