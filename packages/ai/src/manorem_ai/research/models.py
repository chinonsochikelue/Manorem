"""Content intelligence: sources, evidence, claims, and the links between them.

This module is the typed vocabulary of milestone 4. The chain it describes is
deliberately explicit and inspectable at every hop::

    ResearchRequest -> ResearchResult -> Source -> Evidence -> Claim
                                                       │
                                                       └-> ClaimEvidenceLink

Three distinctions are load-bearing and are encoded in the types rather than
left to prose:

* **Retrieval is not support.** A :class:`Source` proves a URL was fetched. Only
  a :class:`ClaimEvidenceLink` with an explicit ``relation`` says a span backs a
  claim, and :class:`ClaimStatus` records what that relation added up to.
* **Support is not truth.** There is deliberately no factuality score anywhere
  in this vocabulary -- no ``truth_score``, no ``confidence`` percentage. The
  system exposes claim, evidence, relation, status and source; downstream
  planning decides what to do with them.
* **A URL is a location, not an identity.** ``url`` says *where*, ``retrieved_at``
  says *when*, and ``content_digest`` says *what* was actually retrieved. The same
  URL yielding different bytes yields a different digest, and the artifacts show
  that rather than pretending the source is immutable.

Retrieved text is **untrusted data** everywhere it travels: it is data a model
may read, never an instruction it must follow.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from manorem_ai.research.text import heading_at, next_heading_start, paragraph_spans
from manorem_core import Slug, canonical_json, sha256_of, short_digest

__all__ = [
    "AssessmentEntry",
    "Claim",
    "ClaimEvidenceLink",
    "ClaimImportance",
    "ClaimStatus",
    "ClaimType",
    "Entity",
    "Evidence",
    "EvidenceAssessment",
    "EvidenceRelation",
    "Locator",
    "LocatorKind",
    "ResearchBrief",
    "ResearchRequest",
    "ResearchResult",
    "RetrievedSource",
    "Source",
    "SourceRef",
    "VisualCandidate",
    "derive_status",
    "evidence_id",
    "research_cache_key",
    "source_identity",
]


# ---------------------------------------------------------------------------
# research request / result
# ---------------------------------------------------------------------------


class ResearchRequest(BaseModel):
    """What needs to be known, expressed without any search-engine syntax.

    A model, not a query string, so persisted project artifacts never bake in a
    vendor's query operators: a different provider gets the same request and
    translates it however it likes. That is what keeps the IR and the artifacts
    provider-neutral.
    """

    model_config = ConfigDict(frozen=True)

    #: The topic to explain, in the words the user gave.
    topic: str = Field(min_length=1, max_length=2000)
    #: Open questions the research should settle, if any.
    questions: tuple[str, ...] = ()
    #: Scope limits: what is deliberately out of bounds for this research.
    constraints: tuple[str, ...] = ()
    #: Upper bound on sources. Retrieval never returns more than this.
    max_sources: int = Field(default=6, ge=1, le=50)


def research_cache_key(request: ResearchRequest, *, provider: str) -> str:
    """Content address of a retrieval: (request, provider identity).

    Deliberately excludes secrets, api keys and request headers -- a cache key
    that folded in a credential would leak it into a filename -- and excludes
    retrieval time, because *when* something was fetched is not part of *what*
    was asked for. Two runs that ask the same provider the same question hit the
    same entry; a different provider or a reworded question misses it.
    """
    payload = {"request": request.model_dump(mode="json"), "provider": provider}
    return sha256_of(canonical_json(payload))


def source_identity(url: str) -> str:
    """A stable, collision-resistant slug for a URL, used when a provider omits an id.

    A digest rather than a slugified URL: two URLs that slugify to the same
    characters would otherwise collide inside one retrieval and trip
    ``RES810_DUPLICATE_ID`` for reasons that have nothing to do with the sources.
    """
    return f"src_{short_digest(sha256_of(url), 12)}"


# ---------------------------------------------------------------------------
# sources
# ---------------------------------------------------------------------------


class Source(BaseModel):
    """One retrieved source: where it came from, when, and what was retrieved.

    ``content_digest`` is the source's *identity* -- the sha256 of the exact bytes
    stored under ``artifact_key`` -- while ``url`` is only its location. The two
    are kept apart on purpose: re-fetching a URL that changed produces the same
    ``url`` with a different ``content_digest``, and the artifacts make that
    visible instead of assuming URLs are immutable.
    """

    model_config = ConfigDict(frozen=True)

    id: Slug
    url: str = Field(min_length=1, max_length=2000)
    title: str = Field(default="", max_length=400)
    publisher: str = Field(default="", max_length=200)
    retrieved_at: datetime
    #: sha256 of the retrieved content. The stable identity of what was fetched.
    content_digest: str = Field(min_length=1)
    #: Object-store key of the full artifact (metadata + content).
    artifact_key: str = Field(min_length=1)
    media_type: str = Field(default="text/plain", min_length=1)
    #: Provider-neutral extra metadata. Never holds credentials or auth headers.
    metadata: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def of(
        cls,
        *,
        url: str,
        content: str,
        retrieved_at: datetime,
        title: str = "",
        publisher: str = "",
        media_type: str = "text/plain",
        metadata: dict[str, str] | None = None,
        id: str | None = None,
    ) -> Source:
        """Build a source, deriving ``content_digest`` and ``artifact_key``.

        Both are derived rather than accepted, so a caller cannot claim a digest
        the stored content does not actually have -- that mismatch is exactly
        what ``RES808_SOURCE_CONTENT_CHANGED`` exists to catch.
        """
        digest = sha256_of(content)
        return cls(
            id=id or source_identity(url),
            url=url,
            title=title,
            publisher=publisher,
            retrieved_at=retrieved_at,
            content_digest=digest,
            artifact_key=f"research/sources/{digest}.json",
            media_type=media_type,
            metadata=metadata or {},
        )


class RetrievedSource(BaseModel):
    """A :class:`Source` plus the raw content that was retrieved, in memory.

    ``content`` is untrusted text a model may read. It is never written into the
    Visual IR and never written into ``sources.json`` -- it lives in its own
    content-addressed artifact under :attr:`Source.artifact_key`, which is what
    keeps a webpage body out of the document every downstream stage hashes.
    """

    model_config = ConfigDict(frozen=True)

    source: Source
    #: The retrieved body. Untrusted data: never instructions, never executed.
    content: str = Field(default="", max_length=500_000)


class Document(RetrievedSource):
    """One retrieved source, in the shape the M1 pipeline and CLI still use.

    The research package renamed this to :class:`RetrievedSource`; ``Document``
    stays as a thin subclass so the pipeline, the ``--corpus`` loader and the
    ``manorem_ai`` re-exports keep working unchanged until they migrate to the
    ``research(request)`` seam. ``content`` carries what M1 called the snippet.
    New code uses :class:`RetrievedSource` directly.
    """

    @classmethod
    def of(cls, url: str, title: str, snippet: str, *, retrieved_at: datetime) -> Document:
        """Build a document, deriving the digest from the snippet (as M1 did)."""
        return cls(
            source=Source.of(url=url, content=snippet, title=title, retrieved_at=retrieved_at),
            content=snippet,
        )


class ResearchResult(BaseModel):
    """What one retrieval actually returned, before any model reads it.

    The provider-neutral output of :meth:`~manorem_ai.research.ResearchProvider.research`.
    Holding the content alongside the metadata is what lets evidence be located
    deterministically in the *retrieved bytes* rather than in a model's memory of
    them.
    """

    model_config = ConfigDict(frozen=True)

    request: ResearchRequest
    retrieved: tuple[RetrievedSource, ...] = ()

    @property
    def sources(self) -> tuple[Source, ...]:
        return tuple(item.source for item in self.retrieved)

    def content_of(self, source_id: str) -> str | None:
        """The retrieved content of ``source_id``, or ``None`` if not present."""
        for item in self.retrieved:
            if item.source.id == source_id:
                return item.content
        return None

    def by_url(self) -> dict[str, RetrievedSource]:
        return {item.source.url: item for item in self.retrieved}


# ---------------------------------------------------------------------------
# evidence
# ---------------------------------------------------------------------------


class LocatorKind(StrEnum):
    """How an evidence span is addressed within its source.

    A deliberately small set: the three forms that are *stable* for the text
    artifacts this pipeline retrieves. Line numbers are conspicuously absent --
    inventing them for an arbitrary web page would be a fabricated locator.
    """

    #: A half-open character range: the precise, lossless address.
    CHAR_RANGE = "char_range"
    #: A zero-based blank-line-delimited block index: robust to small edits.
    PARAGRAPH = "paragraph"
    #: The enclosing markdown heading's text: the most human-readable address.
    SECTION = "section"


class Locator(BaseModel):
    """Where in a source an evidence span came from.

    Every locator carries an exact ``[start, end)`` range over the source's stored
    content -- that is what makes a span *locatable* rather than merely asserted.
    ``kind`` records the most specific stable address available for that range,
    and the accompanying field repeats it in that vocabulary so a human can find
    the passage without arithmetic. :meth:`resolve` re-derives the range from the
    content and cross-checks the label, so a changed document or a mislabelled
    span is detected instead of trusted.
    """

    model_config = ConfigDict(frozen=True)

    kind: LocatorKind
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    #: ``PARAGRAPH`` only: the zero-based block index the span sits in.
    paragraph: int | None = Field(default=None, ge=0)
    #: ``SECTION`` only: the text of the heading the span sits under.
    section: str | None = Field(default=None, max_length=400)

    def resolve(self, content: str) -> tuple[int, int] | None:
        """Re-derive the span from ``content``, or ``None`` if it no longer resolves.

        Resolution is a pure function of the content, so it is reproducible
        offline. A ``None`` means *not locatable* -- which is a fact about the
        artifact, reported as ``RES803``, never a licence to guess a position.
        """
        start, end = self.start, self.end
        if start >= end or end > len(content):
            return None
        if self.kind is LocatorKind.CHAR_RANGE:
            return (start, end)
        if self.kind is LocatorKind.PARAGRAPH:
            if self.paragraph is None:
                return None
            spans = paragraph_spans(content)
            if self.paragraph >= len(spans):
                return None
            first, last = spans[self.paragraph]
            return (start, end) if first <= start and end <= last else None
        heading = heading_at(content, start)
        if heading is None or heading[1] != self.section:
            return None
        return (start, end) if end <= next_heading_start(content, start) else None


class Evidence(BaseModel):
    """A span retrieved from a source that a claim relies on.

    Not every retrieved source is evidence for every claim it mentions: evidence
    exists only where something was actually extracted and located, and it names
    the source it came from. ``content_digest`` pins *which version* of the
    source the span was cut from, so a later refetch that changes the bytes is a
    detectable event rather than a silent rewrite.
    """

    model_config = ConfigDict(frozen=True)

    id: Slug
    source_id: Slug
    locator: Locator
    #: The extracted passage, exactly as it appears in the stored content.
    text: str = Field(min_length=1, max_length=8000)
    #: Digest of the source content this span was located in.
    content_digest: str = Field(min_length=1)
    #: How the span was obtained -- e.g. ``model-quote`` or ``deterministic``.
    extractor: str = Field(default="model-quote", min_length=1, max_length=80)
    #: Free-form extraction note. Not a machine contract.
    note: str = Field(default="", max_length=600)


# ---------------------------------------------------------------------------
# claims
# ---------------------------------------------------------------------------


class ClaimType(StrEnum):
    """A closed set of what kind of assertion a claim *is*.

    Small on purpose: the model picks from a menu planning can reason about,
    rather than inventing an epistemic taxonomy nobody downstream reads.
    """

    FACT = "fact"
    DEFINITION = "definition"
    NUMBER = "number"
    DATE = "date"
    COMPARISON = "comparison"
    CAUSAL = "causal"
    HISTORICAL = "historical"
    QUOTE = "quote"
    INTERPRETATION = "interpretation"


class ClaimImportance(StrEnum):
    """How much of the explanation rests on this claim."""

    PRIMARY = "primary"
    SUPPORTING = "supporting"


class ClaimStatus(StrEnum):
    """What the recorded evidence amounts to for a claim.

    Five values, none of them a number. ``unassessed`` is kept distinct from
    ``unsupported``: "we have not looked" and "we looked and it is not backed"
    are different states, and collapsing either into the other would be a lie.
    ``partially_supported`` and ``contradicted`` keep uncertainty visible rather
    than rounding it up to ``supported``.
    """

    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    UNSUPPORTED = "unsupported"
    CONTRADICTED = "contradicted"
    UNASSESSED = "unassessed"


class EvidenceRelation(StrEnum):
    """How one evidence span bears on one claim.

    Four values, each a real, distinguishable statement about a passage. Note
    what is absent: there is no ``mentions`` / ``same_topic`` relation. "A source
    talks about the same subject" is not support, and a vocabulary that offered
    it would invite exactly the collapse this design forbids.
    """

    SUPPORTS = "supports"
    PARTIALLY_SUPPORTS = "partially_supports"
    CONTRADICTS = "contradicts"
    CONTEXTUALIZES = "contextualizes"


class SourceRef(BaseModel):
    """A citation on a claim: the URL, and optionally the passage relied on.

    The URL is the whole of what the provenance check verifies -- it was
    retrieved. ``quote`` is the input to evidence extraction: locating it in the
    stored content is what turns a citation into an :class:`Evidence` span, and
    failing to locate it is ``RES803``, never a silent pass.
    """

    model_config = ConfigDict(frozen=True)

    url: str = Field(min_length=1, max_length=2000)
    quote: str = Field(default="", max_length=2000)


class ClaimEvidenceLink(BaseModel):
    """The central M4 structure: one explicit claim-to-evidence relationship.

    This -- not ``claim.source_url`` -- is how support is recorded. The link names
    both ends and states the relation, so "retrieved", "supports" and "is true"
    can never be conflated by a field that means all three.
    """

    model_config = ConfigDict(frozen=True)

    claim_id: Slug
    evidence_id: Slug
    relation: EvidenceRelation
    #: Why the span bears this relation. Advisory to a human reader.
    note: str = Field(default="", max_length=600)


class Claim(BaseModel):
    """One assertion the explanation makes, and what backs it.

    ``status`` is derived from the recorded links by :func:`derive_status` once
    evidence has been assessed; before that it is ``unassessed``. It is stored
    rather than computed so an artifact read on its own still says where the
    claim stood, and validated so it can never quietly drift from the links that
    produced it.
    """

    model_config = ConfigDict(frozen=True)

    id: Slug
    text: str = Field(min_length=1, max_length=2000)
    type: ClaimType = ClaimType.FACT
    importance: ClaimImportance = ClaimImportance.SUPPORTING
    status: ClaimStatus = ClaimStatus.UNASSESSED
    #: Explicit relationships to evidence spans, each naming this claim in turn.
    evidence: tuple[ClaimEvidenceLink, ...] = ()
    #: Direct URL citations. Checked for *retrieval* only (``RES801``) -- a
    #: citation without an evidence link is a fetched source, not support.
    sources: tuple[SourceRef, ...] = ()


def derive_status(links: tuple[ClaimEvidenceLink, ...]) -> ClaimStatus:
    """Fold a claim's links into one status, with no way to round uncertainty up.

    The rule is deliberately conservative and exhaustively documented:

    * no links at all -> ``unassessed`` (nobody looked, which is not ``unsupported``)
    * any ``contradicts`` -> ``contradicted``, even alongside supporting links.
      Conflict is never averaged away; ``RES806`` records that the conflict exists
      and the planner sees both links.
    * ``supports`` present, with or without ``partially_supports`` and
      ``contextualizes`` -> ``supported`` only when nothing partial is there,
      otherwise ``partially_supported``
    * only ``partially_supports`` -> ``partially_supported``
    * only ``contextualizes`` -> ``unsupported``: context is not support
    """
    if not links:
        return ClaimStatus.UNASSESSED
    relations = {link.relation for link in links}
    if EvidenceRelation.CONTRADICTS in relations:
        return ClaimStatus.CONTRADICTED
    if EvidenceRelation.PARTIALLY_SUPPORTS in relations:
        return ClaimStatus.PARTIALLY_SUPPORTED
    if EvidenceRelation.SUPPORTS in relations:
        return ClaimStatus.SUPPORTED
    return ClaimStatus.UNSUPPORTED


# ---------------------------------------------------------------------------
# brief / assessment
# ---------------------------------------------------------------------------


class Entity(BaseModel):
    """A named thing the story may need to depict -- a satellite, a receiver."""

    model_config = ConfigDict(frozen=True)

    id: Slug
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)


class VisualCandidate(BaseModel):
    """A suggested way to picture part of the subject. Advisory to the planner."""

    model_config = ConfigDict(frozen=True)

    id: Slug
    description: str = Field(min_length=1, max_length=1000)
    related_entities: tuple[str, ...] = ()


class ResearchBrief(BaseModel):
    """The research stage's output: claims, evidence, and the raw story material.

    ``evidence`` is filled in by the pipeline, not authored by the model: it holds
    every span located in the brief's citations, so downstream stages read one
    artifact instead of reconstructing a graph from ids. The model authors
    ``claims`` (with their citations); everything after that is derived and
    validated rather than asserted.
    """

    model_config = ConfigDict(frozen=True)

    idea: str = Field(min_length=1, max_length=2000)
    claims: tuple[Claim, ...] = ()
    #: Spans located in the citations. Pipeline-populated; the model omits it.
    evidence: tuple[Evidence, ...] = ()
    entities: tuple[Entity, ...] = ()
    visual_candidates: tuple[VisualCandidate, ...] = ()
    open_questions: tuple[str, ...] = ()


class AssessmentEntry(BaseModel):
    """The typed answer to "how does this span bear on this claim?"."""

    model_config = ConfigDict(frozen=True)

    claim_id: Slug
    evidence_id: Slug
    relation: EvidenceRelation
    note: str = Field(default="", max_length=600)


class EvidenceAssessment(BaseModel):
    """Bounded evidence assessment: one structured verdict per reviewed pair.

    The machine contract is the enum, never the prose. ``note`` is a diagnostic
    for a human; a downstream stage that needed it to behave would be reading the
    wrong field.
    """

    model_config = ConfigDict(frozen=True)

    assessments: tuple[AssessmentEntry, ...] = ()


def evidence_id(source_id: str, quote: str) -> str:
    """Deterministic id for the span a quote locates in a source.

    Content-addressed over (source, quote) rather than sequential, so the same
    passage cited by two claims is *one* evidence record in the graph instead of
    two look-alikes -- and so a re-run produces byte-identical ids.
    """
    return f"ev_{short_digest(sha256_of({'source': source_id, 'quote': quote}), 12)}"
