"""Content intelligence: what extraction proves, and what it deliberately does not.

The milestone's load-bearing split is what this file pins down. Locating a quoted
span in retrieved bytes is a pure function of those bytes, so it is asserted
against exact ranges. Deciding what a span *means* for a claim goes to a model,
so what is asserted there is the pipeline's behaviour on an answer it did not
expect: an id that does not exist is discarded and reported, never snapped onto
the nearest real one, and a status is always re-derived from the links that
produced it rather than taken on trust.

The last group holds the boundary the whole milestone rests on. ``RES8xx`` findings
are errors only when a claim *claims* support it has not recorded; ordinary
research uncertainty is informational; and no research code may ever appear in
the semantic set the Visual IR repair loop reads.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from manorem_ai.research import (
    RESEARCH_REPAIR_CODES,
    AssessmentEntry,
    Claim,
    ClaimEvidenceLink,
    ClaimStatus,
    Evidence,
    EvidenceAssessment,
    EvidenceRelation,
    Locator,
    LocatorKind,
    ResearchBrief,
    ResearchRequest,
    ResearchResult,
    ResearchValidator,
    RetrievedSource,
    Source,
    SourceRef,
    apply_assessment,
    classify_locator,
    derive_status,
    evidence_id,
    extract_evidence,
    locate_quote,
    store_source_artifacts,
)
from manorem_core import SEMANTIC_ERROR_CODES, Code, DiagnosticBag, LocalFSStore, canonical_bytes
from tests.support.ai_builders import GPS_SNIPPET, GPS_URL, gps_retrieved
from tests.support.diag import error_codes, find, only, warning_codes

IDEA = "How GPS determines your location."
QUOTE = "trilaterates its position"


def request() -> ResearchRequest:
    return ResearchRequest(topic=IDEA)


def result() -> ResearchResult:
    return ResearchResult(request=request(), retrieved=(gps_retrieved(),))


def brief_with(quote: str = QUOTE, *, url: str = GPS_URL) -> ResearchBrief:
    """One claim citing ``url``; ``quote`` is what extraction will look for."""
    return ResearchBrief(
        idea=IDEA,
        claims=(
            Claim(
                id="gps_trilaterates",
                text="GPS trilaterates position from satellite timing.",
                sources=(SourceRef(url=url, quote=quote),),
            ),
        ),
    )


def evidenced_brief() -> ResearchBrief:
    """A brief whose citation has been located -- the state assessment starts from."""
    base = brief_with()
    return base.model_copy(update={"evidence": extract_evidence(base, result(), DiagnosticBag())})


# -- extraction: arithmetic over bytes ---------------------------------------


def test_locate_quote_matches_exactly_when_it_can() -> None:
    start = GPS_SNIPPET.index(QUOTE)
    assert locate_quote(GPS_SNIPPET, QUOTE) == (start, start + len(QUOTE))


def test_locate_quote_tolerates_capitalisation_and_line_breaks() -> None:
    # The mismatch a copied quotation and a fetched HTML page actually have.
    content = "A receiver\ntrilaterates\n  its position"
    span = locate_quote(content, "receiver trilaterates its position")
    assert span is not None
    assert "trilaterates" in content[span[0] : span[1]]


def test_locate_quote_refuses_to_guess() -> None:
    assert locate_quote(GPS_SNIPPET, "made-up words about the moon") is None
    assert locate_quote(GPS_SNIPPET, "   ") is None
    assert locate_quote("", QUOTE) is None


def test_locator_names_the_paragraph_it_sits_in() -> None:
    prose = "First block.\n\nSecond block."
    span = classify_locator(prose, 0, 5)
    assert span.kind is LocatorKind.PARAGRAPH
    assert span.paragraph == 0
    assert span.resolve(prose) == (0, 5)


def test_locator_names_the_section_a_span_sits_under() -> None:
    doc = "# Getting started\n\nDo the thing.\n\n# Later\n\nDo the other thing."
    start = doc.index("Do the thing")
    span = classify_locator(doc, start, start + 6)
    assert span.kind is LocatorKind.SECTION
    assert span.section == "Getting started"
    assert span.resolve(doc) == (start, start + 6)


def test_locator_falls_back_to_a_range_when_no_label_would_be_true() -> None:
    prose = "First block.\n\nSecond block."
    span = classify_locator(prose, 0, len(prose))
    assert span.kind is LocatorKind.CHAR_RANGE
    assert span.resolve(prose) == (0, len(prose))


def test_extraction_records_the_span_it_found() -> None:
    bag = DiagnosticBag()
    found = extract_evidence(brief_with(), result(), bag)

    assert not bag.has_errors
    assert len(found) == 1
    item = found[0]
    # Content-addressed: the same (source, quote) always names the same record.
    assert item.id == evidence_id(gps_retrieved().source.id, QUOTE)
    span = item.locator.resolve(GPS_SNIPPET)
    assert span is not None and item.text == GPS_SNIPPET[span[0] : span[1]]
    assert item.content_digest == gps_retrieved().source.content_digest


def test_extraction_never_fabricates_a_span_for_absent_words() -> None:
    bag = DiagnosticBag()
    found = extract_evidence(brief_with("words that are not in the source at all"), result(), bag)
    assert found == ()
    only(bag, Code.RES803_EVIDENCE_NOT_LOCATABLE)


def test_extraction_leaves_an_unretrieved_url_to_the_provenance_check() -> None:
    # RES801 owns that defect; reporting it twice would just spam the repair loop.
    bag = DiagnosticBag()
    found = extract_evidence(brief_with(url="https://example.test/elsewhere"), result(), bag)
    assert found == ()
    assert bag.codes() == set()


def test_the_same_passage_cited_twice_is_one_evidence_record() -> None:
    brief = ResearchBrief(
        idea=IDEA,
        claims=(
            Claim(id="first", text="One.", sources=(SourceRef(url=GPS_URL, quote=QUOTE),)),
            Claim(id="second", text="Two.", sources=(SourceRef(url=GPS_URL, quote=QUOTE),)),
        ),
    )
    assert len(extract_evidence(brief, result(), DiagnosticBag())) == 1


# -- assessment: judgement, bounded by the schema ---------------------------


def test_a_verdict_becomes_a_link_and_a_derived_status() -> None:
    brief = evidenced_brief()
    item = brief.evidence[0]
    bag = DiagnosticBag()
    assessed = apply_assessment(
        brief,
        EvidenceAssessment(
            assessments=(
                AssessmentEntry(
                    claim_id="gps_trilaterates",
                    evidence_id=item.id,
                    relation=EvidenceRelation.SUPPORTS,
                    note="The span states exactly this.",
                ),
            )
        ),
        bag,
    )

    assert bag.codes() == set()
    claim = assessed.claims[0]
    assert claim.status is ClaimStatus.SUPPORTED
    assert [link.evidence_id for link in claim.evidence] == [item.id]
    assert ResearchValidator().validate(assessed, result()).codes() == set()


def test_ids_that_do_not_exist_are_discarded_rather_than_snapped_to_the_nearest() -> None:
    bag = DiagnosticBag()
    assessed = apply_assessment(
        evidenced_brief(),
        EvidenceAssessment(
            assessments=(
                AssessmentEntry(
                    claim_id="gps_trilaterates",
                    evidence_id="ev_nope",
                    relation=EvidenceRelation.SUPPORTS,
                ),
                AssessmentEntry(
                    claim_id="no_such_claim",
                    evidence_id="ev_also_nope",
                    relation=EvidenceRelation.SUPPORTS,
                ),
            )
        ),
        bag,
    )

    assert len(find(bag, Code.RES807_MISSING_CLAIM_EVIDENCE)) == 2
    assert assessed.claims[0].evidence == ()
    assert assessed.claims[0].status is ClaimStatus.UNASSESSED


def test_a_contradiction_is_never_averaged_away() -> None:
    links = (
        ClaimEvidenceLink(
            claim_id="gps_trilaterates", evidence_id="ev_a", relation=EvidenceRelation.SUPPORTS
        ),
        ClaimEvidenceLink(
            claim_id="gps_trilaterates", evidence_id="ev_b", relation=EvidenceRelation.CONTRADICTS
        ),
    )
    assert derive_status(links) is ClaimStatus.CONTRADICTED


@pytest.mark.parametrize(
    ("relations", "expected"),
    [
        (
            (),
            ClaimStatus.UNASSESSED,
        ),  # nobody looked, which is not "we looked and it is not backed"
        (
            (EvidenceRelation.CONTRADICTS, EvidenceRelation.SUPPORTS),
            ClaimStatus.CONTRADICTED,
        ),
        (
            (EvidenceRelation.SUPPORTS, EvidenceRelation.PARTIALLY_SUPPORTS),
            ClaimStatus.PARTIALLY_SUPPORTED,
        ),
        ((EvidenceRelation.SUPPORTS,), ClaimStatus.SUPPORTED),
        ((EvidenceRelation.PARTIALLY_SUPPORTS,), ClaimStatus.PARTIALLY_SUPPORTED),
        ((EvidenceRelation.CONTEXTUALIZES,), ClaimStatus.UNSUPPORTED),  # context is not support
    ],
)
def test_status_never_rounds_uncertainty_up(
    relations: tuple[EvidenceRelation, ...], expected: ClaimStatus
) -> None:
    links = tuple(
        ClaimEvidenceLink(claim_id="c", evidence_id=f"ev_{index}", relation=relation)
        for index, relation in enumerate(relations)
    )
    assert derive_status(links) is expected


# -- validation: one graph, every reference checked --------------------------


def test_no_score_of_truth_exists_in_the_vocabulary() -> None:
    # The invariant everything else rests on: there is no number anywhere that
    # could be read as "how true is this", so no downstream stage can quietly
    # start ranking claims by one.
    forbidden = {"confidence", "truth_score", "factuality", "reliability", "probability", "score"}
    for model in (Claim, Evidence, ClaimEvidenceLink, ResearchBrief, Source, RetrievedSource):
        smuggled = forbidden & set(model.model_fields)
        assert not smuggled, f"{model.__name__} exposes a truth-ish field: {sorted(smuggled)}"


def test_a_claim_cannot_claim_support_it_has_not_recorded() -> None:
    brief = evidenced_brief()
    claims = (brief.claims[0].model_copy(update={"status": ClaimStatus.SUPPORTED}),)
    bag = ResearchValidator().validate(brief.model_copy(update={"claims": claims}), result())

    only(bag, Code.RES804_CLAIM_UNSUPPORTED)
    assert bag.has_errors  # a fabricated status is a defect, and a repairable one


def test_looking_and_finding_no_support_is_reported_never_silenced() -> None:
    # The one status that used to fall through silently: research *did* look, and
    # nothing it found backed the claim. That is a fact to report, not a defect
    # to fail an honest run over.
    base = evidenced_brief()
    claim = base.claims[0].model_copy(
        update={
            "status": ClaimStatus.UNSUPPORTED,
            "evidence": (
                ClaimEvidenceLink(
                    claim_id="gps_trilaterates",
                    evidence_id=base.evidence[0].id,
                    relation=EvidenceRelation.CONTEXTUALIZES,
                ),
            ),
        }
    )
    bag = ResearchValidator().validate(base.model_copy(update={"claims": (claim,)}), result())

    only(bag, Code.RES804_CLAIM_UNSUPPORTED)
    assert warning_codes(bag) == {Code.RES804_CLAIM_UNSUPPORTED}
    assert not bag.has_errors


def test_a_status_that_disagrees_with_its_own_links_is_rejected() -> None:
    brief = evidenced_brief()
    claim = brief.claims[0]
    links = (
        ClaimEvidenceLink(
            claim_id=claim.id,
            evidence_id=brief.evidence[0].id,
            relation=EvidenceRelation.CONTEXTUALIZES,
        ),
    )
    tampered = claim.model_copy(update={"status": ClaimStatus.SUPPORTED, "evidence": links})
    bag = ResearchValidator().validate(brief.model_copy(update={"claims": (tampered,)}), result())

    only(bag, Code.RES804_CLAIM_UNSUPPORTED)


def test_nobody_looking_is_informational_not_a_failure() -> None:
    bag = ResearchValidator().validate(brief_with(), result())
    only(bag, Code.RES811_CLAIM_UNASSESSED)
    assert not bag.has_errors
    assert bag.codes() == {Code.RES811_CLAIM_UNASSESSED}


def test_duplicate_ids_are_rejected() -> None:
    brief = ResearchBrief(
        idea=IDEA, claims=(Claim(id="dup", text="A."), Claim(id="dup", text="B."))
    )
    bag = ResearchValidator().validate(brief, result())
    only(bag, Code.RES810_DUPLICATE_ID)


def test_evidence_may_only_name_a_source_from_this_run() -> None:
    orphan = Evidence(
        id="ev_orphan",
        source_id="src_absent",
        locator=Locator(kind=LocatorKind.CHAR_RANGE, start=0, end=5),
        text="hello",
        content_digest="not-a-real-digest",
    )
    brief = brief_with().model_copy(update={"evidence": (orphan,)})
    bag = ResearchValidator().validate(brief, result())
    only(bag, Code.RES807_MISSING_CLAIM_EVIDENCE)


def test_a_link_to_evidence_that_does_not_exist_is_rejected() -> None:
    claim = Claim(
        id="gps_trilaterates",
        text="GPS trilaterates position from satellite timing.",
        status=ClaimStatus.SUPPORTED,
        evidence=(
            ClaimEvidenceLink(
                claim_id="gps_trilaterates",
                evidence_id="ev_absent",
                relation=EvidenceRelation.SUPPORTS,
            ),
        ),
    )
    bag = ResearchValidator().validate(ResearchBrief(idea=IDEA, claims=(claim,)), result())
    only(bag, Code.RES807_MISSING_CLAIM_EVIDENCE)


def test_a_stored_artifact_is_read_back_and_rehashed(tmp_path: Path) -> None:
    store = LocalFSStore(tmp_path / "store")

    missing = ResearchValidator().validate(brief_with(), result(), store=store)
    only(missing, Code.RES802_SOURCE_ARTIFACT_INVALID)

    store_source_artifacts(result(), store)
    clean = ResearchValidator().validate(brief_with(), result(), store=store)
    assert not clean.has_errors

    source = result().sources[0]
    store.put_bytes(
        source.artifact_key,
        canonical_bytes({"source": source.model_dump(mode="json"), "content": "tampered"}),
    )
    altered = ResearchValidator().validate(brief_with(), result(), store=store)
    only(altered, Code.RES808_SOURCE_CONTENT_CHANGED)


def test_only_defects_a_re_run_can_clear_are_repairable() -> None:
    assert Code.RES801_UNRETRIEVED_SOURCE in RESEARCH_REPAIR_CODES
    assert Code.RES803_EVIDENCE_NOT_LOCATABLE in RESEARCH_REPAIR_CODES
    assert Code.RES804_CLAIM_UNSUPPORTED in RESEARCH_REPAIR_CODES
    # A missing file, a dead network or a state worth *recording* are not things
    # asking the model again can fix.
    assert Code.RES802_SOURCE_ARTIFACT_INVALID not in RESEARCH_REPAIR_CODES
    assert Code.RES809_RESEARCH_PROVIDER_FAILED not in RESEARCH_REPAIR_CODES
    assert Code.RES811_CLAIM_UNASSESSED not in RESEARCH_REPAIR_CODES
    assert Code.RES812_CLAIM_UNUSED not in RESEARCH_REPAIR_CODES


def test_no_research_code_reaches_the_ir_repair_loop() -> None:
    research_codes = {code for code in Code if code.value.startswith("RES")}
    assert research_codes
    assert research_codes & SEMANTIC_ERROR_CODES == set()


def test_error_codes_only_fire_where_a_claim_overreaches() -> None:
    # The same brief, once honestly backed and once merely asserted: only the
    # overreach is an error, because everything else is a state to record.
    backed = evidenced_brief()
    claim = backed.claims[0]
    honest = claim.model_copy(
        update={
            "status": ClaimStatus.SUPPORTED,
            "evidence": (
                ClaimEvidenceLink(
                    claim_id=claim.id,
                    evidence_id=backed.evidence[0].id,
                    relation=EvidenceRelation.SUPPORTS,
                ),
            ),
        }
    )
    assert (
        error_codes(
            ResearchValidator().validate(backed.model_copy(update={"claims": (honest,)}), result())
        )
        == set()
    )

    asserted = claim.model_copy(update={"status": ClaimStatus.SUPPORTED})
    overreaching = backed.model_copy(update={"claims": (asserted,)})
    assert error_codes(ResearchValidator().validate(overreaching, result())) == {
        Code.RES804_CLAIM_UNSUPPORTED
    }
