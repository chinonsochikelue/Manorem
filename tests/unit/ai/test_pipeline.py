"""The staged orchestrator, end to end and at its guardrails.

The happy-path test drives every stage with a stub sequence and a fixture
research corpus, and asserts the run produces a video, content-addressed
digests, and -- crucially -- ``quality=None``: an M1 render is *not assessed*,
never quietly reported as good. The remaining tests are the structural
guardrails: fabricated provenance and a beat/segment mismatch each raise before
anything is rendered.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from manorem_ai import Pipeline, PipelineError
from manorem_ai.cassette import StubProvider
from manorem_ai.research import FixtureResearchProvider
from manorem_core import LocalFSStore
from manorem_ir import Aspect
from tests.support.ai_builders import (
    GPS_URL,
    brief_citing,
    gps_document,
    outline,
    plan,
    script,
)
from tests.support.ir_builders import valid_scene

_HAS_FFMPEG = shutil.which("ffmpeg") is not None


def _pipeline(provider: StubProvider, tmp_path: Path) -> Pipeline:
    return Pipeline(
        provider,
        FixtureResearchProvider((gps_document(),)),
        store=LocalFSStore(tmp_path / "store"),
    )


@pytest.mark.skipif(not _HAS_FFMPEG, reason="end-to-end render needs ffmpeg on PATH")
def test_build_produces_a_video_and_leaves_quality_unassessed(tmp_path: Path) -> None:
    provider = StubProvider.sequence(
        [brief_citing(GPS_URL), outline(), script(), plan(), valid_scene()]
    )
    result = _pipeline(provider, tmp_path).build(
        "How GPS determines your location.", aspect=Aspect.WIDESCREEN, workspace=tmp_path / "work"
    )
    assert result.video is not None
    assert result.video.exists()
    assert result.repair_attempts == 0
    # An M1 render is NOT assessed -- never conflated with "assessed and fine".
    assert result.quality is None
    assert not result.diagnostics.has_errors
    # Every stage was persisted content-addressed.
    assert {"brief", "outline", "script", "ir", "renderplan"} <= set(result.digests)


def test_fabricated_provenance_raises_before_story(tmp_path: Path) -> None:
    # The brief cites a URL the fixture corpus never returned.
    provider = StubProvider.sequence([brief_citing("https://example.test/made-up")])
    with pytest.raises(PipelineError, match="fabricated provenance"):
        _pipeline(provider, tmp_path).build("How GPS works.", workspace=tmp_path / "work")


def test_beat_segment_mismatch_raises(tmp_path: Path) -> None:
    # Two beats but only one narration segment: each beat needs its own segment.
    provider = StubProvider.sequence([brief_citing(GPS_URL), outline(beats=2), script(segments=1)])
    with pytest.raises(PipelineError, match="segments for"):
        _pipeline(provider, tmp_path).build("How GPS works.", workspace=tmp_path / "work")
