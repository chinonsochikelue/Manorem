"""Content intelligence in the pipeline: what it records, and what it refuses to pass on.

The research stage is exercised end to end rather than through mocks, because the
properties that matter are *ordering* properties: evidence is extracted and
assessed before a beat is planned, artifacts are written before validation runs
so a failed build is still inspectable, and a repair loop stops at the configured
cap instead of asking until the model happens to agree. The failure paths are the
other half -- a retrieval that raises is reported and never becomes a source, and
a claim id nobody researched never reaches the renderer.

Tests that must reach the render step are gated on ffmpeg, matching the rest of
the pipeline suite; the refusal paths raise before any rendering and run
everywhere.
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

import pytest

from manorem_ai import Pipeline, PipelineError
from manorem_ai.agents.models import Script
from manorem_ai.cassette import StubProvider
from manorem_ai.research import (
    AssessmentEntry,
    Claim,
    EvidenceAssessment,
    EvidenceRelation,
    FixtureResearchProvider,
    ResearchBrief,
    ResearchError,
    ResearchProvider,
    ResearchRequest,
    ResearchResult,
    RetrievedSource,
    SourceRef,
    evidence_id,
)
from manorem_core import Code, DiagnosticBag, LocalFSStore, Settings, Severity
from manorem_ir import Aspect, NarrationSegment
from tests.support.ai_builders import GPS_URL, gps_retrieved, outline, plan
from tests.support.ir_builders import valid_scene

_HAS_FFMPEG = shutil.which("ffmpeg") is not None
IDEA = "How GPS determines your location."
QUOTE = "trilaterates its position"


def _corpus() -> tuple[RetrievedSource, ...]:
    return (gps_retrieved(),)


def _brief(quote: str = QUOTE) -> ResearchBrief:
    return ResearchBrief(
        idea=IDEA,
        claims=(
            Claim(
                id="gps_trilaterates",
                text="GPS trilaterates position from satellite timing.",
                sources=(SourceRef(url=GPS_URL, quote=quote),),
            ),
        ),
    )


def _assessment() -> EvidenceAssessment:
    return EvidenceAssessment(
        assessments=(
            AssessmentEntry(
                claim_id="gps_trilaterates",
                evidence_id=evidence_id(gps_retrieved().source.id, QUOTE),
                relation=EvidenceRelation.SUPPORTS,
                note="The span states exactly this.",
            ),
        )
    )


def _script_citing(*claim_ids: str) -> Script:
    """The default script, with claim references added."""
    return Script(
        segments=(
            NarrationSegment(id="line_0", text="Where are you right now?", claims=[*claim_ids]),
        )
    )


def _pipeline(
    llm: StubProvider,
    tmp_path: Path,
    *,
    research: bool = True,
    research_provider: ResearchProvider | None = None,
    fallback: ResearchProvider | None = None,
    settings: Settings | None = None,
) -> Pipeline:
    return Pipeline(
        llm,
        research_provider or FixtureResearchProvider(_corpus()),
        store=LocalFSStore(tmp_path / "store"),
        settings=settings or Settings(research_enabled=research),
        research_fallback=fallback,
    )


@pytest.mark.skipif(not _HAS_FFMPEG, reason="end-to-end render needs ffmpeg on PATH")
def test_research_mode_persists_inspectable_artifacts(tmp_path: Path) -> None:
    llm = StubProvider.sequence(
        [_brief(), _assessment(), outline(), _script_citing(), plan(), valid_scene()]
    )
    result = _pipeline(llm, tmp_path).build(
        IDEA, aspect=Aspect.WIDESCREEN, workspace=tmp_path / "work"
    )

    research = tmp_path / "work" / "research"
    assert (research / "manifest.json").is_file()
    assert (research / "evidence.json").is_file()
    assert "research" in result.digests
    assert result.research_attempts == 0
    assert not result.diagnostics.has_errors
    # Research that never reached the script is reported, but never blocks.
    codes = {d.code for d in result.diagnostics}
    assert Code.RES812_CLAIM_UNUSED in codes
    assert Code.RES813_UNTRACED_SCRIPT_CLAIM in codes
    assert all(d.severity is not Severity.ERROR for d in result.diagnostics)


@pytest.mark.skipif(not _HAS_FFMPEG, reason="end-to-end render needs ffmpeg on PATH")
def test_content_intelligence_is_opt_in(tmp_path: Path) -> None:
    llm = StubProvider.sequence([_brief(), outline(), _script_citing(), plan(), valid_scene()])
    result = _pipeline(llm, tmp_path, research=False).build(
        IDEA, aspect=Aspect.WIDESCREEN, workspace=tmp_path / "work"
    )

    assert not (tmp_path / "work" / "research").exists()
    assert "research" not in result.digests
    assert result.research_attempts == 0


@pytest.mark.skipif(not _HAS_FFMPEG, reason="end-to-end render needs ffmpeg on PATH")
def test_a_quote_that_cannot_be_found_gets_one_bounded_repair(tmp_path: Path) -> None:
    llm = StubProvider.sequence(
        [
            _brief("words that are not in the source at all"),
            _brief(),
            _assessment(),
            outline(),
            _script_citing(),
            plan(),
            valid_scene(),
        ]
    )
    result = _pipeline(llm, tmp_path).build(IDEA, workspace=tmp_path / "work")

    assert result.research_attempts == 1
    assert not result.diagnostics.has_errors
    assert (tmp_path / "work" / "research" / "manifest.json").is_file()


def test_repair_stops_at_the_cap_and_fails_loudly(tmp_path: Path) -> None:
    # Every attempt is broken the same way, so the loop must stop at the cap
    # rather than keep asking until the model happens to agree.
    broken = _brief("words that are not in the source at all")
    always = StubProvider(lambda _prompt, _schema: broken)
    pipeline = _pipeline(always, tmp_path)

    with pytest.raises(PipelineError, match="bounded repair loop"):
        pipeline.build(IDEA, workspace=tmp_path / "work")


def test_a_claim_id_nobody_researched_never_reaches_the_renderer(tmp_path: Path) -> None:
    llm = StubProvider.sequence(
        [_brief(), _assessment(), outline(), _script_citing("made_up_claim")]
    )
    pipeline = _pipeline(llm, tmp_path)
    with pytest.raises(PipelineError, match="claims that do not exist"):
        pipeline.build(IDEA, workspace=tmp_path / "work")


class _ExplodingProvider:
    """A retrieval backend that cannot produce a result. Never a source."""

    name = "exploding"
    cache_identity = ""

    def research(self, request: ResearchRequest) -> ResearchResult:
        raise ResearchError("gateway unreachable")


def test_a_provider_failure_stops_the_build_without_inventing_a_source(tmp_path: Path) -> None:
    pipeline = _pipeline(
        StubProvider.sequence([]),
        tmp_path,
        research_provider=_ExplodingProvider(),
    )
    with pytest.raises(PipelineError, match="research retrieval failed"):
        pipeline.build(IDEA, workspace=tmp_path / "work")


@pytest.mark.skipif(not _HAS_FFMPEG, reason="end-to-end render needs ffmpeg on PATH")
def test_a_provider_failure_falls_back_and_stays_on_the_record(tmp_path: Path) -> None:
    llm = StubProvider.sequence(
        [_brief(), _assessment(), outline(), _script_citing(), plan(), valid_scene()]
    )
    pipeline = _pipeline(
        llm,
        tmp_path,
        research_provider=_ExplodingProvider(),
        fallback=FixtureResearchProvider(_corpus()),
    )
    result = pipeline.build(IDEA, aspect=Aspect.WIDESCREEN, workspace=tmp_path / "work")

    reported = [d for d in result.diagnostics if d.code is Code.RES809_RESEARCH_PROVIDER_FAILED]
    assert len(reported) == 1
    assert reported[0].severity is Severity.WARNING  # the substitution is on the record
    assert not result.diagnostics.has_errors


class _CountingProvider:
    """The one shape worth caching: a live backend that costs a round trip."""

    name = "counting"
    cache_identity = "gateway-v1"

    def __init__(self) -> None:
        self.calls = 0

    def research(self, request: ResearchRequest) -> ResearchResult:
        self.calls += 1
        return ResearchResult(request=request, retrieved=_corpus())


def test_a_retrieval_is_reused_within_its_ttl_and_refreshed_beyond_it(tmp_path: Path) -> None:
    # Driven through the retrieval seam directly: the cache's whole contract is
    # "the second lookup does not call the provider", and a full build would bury
    # that under a render.
    provider = _CountingProvider()
    pipeline = _pipeline(
        StubProvider.sequence([]),
        tmp_path,
        research_provider=provider,
        settings=Settings(research_enabled=True, research_cache_ttl_s=60),
    )
    request = pipeline._research_request(IDEA)
    bag = DiagnosticBag()

    first = pipeline._retrieve(request, bag)
    second = pipeline._retrieve(request, bag)
    assert provider.calls == 1
    assert second == first

    cached = next((tmp_path / "store" / "research" / "cache").glob("*.json"))
    stale = time.time() - 120
    os.utime(cached, (stale, stale))
    pipeline._retrieve(request, bag)
    assert provider.calls == 2  # expired, so it fetched again rather than going stale
