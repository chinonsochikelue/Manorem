"""Deterministic validation of the research artifacts, in the ``RES8xx`` namespace.

Three guarantees are checked here, and they are deliberately kept apart:

* **Provenance** -- a cited URL was genuinely retrieved. That is
  :class:`ProvenanceValidator` and ``RES801``; it is the whole of the M1 promise,
  and it still says nothing about whether the source supports the claim.
* **Structure** -- ids are unique, references resolve, an evidence span still
  exists inside the content it was cut from, and the stored artifact's bytes hash
  to the digest they claim.
* **Support** -- a claim's ``status`` agrees with the relations actually recorded
  for it. A claim cannot be labelled ``supported`` while its own links say
  otherwise, and a claim with no links cannot claim support at all.

What is *not* checked is whether any of it is true. A retrieved source is not
automatically supporting evidence, and supporting evidence is not proof of
truth; that boundary is why these codes are separate statements rather than one
number.

Every finding names one defect and one JSON Pointer. Ordinary research
uncertainty -- partial support, a contradiction, an unused claim -- is reported at
WARNING or INFO severity, never ERROR, and none of these codes enter
:data:`~manorem_core.SEMANTIC_ERROR_CODES`: research state is not Visual IR
damage and must never reach the IR repair loop.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from manorem_ai.research.models import (
    ClaimStatus,
    EvidenceRelation,
    ResearchBrief,
    ResearchResult,
    RetrievedSource,
    Source,
    derive_status,
)
from manorem_core import Code, DiagnosticBag, ObjectStore, Severity, pointer, sha256_of

__all__ = [
    "RESEARCH_REPAIR_CODES",
    "ProvenanceValidator",
    "ResearchValidator",
]

#: The research defects a bounded re-run can actually clear -- every one of them
#: is something the model got wrong on the way to its brief, so asking again with
#: the diagnostic in hand is a real repair. Artifact faults (``RES802``,
#: ``RES808``) and provider faults (``RES809``) are absent on purpose: re-running
#: the model cannot make a missing file appear or a network come back, and
#: routing them here would burn an attempt to achieve nothing. The planning-side
#: observations (``RES805``, ``RES806``, ``RES811``..``RES814``) are absent too --
#: they are states to record, not defects, and are never errors.
RESEARCH_REPAIR_CODES: frozenset[Code] = frozenset(
    {
        Code.RES801_UNRETRIEVED_SOURCE,
        Code.RES803_EVIDENCE_NOT_LOCATABLE,
        Code.RES804_CLAIM_UNSUPPORTED,
        Code.RES807_MISSING_CLAIM_EVIDENCE,
        Code.RES810_DUPLICATE_ID,
    }
)


class ProvenanceValidator:
    """Reject citations to URLs that were never retrieved. Provenance, not proof.

    This is the entirety of the guarantee: a cited URL must be among the
    retrieved sources. A retrieved-but-unsupported claim passes -- deliberately --
    because *support* is a separate, explicit relationship recorded and checked
    by :class:`ResearchValidator`, and this validator must not be mistaken for it.
    """

    def validate(
        self,
        brief: ResearchBrief,
        retrieved: Sequence[Source | RetrievedSource],
    ) -> DiagnosticBag:
        bag = DiagnosticBag()
        urls = {_url(item) for item in retrieved}
        urls.discard("")
        for claim_index, claim in enumerate(brief.claims):
            for source_index, citation in enumerate(claim.sources):
                if citation.url not in urls:
                    bag.add(
                        Code.RES801_UNRETRIEVED_SOURCE,
                        f"claim {claim.id!r} cites {citation.url!r}, which was not retrieved",
                        pointer=pointer("claims", claim_index, "sources", source_index),
                        object_id=claim.id,
                        hint=(
                            "Every cited URL must come from a retrieved document. This checks "
                            "provenance only -- whether the source supports the claim is "
                            "recorded separately, in the claim's evidence links."
                        ),
                    )
        return bag


def _url(item: Source | RetrievedSource) -> str:
    if isinstance(item, RetrievedSource):
        return item.source.url
    return item.url


class ResearchValidator:
    """Validate sources, evidence and claims as one referential graph.

    ``store`` is optional. When given, each source's artifact is read back and
    re-hashed, which is the only way to catch a content digest that no longer
    matches the bytes it names; without a store the validator checks the graph
    against the retrieved content it was handed, which is what unit tests do.
    """

    def validate(
        self,
        brief: ResearchBrief,
        result: ResearchResult,
        *,
        store: ObjectStore | None = None,
    ) -> DiagnosticBag:
        bag = DiagnosticBag()
        sources = result.sources

        _check_duplicate_ids(brief, sources, bag)
        _check_evidence(brief, result, bag)
        _check_claims(brief, bag)
        if store is not None:
            _check_artifacts(result, store, bag)
        return bag


def _check_duplicate_ids(
    brief: ResearchBrief, sources: tuple[Source, ...], bag: DiagnosticBag
) -> None:
    for kind, ids in (
        ("sources", [source.id for source in sources]),
        ("claims", [claim.id for claim in brief.claims]),
        ("evidence", [item.id for item in brief.evidence]),
    ):
        seen: set[str] = set()
        for index, value in enumerate(ids):
            if value in seen:
                bag.add(
                    Code.RES810_DUPLICATE_ID,
                    f"duplicate {kind[:-1]} id {value!r}",
                    pointer=pointer(kind, index),
                    object_id=value,
                    hint="Ids must be unique within one research run.",
                )
            seen.add(value)


def _check_evidence(brief: ResearchBrief, result: ResearchResult, bag: DiagnosticBag) -> None:
    """Referential integrity for evidence, then for the links that point at it."""
    evidence_ids = {item.id for item in brief.evidence}
    sources_by_id = {source.id: source for source in result.sources}

    for index, item in enumerate(brief.evidence):
        source = sources_by_id.get(item.source_id)
        if source is None:
            bag.add(
                Code.RES807_MISSING_CLAIM_EVIDENCE,
                f"evidence {item.id!r} names source {item.source_id!r}, which was not retrieved",
                pointer=pointer("evidence", index, "source_id"),
                object_id=item.id,
                hint="Evidence may only come from a source in this run's result.",
            )
            continue
        content = result.content_of(item.source_id)
        if content is None:
            continue  # reported as RES807 above or RES802 by the artifact check
        if item.content_digest != source.content_digest:
            # Digest first: once the content has changed, every locator failure
            # is a consequence of it, and reporting both would be one defect
            # reported twice.
            bag.add(
                Code.RES808_SOURCE_CONTENT_CHANGED,
                f"evidence {item.id!r} was cut from content digest "
                f"{item.content_digest[:12]}, but {source.id!r} now holds "
                f"{source.content_digest[:12]}",
                pointer=pointer("evidence", index, "content_digest"),
                object_id=item.id,
                hint="Re-extract the span against the current content.",
            )
            continue
        span = item.locator.resolve(content)
        if span is None or item.text not in content[span[0] : span[1]]:
            bag.add(
                Code.RES803_EVIDENCE_NOT_LOCATABLE,
                f"evidence {item.id!r} no longer resolves to a span in {source.url!r}",
                pointer=pointer("evidence", index, "locator"),
                object_id=item.id,
                hint="The locator must re-derive a range that still contains the quoted text.",
            )

    for claim_index, claim in enumerate(brief.claims):
        for link_index, link in enumerate(claim.evidence):
            base = pointer("claims", claim_index, "evidence", link_index)
            if link.claim_id != claim.id:
                bag.add(
                    Code.RES807_MISSING_CLAIM_EVIDENCE,
                    f"link claims {link.claim_id!r} but is recorded on {claim.id!r}",
                    pointer=f"{base}/claim_id",
                    object_id=claim.id,
                    hint="A link must name the claim that carries it.",
                )
            elif link.evidence_id not in evidence_ids:
                bag.add(
                    Code.RES807_MISSING_CLAIM_EVIDENCE,
                    f"claim {claim.id!r} links evidence {link.evidence_id!r}, which does not exist",
                    pointer=f"{base}/evidence_id",
                    object_id=claim.id,
                    hint="Every link must resolve to evidence extracted in this run.",
                )


def _check_claims(brief: ResearchBrief, bag: DiagnosticBag) -> None:
    """Fold each claim's links into a status and hold the stored one to it."""
    for index, claim in enumerate(brief.claims):
        status_pointer = pointer("claims", index, "status")
        links = claim.evidence
        derived = derive_status(links)

        if links:
            if claim.status is not derived:
                bag.add(
                    Code.RES804_CLAIM_UNSUPPORTED,
                    f"claim {claim.id!r} is marked {claim.status.value} but its links "
                    f"record {derived.value}",
                    pointer=status_pointer,
                    object_id=claim.id,
                    hint="Status is derived from the recorded relations; fix the links.",
                )
            elif claim.status is ClaimStatus.PARTIALLY_SUPPORTED:
                bag.warn(
                    Code.RES805_CLAIM_PARTIALLY_SUPPORTED,
                    f"claim {claim.id!r} is only partially supported by its evidence",
                    pointer=status_pointer,
                    object_id=claim.id,
                    hint="Consider qualifying the statement rather than stating it flatly.",
                )
            elif claim.status is ClaimStatus.UNSUPPORTED:
                bag.warn(
                    Code.RES804_CLAIM_UNSUPPORTED,
                    f"claim {claim.id!r} has evidence, but none of it supports the claim",
                    pointer=status_pointer,
                    object_id=claim.id,
                    hint=(
                        "Research looked and found no supporting span. Qualify the "
                        "statement, present the disagreement, or drop the claim."
                    ),
                )
            if any(link.relation is EvidenceRelation.CONTRADICTS for link in links):
                bag.warn(
                    Code.RES806_CLAIM_CONTRADICTED,
                    f"claim {claim.id!r} has evidence that contradicts it",
                    pointer=pointer("claims", index),
                    object_id=claim.id,
                    hint=(
                        "Conflicting evidence is preserved, never resolved by source order; "
                        "the story planner must qualify, present the disagreement, or omit "
                        "the claim."
                    ),
                )
        elif claim.status in (
            ClaimStatus.SUPPORTED,
            ClaimStatus.PARTIALLY_SUPPORTED,
            ClaimStatus.CONTRADICTED,
        ):
            bag.add(
                Code.RES804_CLAIM_UNSUPPORTED,
                f"claim {claim.id!r} is marked {claim.status.value} with no evidence links",
                pointer=status_pointer,
                object_id=claim.id,
                hint="A claim with no recorded relation to any span cannot claim support.",
            )
        elif claim.status is ClaimStatus.UNASSESSED:
            bag.add(
                Code.RES811_CLAIM_UNASSESSED,
                f"claim {claim.id!r} has no assessed evidence",
                pointer=status_pointer,
                object_id=claim.id,
                severity=Severity.INFO,
                hint="Recorded for inspection; unassessed is not the same as unsupported.",
            )


def _check_artifacts(result: ResearchResult, store: ObjectStore, bag: DiagnosticBag) -> None:
    """Read every source artifact back and re-hash it against its declared digest."""
    for index, source in enumerate(result.sources):
        key = source.artifact_key
        if not store.exists(key):
            bag.add(
                Code.RES802_SOURCE_ARTIFACT_INVALID,
                f"source {source.id!r} has no stored artifact at {key}",
                pointer=pointer("sources", index, "artifact_key"),
                object_id=source.id,
                hint="Every retrieved source must be written to the object store.",
            )
            continue
        try:
            payload = json.loads(store.get_text(key))
            content = payload["content"]
        except (ValueError, KeyError, TypeError):
            bag.add(
                Code.RES802_SOURCE_ARTIFACT_INVALID,
                f"source {source.id!r} artifact at {key} is not a readable research artifact",
                pointer=pointer("sources", index, "artifact_key"),
                object_id=source.id,
                hint="The artifact must be a JSON object holding the retrieved content.",
            )
            continue
        if not isinstance(content, str) or sha256_of(content) != source.content_digest:
            bag.add(
                Code.RES808_SOURCE_CONTENT_CHANGED,
                f"source {source.id!r} stored bytes do not hash to {source.content_digest[:12]}",
                pointer=pointer("sources", index, "content_digest"),
                object_id=source.id,
                hint="The artifact was altered after retrieval; re-research instead of editing.",
            )
