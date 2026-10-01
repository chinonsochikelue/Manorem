"""The staged orchestrator, end to end and at its guardrails.

The happy-path test drives every stage with a stub sequence and a fixture
research corpus, and asserts the run produces a video, content-addressed
digests, and -- crucially -- ``quality=None``: an M1 render is *not assessed*,
never quietly reported as good. The remaining tests are the structural
guardrails: fabricated provenance and a beat/segment mismatch each raise before
anything is rendered.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from manorem_ai import Pipeline, PipelineError, StubTTSProvider, TTSRequest
from manorem_ai.cassette import StubProvider
from manorem_ai.research import FixtureResearchProvider
from manorem_core import LocalFSStore, Settings
from manorem_ir import Aspect, narration_windows
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


@pytest.mark.skipif(not _HAS_FFMPEG, reason="end-to-end render needs ffmpeg on PATH")
def test_build_with_stub_tts_makes_audio_the_timing_authority(tmp_path: Path) -> None:
    # The same offline run, now voiced by the deterministic stub TTS: the build
    # must produce a video, persist the audio summary + digest, and write real
    # (measured, non-WPM) windows into segments.json.
    provider = StubProvider.sequence(
        [brief_citing(GPS_URL), outline(), script(), plan(), valid_scene()]
    )
    pipeline = Pipeline(
        provider,
        FixtureResearchProvider((gps_document(),)),
        store=LocalFSStore(tmp_path / "store"),
        tts=StubTTSProvider(),
    )
    result = pipeline.build(
        "How GPS determines your location.", aspect=Aspect.WIDESCREEN, workspace=tmp_path / "work"
    )

    assert result.video is not None and result.video.exists()
    assert not result.diagnostics.has_errors
    # Audio is a first-class, content-addressed artifact of the run.
    assert result.audio is not None
    assert "audio" in result.digests

    segments = json.loads((tmp_path / "work" / "audio" / "segments.json").read_text("utf-8"))
    assert segments  # one row per voiced segment
    for row in segments:
        assert row["start"] is not None and row["end"] is not None
        assert row["asset"].startswith("audio/") and row["asset"].endswith(".wav")

    # The persisted windows are the measured ones, not the WPM estimate.
    stub = StubTTSProvider()
    cfg = Settings()
    authored = valid_scene()
    first = segments[0]
    first_segment = next(s for s in authored.narration if s.id == first["segment_id"])
    measured = stub.synthesize(
        TTSRequest(
            text=first["text"],
            voice=cfg.tts_voice,
            language=cfg.tts_language,
            speed=cfg.tts_speed,
            sample_rate=cfg.tts_sample_rate,
        )
    ).duration_s
    assert first["duration_s"] == pytest.approx(measured)
    assert first["end"] == pytest.approx(measured + first_segment.pause_after)
    # A WPM-only estimate for that line would land elsewhere.
    wpm = narration_windows(authored, wpm=cfg.narration_wpm)
    assert first["end"] != pytest.approx(wpm[first["segment_id"]].end)


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
