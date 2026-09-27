"""The research agent: idea plus retrieved documents in, a brief out.

The agent is handed the *only* documents it may cite -- the retrieved set -- so a
citation to anything else is a fabrication that :class:`~manorem_ai.research.ProvenanceValidator`
will catch downstream. Its output claims carry ``kind`` and ``confidence``, which
are the model's own assessment and are labelled as such everywhere they surface.
"""

from __future__ import annotations

from manorem_ai.agents.base import Agent, load_prompt, render_input
from manorem_ai.provider import Completion
from manorem_ai.research import Document, ResearchBrief

__all__ = ["ResearchAgent"]


class ResearchAgent(Agent):
    """Turn an idea and its sources into a structured :class:`ResearchBrief`."""

    def run(self, idea: str, documents: tuple[Document, ...]) -> Completion[ResearchBrief]:
        user = render_input(
            idea=idea,
            retrieved_documents=[
                {"url": d.url, "title": d.title, "snippet": d.snippet} for d in documents
            ],
        )
        return self._complete(system=load_prompt("research"), user=user, schema=ResearchBrief)
