"""Tracing every planned and spoken statement back to a research claim.

The research layer can prove a quote is really in a retrieved source. What it
cannot do on its own is notice that the *story* went on to say something else.
This module closes that half of the loop: it walks the outline and the script
and holds every claim reference against the claims that actually exist.

Five findings, at three severities:

* a reference to a claim that does not exist is an **error** (``RES807``) --
  a fabricated id would put an untraceable sentence into narration, so the
  pipeline raises before the render, exactly as fabricated provenance does.
* a beat that presents a contradicted claim as if nothing were wrong (``RES814``)
  and a segment that states an unsupported claim as fact (``RES804``) are
  **warnings**: the planner or the writer chose to say it anyway, and that choice
  is now visible rather than implied. Unsupported is the milder of the two, so it
  does not get the louder voice -- but it is never silent either.
* an unused claim (``RES812``) and a segment with no claim reference
  (``RES813``) are **informational**. Research that never made it into the
  script is a fact worth reporting and not worth failing a build over -- some
  claims simply do not belong in a short explainer, and a rhetorical question
  asserts nothing.

JSON Pointers here name their artifact in the first segment (``/outline/...``
versus ``/script/...``) because these diagnostics span two documents; every
other pointer in the system points into a single one.
"""

from __future__ import annotations

from manorem_ai.agents.models import ClaimTreatment, Script, StoryOutline
from manorem_ai.research import Claim, ClaimStatus, ResearchBrief
from manorem_core import Code, DiagnosticBag, Severity, pointer

__all__ = ["validate_traceability"]


def validate_traceability(
    outline: StoryOutline,
    script: Script,
    brief: ResearchBrief,
) -> DiagnosticBag:
    """Check the outline's and the script's claim references against the brief."""
    bag = DiagnosticBag()
    known = {claim.id: claim for claim in brief.claims}
    used: set[str] = set()

    _check_beats(outline, known, used, bag)
    _check_segments(script, known, used, bag)

    for claim in brief.claims:
        if claim.id not in used:
            bag.add(
                Code.RES812_CLAIM_UNUSED,
                f"claim {claim.id!r} is not referenced by any beat or segment",
                pointer=pointer("claims", claim.id),
                object_id=claim.id,
                severity=Severity.INFO,
                hint=(
                    "Reported, not failed: research that never reaches the script is a "
                    "fact worth seeing, not a defect."
                ),
            )
    return bag


def _check_beats(
    outline: StoryOutline,
    known: dict[str, Claim],
    used: set[str],
    bag: DiagnosticBag,
) -> None:
    for beat_index, beat in enumerate(outline.beats):
        for link_index, link in enumerate(beat.claims):
            base = pointer("outline", "beats", beat_index, "claims", link_index)
            claim = known.get(link.claim_id)
            if claim is None:
                bag.add(
                    Code.RES807_MISSING_CLAIM_EVIDENCE,
                    f"beat {beat.id!r} references claim {link.claim_id!r}, which does not exist",
                    pointer=f"{base}/claim_id",
                    object_id=beat.id,
                    hint="Beats may only rest on claims from this run's brief.",
                )
                continue
            used.add(link.claim_id)
            if claim.status is ClaimStatus.CONTRADICTED and link.treatment is ClaimTreatment.USES:
                bag.warn(
                    Code.RES814_CONTRADICTED_CLAIM_UNQUALIFIED,
                    f"beat {beat.id!r} states contradicted claim {link.claim_id!r} outright",
                    pointer=f"{base}/treatment",
                    object_id=beat.id,
                    hint="Qualify it, present the disagreement, or omit the claim.",
                )


def _check_segments(
    script: Script,
    known: dict[str, Claim],
    used: set[str],
    bag: DiagnosticBag,
) -> None:
    for seg_index, segment in enumerate(script.segments):
        if not segment.claims:
            bag.add(
                Code.RES813_UNTRACED_SCRIPT_CLAIM,
                f"segment {segment.id!r} references no claim",
                pointer=pointer("script", "segments", seg_index, "claims"),
                object_id=segment.id,
                severity=Severity.INFO,
                hint=(
                    "Factual lines should cite the claim they draw on; rhetorical lines "
                    "may leave this empty."
                ),
            )
            continue
        for claim_index, claim_id in enumerate(segment.claims):
            if claim_id not in known:
                bag.add(
                    Code.RES807_MISSING_CLAIM_EVIDENCE,
                    f"segment {segment.id!r} references claim {claim_id!r}, which does not exist",
                    pointer=pointer("script", "segments", seg_index, "claims", claim_index),
                    object_id=segment.id,
                    hint="A fabricated claim id cannot be traced to any source; it is rejected.",
                )
            else:
                used.add(claim_id)
                if known[claim_id].status is ClaimStatus.UNSUPPORTED:
                    bag.warn(
                        Code.RES804_CLAIM_UNSUPPORTED,
                        f"segment {segment.id!r} states claim {claim_id!r} as fact, but "
                        "its own evidence does not support it",
                        pointer=pointer("script", "segments", seg_index, "claims", claim_index),
                        object_id=segment.id,
                        hint=(
                            "Unsupported factual content is reported, not passed on: "
                            "qualify the line, present the disagreement, or drop it."
                        ),
                    )
