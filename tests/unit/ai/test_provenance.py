"""``ProvenanceValidator`` -- provenance, and the limit it deliberately keeps.

Two tests carry the guardrail. A citation to a URL that was not retrieved is a
``RES801`` error: fabricated citations are structurally impossible. A citation to
a URL that *was* retrieved but does not support the claim **passes** -- because
this validator checks provenance, not entailment, and that limit is a documented
design decision, not a gap to close here.
"""

from __future__ import annotations

from manorem_ai import Claim, ProvenanceValidator, ResearchBrief, SourceRef
from manorem_ai.research import FixtureResearchProvider
from manorem_core import Code
from tests.support.ai_builders import GPS_URL, brief_citing, gps_document
from tests.support.diag import error_codes


def test_unretrieved_url_is_rejected() -> None:
    documents = (gps_document(),)
    brief = brief_citing("https://example.test/not-fetched")
    bag = ProvenanceValidator().validate(brief, documents)
    assert Code.RES801_UNRETRIEVED_SOURCE in error_codes(bag)


def test_retrieved_url_passes() -> None:
    documents = (gps_document(),)
    bag = ProvenanceValidator().validate(brief_citing(GPS_URL), documents)
    assert not bag.has_errors


def test_retrieved_but_unsupported_claim_passes_by_design() -> None:
    # The source is real (retrieved), but says nothing about the claim's content.
    # Provenance validation is not claim-to-evidence verification, so this passes.
    documents = (gps_document(),)
    brief = ResearchBrief(
        idea="How GPS works.",
        claims=(
            Claim(
                id="unsupported",
                text="The moon is made of cheese.",
                sources=(SourceRef(url=GPS_URL),),
            ),
        ),
    )
    bag = ProvenanceValidator().validate(brief, documents)
    assert not bag.has_errors


def test_fixture_provider_respects_limit() -> None:
    docs = tuple(gps_document() for _ in range(3))
    provider = FixtureResearchProvider(docs)
    assert len(provider.retrieve("anything", limit=2)) == 2
