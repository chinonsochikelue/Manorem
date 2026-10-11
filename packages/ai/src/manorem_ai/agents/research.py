"""The research agent: idea plus retrieved sources in, a brief out.

The agent is handed the *only* sources it may cite -- the retrieved set -- so a
citation to anything else is a fabrication that
:class:`~manorem_ai.research.ProvenanceValidator` will catch downstream.

**Retrieved text is untrusted data.** A source body arrives embedded in a
section explicitly labelled as untrusted, JSON-encoded so its own punctuation
cannot terminate the surrounding structure, and the system prompt says in as many
words that it is data to read, never instructions to follow. The agent may quote
from it; it may not act on anything it finds there. That containment is the
prompt's job and the *format's* job -- a model that ignores the instruction
still cannot break out of a JSON string literal.

Quotes are cut from a bounded excerpt rather than the whole body, which keeps a
huge page from dominating the prompt and makes it possible for the quote to be
located deterministically afterwards (``RES803`` when it cannot be).
"""

from __future__ import annotations

from collections.abc import Sequence

from manorem_ai.agents.base import Agent, load_prompt, render_input
from manorem_ai.provider import Completion
from manorem_ai.research import ResearchBrief, RetrievedSource
from manorem_core import Diagnostic, Severity

__all__ = ["ResearchAgent"]


class ResearchAgent(Agent):
    """Turn an idea and its sources into a structured :class:`ResearchBrief`."""

    #: Characters of each source body handed to the model. Bounded so one large
    #: page cannot crowd out the others, and so every quote the model produces is
    #: guaranteed to come from text it actually saw.
    excerpt_chars = 4000

    def run(
        self,
        idea: str,
        retrieved: tuple[RetrievedSource, ...],
        *,
        diagnostics: Sequence[Diagnostic] = (),
    ) -> Completion[ResearchBrief]:
        """Build the brief. With ``diagnostics``, this is a bounded repair re-run.

        The same schema is requested either way -- a repair that changed the
        output contract would not be a repair. What changes is the input: the
        previous attempt's findings are handed back so the model can see *which*
        citation, quote or id was rejected rather than guessing.
        """
        sections: dict[str, object] = {
            "idea": idea,
            "untrusted_retrieved_sources": self._rows(retrieved),
        }
        if diagnostics:
            sections["repair_diagnostics"] = [
                {
                    "code": d.code.value,
                    "severity": d.severity.value,
                    "pointer": d.pointer,
                    "message": d.message,
                    "hint": d.hint,
                }
                for d in diagnostics
                if d.severity is not Severity.INFO
            ]
        user = render_input(**sections)
        return self._complete(system=load_prompt("research"), user=user, schema=ResearchBrief)

    def _rows(self, retrieved: tuple[RetrievedSource, ...]) -> list[dict[str, str]]:
        """The source bodies, excerpted, as plain JSON-encodable data."""
        return [
            {
                "source_id": item.source.id,
                "url": item.source.url,
                "title": item.source.title,
                "publisher": item.source.publisher,
                "excerpt": item.content[: self.excerpt_chars],
            }
            for item in retrieved
        ]
