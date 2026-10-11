"""The evidence agent: located spans in, typed support relations out.

Extraction is arithmetic; *judgement* is not. Deciding whether a span of a real
webpage backs a particular sentence is a reading, so this is where the model is
asked -- and it is asked for the narrowest possible answer: one closed enum per
(claim, evidence) pair.

What the model cannot do here is invent. The input carries only ids that already
exist, and :func:`~manorem_ai.research.evidence.apply_assessment` discards any
entry naming one that does not (``RES807``) rather than snapping it to the
nearest match. It also cannot assert a *status*: statuses are derived from the
relations it returns, so a claim cannot end up labelled ``supported`` by
assertion while its own links disagree.

The input's span text is retrieved content and is therefore untrusted data --
quoted, JSON-encoded, and framed as evidence to weigh rather than instructions
to obey.
"""

from __future__ import annotations

from manorem_ai.agents.base import Agent, load_prompt, render_input
from manorem_ai.provider import Completion
from manorem_ai.research import (
    EvidenceAssessment,
    ResearchBrief,
    ResearchResult,
)

__all__ = ["EvidenceAssessmentAgent"]


class EvidenceAssessmentAgent(Agent):
    """Assess how each located span bears on the claim that cited it."""

    def run(self, brief: ResearchBrief, result: ResearchResult) -> Completion[EvidenceAssessment]:
        sources = {source.id: source for source in result.sources}
        evidence_rows: list[dict[str, str]] = []
        for item in brief.evidence:
            source = sources.get(item.source_id)
            evidence_rows.append(
                {
                    "evidence_id": item.id,
                    "claim_citation": item.note,
                    "url": source.url if source is not None else "",
                    "publisher": source.publisher if source is not None else "",
                    "text": item.text,
                }
            )
        claim_rows = [
            {
                "claim_id": claim.id,
                "text": claim.text,
                "type": claim.type.value,
                "cited_urls": [citation.url for citation in claim.sources],
            }
            for claim in brief.claims
        ]
        user = render_input(
            claims=claim_rows,
            untrusted_evidence=evidence_rows,
        )
        return self._complete(system=load_prompt("evidence"), user=user, schema=EvidenceAssessment)
