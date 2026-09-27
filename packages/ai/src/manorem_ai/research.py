"""Research: what a model claims, and the one thing provenance actually proves.

The research layer turns an idea into a :class:`ResearchBrief` -- claims, the
entities they involve, candidate visuals, and the questions left open. Every
field a model fills in here is *model-asserted*: :class:`Claim.kind` and
:class:`Claim.confidence` are the model's own estimate of epistemic weight, not a
verified property, and the types and the field docs say so out loud.

:class:`ProvenanceValidator` enforces the one guarantee this layer can actually
make: **every cited URL was genuinely retrieved.** It rejects a
:class:`SourceRef` whose URL is not in the retrieved document set (``RES801``),
which makes a *fabricated* citation structurally impossible. It deliberately does
**not** check that the retrieved source supports the claim -- a real URL cited for
something it never says passes, and that is the documented limit. Claim-to-evidence
verification is a future research-layer capability, and nothing here implies it
exists yet.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from manorem_core import Code, DiagnosticBag, Slug, pointer, sha256_of
from manorem_ir import ClaimKind

__all__ = [
    "Claim",
    "Document",
    "Entity",
    "FixtureResearchProvider",
    "ProvenanceValidator",
    "ResearchBrief",
    "ResearchProvider",
    "SourceRef",
    "VisualCandidate",
]


class Document(BaseModel):
    """One retrieved source. ``content_hash`` pins exactly what was fetched."""

    model_config = ConfigDict(frozen=True)

    url: str = Field(min_length=1)
    title: str = Field(default="", max_length=300)
    snippet: str = Field(default="", max_length=4000)
    retrieved_at: datetime
    content_hash: str = Field(min_length=1)

    @classmethod
    def of(cls, url: str, title: str, snippet: str, *, retrieved_at: datetime) -> Document:
        """Build a document, deriving ``content_hash`` from the snippet."""
        return cls(
            url=url,
            title=title,
            snippet=snippet,
            retrieved_at=retrieved_at,
            content_hash=sha256_of(snippet),
        )


class SourceRef(BaseModel):
    """A citation on a claim: the URL, and optionally the passage relied on.

    The URL is the whole of what provenance checks. ``quote`` is a convenience for
    a human reader and, later, the input to claim-to-evidence verification -- it is
    not validated against the source in M1.
    """

    model_config = ConfigDict(frozen=True)

    url: str = Field(min_length=1)
    quote: str = Field(default="", max_length=2000)


class Claim(BaseModel):
    """One assertion the brief makes, with its model-asserted epistemic weight.

    ``kind`` and ``confidence`` come from the model. Provenance proves the sources
    were fetched; it says nothing about whether they support the claim. Downstream
    surfaces must label these as asserted, not verified.
    """

    model_config = ConfigDict(frozen=True)

    id: Slug
    text: str = Field(min_length=1, max_length=2000)
    kind: ClaimKind = ClaimKind.INFERENCE
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    sources: tuple[SourceRef, ...] = ()


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
    """The research stage's output: the raw material the story is built from."""

    model_config = ConfigDict(frozen=True)

    idea: str = Field(min_length=1, max_length=2000)
    claims: tuple[Claim, ...] = ()
    entities: tuple[Entity, ...] = ()
    visual_candidates: tuple[VisualCandidate, ...] = ()
    open_questions: tuple[str, ...] = ()


@runtime_checkable
class ResearchProvider(Protocol):
    """A source of retrieved documents for an idea.

    M1 ships :class:`FixtureResearchProvider` only; a live search backend is a
    later adapter behind this same seam.
    """

    name: str

    def retrieve(self, query: str, *, limit: int = 8) -> tuple[Document, ...]: ...


class FixtureResearchProvider:
    """Serve a fixed corpus, so research is offline and deterministic.

    Every document is returned regardless of the query -- the corpus is already
    scoped to the subject. What matters for the tests is that the URLs a brief may
    cite are exactly the ones this returns, which is what
    :class:`ProvenanceValidator` checks against.
    """

    name = "fixture"

    def __init__(self, documents: tuple[Document, ...]) -> None:
        self._documents = documents

    def retrieve(self, query: str, *, limit: int = 8) -> tuple[Document, ...]:  # noqa: ARG002
        return self._documents[:limit]


class ProvenanceValidator:
    """Reject citations to URLs that were never retrieved. Provenance, not proof.

    This is the entirety of the guarantee: a cited URL must be in the retrieved
    set. A retrieved-but-unsupported claim passes -- deliberately -- because
    checking that a source *supports* a claim is a separate, future capability and
    this validator must not be mistaken for it.
    """

    def validate(self, brief: ResearchBrief, documents: tuple[Document, ...]) -> DiagnosticBag:
        bag = DiagnosticBag()
        retrieved = {doc.url for doc in documents}
        for claim_index, claim in enumerate(brief.claims):
            for source_index, source in enumerate(claim.sources):
                if source.url not in retrieved:
                    bag.add(
                        Code.RES801_UNRETRIEVED_SOURCE,
                        f"claim {claim.id!r} cites {source.url!r}, which was not retrieved",
                        pointer=pointer("claims", claim_index, "sources", source_index),
                        object_id=claim.id,
                        hint=(
                            "Every cited URL must come from a retrieved document. This "
                            "checks provenance only -- not that the source supports the claim."
                        ),
                    )
        return bag
