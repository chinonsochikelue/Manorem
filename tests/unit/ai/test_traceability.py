"""Tracing what the video says back to what the research established.

Every reference the story planner or the script writer emits is held against the
brief, and the four outcomes sit at four different severities on purpose. A
dangling id is an error because it would put an untraceable sentence into
narration. A contradicted claim stated outright is a warning because the planner
made a visible choice. An unused claim and an untraced line are informational,
because a short explainer legitimately leaves research behind and a rhetorical
question asserts nothing.
"""

from __future__ import annotations

from manorem_ai.agents.models import Beat, BeatClaim, ClaimTreatment, Script, StoryOutline
from manorem_ai.research import Claim, ClaimStatus, ResearchBrief
from manorem_ai.traceability import validate_traceability
from manorem_core import Code
from manorem_ir import NarrationRole, NarrationSegment
from tests.support.diag import error_codes, only, warning_codes

IDEA = "How GPS determines your location."
CLAIM_ID = "gps_trilaterates"
GPS_TEXT = "GPS trilaterates position from satellite timing."


def brief(status: ClaimStatus = ClaimStatus.SUPPORTED) -> ResearchBrief:
    return ResearchBrief(
        idea=IDEA,
        claims=(Claim(id=CLAIM_ID, text=GPS_TEXT, status=status),),
    )


def outline(*links: BeatClaim) -> StoryOutline:
    return StoryOutline(
        title="How GPS Works",
        arc="question_led",
        rationale="A how-does-it-work explainer suits a question-led arc.",
        beats=(
            Beat(
                id="beat_0",
                role=NarrationRole.HOOK,
                purpose="Establish the question.",
                visual_intent="Show a phone asking where it is.",
                claims=links,
            ),
        ),
    )


def script(*claim_ids: str) -> Script:
    return Script(
        segments=(
            NarrationSegment(
                id="line_0", text="A receiver trilaterates its position.", claims=[*claim_ids]
            ),
        )
    )


def test_a_claim_id_nobody_researched_is_rejected() -> None:
    bag = validate_traceability(outline(BeatClaim(claim_id=CLAIM_ID)), script(CLAIM_ID), brief())
    assert not bag.has_errors
    assert bag.codes() == set()

    fabricated = validate_traceability(
        outline(BeatClaim(claim_id="made_up_claim")), script(), brief()
    )
    only(fabricated, Code.RES807_MISSING_CLAIM_EVIDENCE)
    assert fabricated.has_errors


def test_a_segment_citing_a_claim_nobody_researched_is_rejected() -> None:
    bag = validate_traceability(outline(), script("made_up_claim"), brief())
    only(bag, Code.RES807_MISSING_CLAIM_EVIDENCE)
    assert bag.has_errors


def test_a_contradicted_claim_stated_outright_is_a_warning_not_an_error() -> None:
    contested = brief(ClaimStatus.CONTRADICTED)
    bag = validate_traceability(
        outline(BeatClaim(claim_id=CLAIM_ID, treatment=ClaimTreatment.USES)),
        script(CLAIM_ID),
        contested,
    )
    only(bag, Code.RES814_CONTRADICTED_CLAIM_UNQUALIFIED)
    assert warning_codes(bag) == {Code.RES814_CONTRADICTED_CLAIM_UNQUALIFIED}
    assert not bag.has_errors  # a plan we disagree with still builds


def test_a_contradicted_claim_the_planner_qualified_is_left_alone() -> None:
    for treatment in (ClaimTreatment.QUALIFIES, ClaimTreatment.PRESENTS_DISAGREEMENT):
        bag = validate_traceability(
            outline(BeatClaim(claim_id=CLAIM_ID, treatment=treatment)),
            script(CLAIM_ID),
            brief(ClaimStatus.CONTRADICTED),
        )
        assert Code.RES814_CONTRADICTED_CLAIM_UNQUALIFIED not in bag.codes()


def test_a_supported_claim_stated_plainly_is_not_second_guessed() -> None:
    bag = validate_traceability(
        outline(BeatClaim(claim_id=CLAIM_ID, treatment=ClaimTreatment.USES)),
        script(CLAIM_ID),
        brief(ClaimStatus.SUPPORTED),
    )
    assert bag.codes() == set()


def test_a_claim_nothing_used_is_reported_informationally() -> None:
    bag = validate_traceability(outline(), script(), brief())
    only(bag, Code.RES812_CLAIM_UNUSED)
    assert not bag.has_errors

    referenced = validate_traceability(
        outline(BeatClaim(claim_id=CLAIM_ID)), script(CLAIM_ID), brief()
    )
    assert Code.RES812_CLAIM_UNUSED not in referenced.codes()


def test_a_segment_that_states_an_unsupported_claim_is_reported() -> None:
    # This is the "unsupported factual script content" case: the line exists, it
    # names a real claim, and the research behind that claim found no support.
    bag = validate_traceability(
        outline(BeatClaim(claim_id=CLAIM_ID)),
        script(CLAIM_ID),
        brief(ClaimStatus.UNSUPPORTED),
    )
    only(bag, Code.RES804_CLAIM_UNSUPPORTED)
    assert warning_codes(bag) == {Code.RES804_CLAIM_UNSUPPORTED}
    assert not bag.has_errors  # reported and visible, without failing the plan


def test_a_segment_that_asserts_nothing_is_reported_informationally() -> None:
    bag = validate_traceability(outline(BeatClaim(claim_id=CLAIM_ID)), script(), brief())
    only(bag, Code.RES813_UNTRACED_SCRIPT_CLAIM)
    assert not bag.has_errors

    cited = validate_traceability(outline(BeatClaim(claim_id=CLAIM_ID)), script(CLAIM_ID), brief())
    assert cited.codes() == set()
    assert error_codes(cited) == set()
