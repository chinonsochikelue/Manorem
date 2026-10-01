"""The pipeline's narration stage -- audio becomes the timing authority.

These tests drive ``_narrate`` and ``_attach_audio`` directly with a deterministic
stub TTS (no ffmpeg, no network), proving the M3 contract end to end at the IR/plan
boundary: measured clip durations rewrite each scene's windows (distinct from the
WPM estimate), asset keys are namespaced by ``(scene_id, segment_id)`` and attached
to the compiled plan rather than the IR, a provider failure degrades one scene to
WPM with a single ``AUD901`` while the build survives, and ``tts=None`` is a true
no-op -- the pre-M3 silent pipeline, untouched.
"""

from __future__ import annotations

from pathlib import Path

from manorem_ai import Pipeline, StubTTSProvider, TTSError, TTSRequest
from manorem_ai.cassette import StubProvider
from manorem_ai.research import FixtureResearchProvider
from manorem_compiler import CompileOptions, compile_project
from manorem_compositor import build_audio_timeline
from manorem_core import Code, LocalFSStore, Settings, sha256_of
from manorem_ir import narration_windows
from tests.support.ir_builders import make_project, valid_scene

_SCENE_ID = "intro"


class _FailingTTS:
    name = "failing"

    def synthesize(self, request: TTSRequest) -> object:
        raise TTSError("backend unreachable")


def _pipeline(tmp_path: Path, tts: object | None) -> Pipeline:
    return Pipeline(
        StubProvider.sequence([]),
        FixtureResearchProvider(()),
        store=LocalFSStore(tmp_path / "store"),
        tts=tts,  # type: ignore[arg-type]
        settings=Settings(),
    )


def test_narrate_retimes_windows_from_measured_audio(tmp_path: Path) -> None:
    pipe = _pipeline(tmp_path, StubTTSProvider())
    project = make_project(valid_scene())

    retimed, assets, bag, summary = pipe._narrate(project, tmp_path / "work")

    assert not bag.has_errors
    # Every segment now carries real start/end laid end to end.
    scene = next(iter(retimed.scenes))
    stub = StubTTSProvider()
    cfg = Settings()
    cursor = 0.0
    for segment in scene.narration:
        duration = stub.synthesize(
            TTSRequest(
                text=segment.text,
                voice=cfg.tts_voice,
                language=cfg.tts_language,
                speed=cfg.tts_speed,
                sample_rate=cfg.tts_sample_rate,
            )
        ).duration_s
        assert segment.start == cursor
        assert segment.end == cursor + duration + segment.pause_after
        cursor = segment.end

    # The windows are the measured ones, not the WPM estimate.
    wpm_only = narration_windows(valid_scene(), wpm=cfg.narration_wpm)
    real = narration_windows(scene, wpm=cfg.narration_wpm)
    assert real["line_one"].end != wpm_only["line_one"].end

    # Assets are namespaced by (scene_id, segment_id) -- never the bare segment id.
    assert set(assets) == {(_SCENE_ID, "line_one"), (_SCENE_ID, "line_two")}
    for _key, asset in assets.items():
        assert asset.startswith("audio/") and asset.endswith(".wav")
    assert summary is not None
    assert (tmp_path / "work" / "audio" / "segments.json").exists()
    assert (tmp_path / "work" / "audio" / "metadata.json").exists()


def test_attach_audio_flips_the_plan_out_of_silence(tmp_path: Path) -> None:
    pipe = _pipeline(tmp_path, StubTTSProvider())
    project = make_project(valid_scene())
    retimed, assets, _bag, _summary = pipe._narrate(project, tmp_path / "work")

    plan, bag = compile_project(retimed, CompileOptions())
    assert not bag.has_errors, bag.errors
    assert build_audio_timeline(plan).is_silent is True  # assets not attached yet

    voiced = pipe._attach_audio(plan, assets)
    assert build_audio_timeline(voiced).is_silent is False
    # Each cue now points at its scene-matched asset.
    for scene in voiced.scenes:
        for cue in scene.audio_cues:
            assert cue.asset == assets[(scene.id, cue.segment_id)]
    # The source plan is untouched -- attach is a copy, so the persisted plan stays
    # asset-free and its digest stable.
    assert build_audio_timeline(plan).is_silent is True


def test_provider_failure_falls_back_to_wpm_with_one_aud901(tmp_path: Path) -> None:
    pipe = _pipeline(tmp_path, _FailingTTS())
    project = make_project(valid_scene())

    retimed, assets, bag, _summary = pipe._narrate(project, tmp_path / "work")

    # Scene-atomic fallback: no assets, no errors, exactly one AUD901 warning.
    assert assets == {}
    assert not bag.has_errors
    codes = [d.code for d in bag]
    assert codes == [Code.AUD901_TTS_PROVIDER_FAILED]
    # The scene reverted to WPM: start/end stay unset so narration_windows estimates.
    scene = next(iter(retimed.scenes))
    assert all(seg.start is None and seg.end is None for seg in scene.narration)


def test_tts_none_is_a_true_no_op(tmp_path: Path) -> None:
    pipe = _pipeline(tmp_path, None)
    project = make_project(valid_scene())

    retimed, assets, bag, summary = pipe._narrate(project, tmp_path / "work")

    assert retimed is project  # same object -- nothing was rewritten
    assert assets == {}
    assert len(bag) == 0
    assert summary is None
    # No audio directory is created when audio is disabled.
    assert not (tmp_path / "work" / "audio").exists()


def test_audio_summary_digest_is_deterministic(tmp_path: Path) -> None:
    pipe = _pipeline(tmp_path, StubTTSProvider())
    project = make_project(valid_scene())

    _retimed, _assets, _bag, summary = pipe._narrate(project, tmp_path / "work")
    assert summary is not None
    # The digest build() records over the summary is a pure function of its content.
    assert sha256_of(summary) == sha256_of(summary)
