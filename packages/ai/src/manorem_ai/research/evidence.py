"""Turning a citation into located evidence, and a span into a support relation.

Two steps live here, and the split between them is the point:

* **Extraction is deterministic.** A claim cites ``(url, quote)``; the pipeline
  finds that quote in the *retrieved bytes* of that source and records the exact
  character range it occupies. No model is asked to guess an offset, and a quote
  that cannot be found is reported (``RES803``) rather than approximated. The
  same passage cited twice yields one evidence record, because the id is a
  content address of (source, quote).
* **Assessment is model-judged but typed.** Deciding whether a span *supports* a
  claim is a reading, not a computation, so it goes to the model -- but the only
  thing it can return is a closed enum, never free prose the pipeline would then
  have to interpret. What the model cannot do is invent ids: every entry must
  name a claim and a span that already exist.

Neither step produces truth. Extraction proves the words are there; assessment
records a relation. Both persist as inspectable artifacts.
"""

from __future__ import annotations

from manorem_ai.research.models import (
    Claim,
    ClaimEvidenceLink,
    Evidence,
    EvidenceAssessment,
    Locator,
    LocatorKind,
    ResearchBrief,
    ResearchResult,
    derive_status,
    evidence_id,
)
from manorem_ai.research.text import heading_at, next_heading_start, paragraph_spans
from manorem_core import Code, DiagnosticBag, pointer

__all__ = [
    "apply_assessment",
    "classify_locator",
    "extract_evidence",
    "locate_quote",
]


def _fold(text: str) -> tuple[str, list[int]]:
    """Fold ``text`` into a matchable string, each char mapped back to an offset.

    Two transformations happen together, and both are why the offsets come back
    alongside the folded string -- a range recovered from folded text would
    otherwise point at the wrong characters:

    * **case-folding**, so a quotation copied with different capitalisation still
      matches. A character whose fold changes length is passed through unchanged,
      or every offset after it would drift.
    * **whitespace runs collapsed to one space**, because retrieved HTML and a
      copied quotation routinely disagree about line breaks alone -- the exact
      mismatch ``RES803`` would otherwise report as a missing span.

    Every output character carries the offset of the original character it came
    from. A collapsed run maps to the offset of the first character *after* it,
    so a matched range starts on real text rather than on padding.
    """
    out: list[str] = []
    offsets: list[int] = []
    pending_space = False
    for index, char in enumerate(text):
        if char.isspace():
            pending_space = True
            continue
        if pending_space:
            out.append(" ")
            offsets.append(index)
            pending_space = False
        folded = char.casefold()
        out.append(folded if len(folded) == 1 else char)
        offsets.append(index)
    return "".join(out), offsets


def locate_quote(content: str, quote: str) -> tuple[int, int] | None:
    """Find ``quote`` in ``content``, returning the half-open range it occupies.

    Exact match first, so the recorded range is precisely the quoted words; then
    a case-insensitive, whitespace-collapsed search as the fallback, because HTML
    sources routinely differ from a copied quotation in capitalisation and line
    breaks. ``None`` means *not present*, which the caller reports as ``RES803``
    -- nothing here ever returns a plausible-looking range for words that are not
    in the document.
    """
    if not quote.strip() or not content.strip():
        return None
    index = content.find(quote)
    if index >= 0:
        return (index, index + len(quote))

    folded_content, content_offsets = _fold(content)
    folded_quote = _fold(quote)[0]
    start = folded_content.find(folded_quote)
    if start < 0:
        return None
    end = start + len(folded_quote) - 1
    return (content_offsets[start], content_offsets[end] + 1)


def classify_locator(content: str, start: int, end: int) -> Locator:
    """Describe a known range with the most specific *stable* address it has.

    A heading first -- "under *Getting started*" is how a reader would find it --
    then a paragraph index for prose with no headings, then the raw range when
    the span crosses a boundary and neither label would be true. Classification
    never moves the range: it only adds a label that :meth:`Locator.resolve`
    re-checks against the same content.
    """
    heading = heading_at(content, start)
    if heading is not None and end <= next_heading_start(content, start):
        return Locator(kind=LocatorKind.SECTION, start=start, end=end, section=heading[1])
    for index, (first, last) in enumerate(paragraph_spans(content)):
        if first <= start and end <= last:
            return Locator(kind=LocatorKind.PARAGRAPH, start=start, end=end, paragraph=index)
    return Locator(kind=LocatorKind.CHAR_RANGE, start=start, end=end)


def extract_evidence(
    brief: ResearchBrief, result: ResearchResult, bag: DiagnosticBag
) -> tuple[Evidence, ...]:
    """Locate every cited quote in its source's retrieved content.

    Citations whose URL was never retrieved are skipped silently: the provenance
    check reports those as ``RES801``, and emitting a second finding for one
    defect would spam the repair loop for no extra information. Citations with no
    quote stay what they always were -- retrievable provenance that never becomes
    evidence, because a span that was never extracted cannot be pointed at.
    """
    by_url = result.by_url()
    found: dict[str, Evidence] = {}
    for claim_index, claim in enumerate(brief.claims):
        for source_index, citation in enumerate(claim.sources):
            if not citation.quote:
                continue
            retrieved = by_url.get(citation.url)
            if retrieved is None:
                continue
            span = locate_quote(retrieved.content, citation.quote)
            if span is None:
                bag.add(
                    Code.RES803_EVIDENCE_NOT_LOCATABLE,
                    f"claim {claim.id!r} quotes text that is not in {citation.url!r}",
                    pointer=pointer("claims", claim_index, "sources", source_index),
                    object_id=claim.id,
                    hint=(
                        "The quote must appear in the retrieved content (whitespace and "
                        "case may differ); an unlocatable quote is not evidence."
                    ),
                )
                continue
            start, end = span
            key = evidence_id(retrieved.source.id, citation.quote)
            found.setdefault(
                key,
                Evidence(
                    id=key,
                    source_id=retrieved.source.id,
                    locator=classify_locator(retrieved.content, start, end),
                    text=retrieved.content[start:end],
                    content_digest=retrieved.source.content_digest,
                    extractor="deterministic",
                    note=f"located from claim {claim.id!r} citation",
                ),
            )
    return tuple(found.values())


def apply_assessment(
    brief: ResearchBrief, assessment: EvidenceAssessment, bag: DiagnosticBag
) -> ResearchBrief:
    """Write a model's typed verdicts onto the claims, then re-derive every status.

    Entries naming a claim or a span that does not exist are reported as
    ``RES807`` and **discarded**, never coerced onto the nearest real id: a
    support relationship that points at the wrong thing is worse than an absent
    one. Statuses are recomputed from the surviving links rather than taken from
    the model, so a claim can never be labelled ``supported`` by assertion when
    its own recorded links say otherwise.
    """
    known_evidence = {item.id for item in brief.evidence}
    per_claim: dict[str, list[ClaimEvidenceLink]] = {claim.id: [] for claim in brief.claims}

    for index, entry in enumerate(assessment.assessments):
        if entry.claim_id not in per_claim or entry.evidence_id not in known_evidence:
            bag.add(
                Code.RES807_MISSING_CLAIM_EVIDENCE,
                f"assessment names unknown claim {entry.claim_id!r} or evidence "
                f"{entry.evidence_id!r}",
                pointer=pointer("assessments", index),
                object_id=entry.claim_id,
                hint="An assessment entry may only reference ids that already exist.",
            )
            continue
        per_claim[entry.claim_id].append(
            ClaimEvidenceLink(
                claim_id=entry.claim_id,
                evidence_id=entry.evidence_id,
                relation=entry.relation,
                note=entry.note,
            )
        )

    claims = tuple(_reassess(claim, tuple(per_claim.get(claim.id, ()))) for claim in brief.claims)
    return brief.model_copy(update={"claims": claims})


def _reassess(claim: Claim, links: tuple[ClaimEvidenceLink, ...]) -> Claim:
    """Set a claim's links, and its status only when there is something to derive.

    With no links the claim keeps whatever status it already carries: "nobody
    assessed this" and "the model called it unsupported" are different statements,
    and overwriting one with the other would silently invent an assessment.
    """
    if not links:
        return claim
    return claim.model_copy(update={"evidence": links, "status": derive_status(links)})
