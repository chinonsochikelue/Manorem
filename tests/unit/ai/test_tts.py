"""The TTS provider seam -- determinism offline, secrets inside the provider.

Three backends live behind one :class:`~manorem_ai.TTSProvider` protocol and these
tests hold each to its contract: the stub is byte-identical and its duration is a
*measured* function of the WAV header (never the WPM estimate); the cassette records
then replays with no live call; :func:`tts_cache_key` is a stable function of only
the provider-neutral request (so no secret or vendor id can ever enter a cache key
or an artifact); and the one real provider translates OpenAI's request shape without
ever letting the api key reach the returned audio, its metadata, or the cache key.
"""

from __future__ import annotations

import io
import wave
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from manorem_ai import (
    CassetteTTSProvider,
    OpenAISpeechProvider,
    StubTTSProvider,
    SynthesizedAudio,
    TTSError,
    TTSRequest,
    tts_cache_key,
    wav_duration_seconds,
)

_SECRET = "sk-must-never-leak"


def _request(text: str = "Hello there, world.", **kwargs: Any) -> TTSRequest:
    fields: dict[str, Any] = {
        "text": text,
        "voice": "narrator",
        "language": "en",
        "speed": 1.0,
        "sample_rate": 24000,
    }
    fields.update(kwargs)
    return TTSRequest(**fields)


# --- the stub --------------------------------------------------------------


def test_stub_output_is_byte_identical_for_identical_input() -> None:
    stub = StubTTSProvider()
    first = stub.synthesize(_request())
    second = stub.synthesize(_request())
    assert first.data == second.data
    assert first.duration_s == second.duration_s


def test_stub_duration_is_measured_from_the_wav_not_estimated() -> None:
    stub = StubTTSProvider()
    audio = stub.synthesize(_request("A longer line has more characters here."))
    # The duration the pipeline will use is the one in the WAV header itself.
    assert audio.duration_s == pytest.approx(wav_duration_seconds(audio.data))
    assert audio.channels == 1
    assert audio.format == "wav"


def test_stub_speed_shortens_the_clip() -> None:
    stub = StubTTSProvider()
    slow = stub.synthesize(_request("Same words, different pace.", speed=1.0))
    fast = stub.synthesize(_request("Same words, different pace.", speed=2.0))
    assert fast.duration_s < slow.duration_s


# --- wav_duration_seconds --------------------------------------------------


def test_wav_duration_matches_a_known_header() -> None:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(1000)
        wav.writeframes(b"\x00\x00" * 2500)  # 2500 frames at 1000 Hz = 2.5 s
    assert wav_duration_seconds(buffer.getvalue()) == pytest.approx(2.5)


def test_unreadable_or_empty_audio_is_a_tts_error() -> None:
    with pytest.raises(TTSError):
        wav_duration_seconds(b"")
    with pytest.raises(TTSError):
        wav_duration_seconds(b"not a wav at all")


# --- tts_cache_key ---------------------------------------------------------


def test_cache_key_is_stable_and_content_addressed() -> None:
    assert tts_cache_key(_request()) == tts_cache_key(_request())
    assert tts_cache_key(_request("one")) != tts_cache_key(_request("two"))


def test_cache_key_depends_only_on_provider_neutral_fields() -> None:
    # Voice/speed/rate change the key; nothing vendor-shaped exists to change it.
    assert tts_cache_key(_request(voice="narrator")) != tts_cache_key(_request(voice="alloy"))
    assert tts_cache_key(_request(speed=1.0)) != tts_cache_key(_request(speed=1.5))
    # No OpenAI model id, response_format, or key is part of the request type.
    assert "model" not in TTSRequest.model_fields
    assert "api_key" not in TTSRequest.model_fields
    assert "response_format" not in TTSRequest.model_fields


# --- the cassette ----------------------------------------------------------


class _RecordingInner:
    name = "recording-inner"

    def __init__(self) -> None:
        self.calls = 0

    def synthesize(self, request: TTSRequest) -> SynthesizedAudio:
        self.calls += 1
        return StubTTSProvider().synthesize(request)


def test_cassette_records_then_replays_offline(tmp_path: Path) -> None:
    inner = _RecordingInner()
    recorder = CassetteTTSProvider(tmp_path, record=True, inner=inner)
    recorded = recorder.synthesize(_request())
    assert inner.calls == 1

    # Replay must read the clip from disk and never touch the inner provider again.
    replayer = CassetteTTSProvider(tmp_path, record=False)
    replayed = replayer.synthesize(_request())
    assert replayed.data == recorded.data
    assert replayed.duration_s == pytest.approx(recorded.duration_s)
    assert inner.calls == 1  # unchanged -- no live call on replay


def test_cassette_missing_entry_is_an_error_not_a_live_call(tmp_path: Path) -> None:
    replayer = CassetteTTSProvider(tmp_path, record=False)
    with pytest.raises(TTSError, match="no tts cassette"):
        replayer.synthesize(_request("never recorded"))


def test_cassette_record_without_inner_is_refused(tmp_path: Path) -> None:
    with pytest.raises(TTSError, match="inner provider"):
        CassetteTTSProvider(tmp_path, record=True)


def test_cassette_files_never_contain_the_key(tmp_path: Path) -> None:
    recorder = CassetteTTSProvider(tmp_path, record=True, inner=_RecordingInner())
    recorder.synthesize(_request())
    for path in tmp_path.iterdir():
        assert _SECRET.encode() not in path.read_bytes()


# --- the real provider (no network: a fake client) -------------------------


class _FakeSpeechResponse:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


class _FakeSpeech:
    def __init__(self, recorder: list[dict[str, Any]], data: bytes) -> None:
        self._recorder = recorder
        self._data = data

    def create(self, **kwargs: Any) -> _FakeSpeechResponse:
        self._recorder.append(kwargs)
        return _FakeSpeechResponse(self._data)


class _FakeAudio:
    def __init__(self, speech: _FakeSpeech) -> None:
        self.speech = speech


class _FakeOpenAI:
    """Just enough of the OpenAI client surface for ``synthesize`` to drive."""

    def __init__(self, recorder: list[dict[str, Any]], data: bytes) -> None:
        self.audio = _FakeAudio(_FakeSpeech(recorder, data))


def _real_wav() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b"\x00\x00" * 24000)  # 1.0 s
    return buffer.getvalue()


def test_openai_provider_builds_the_right_request() -> None:
    recorder: list[dict[str, Any]] = []
    client = _FakeOpenAI(recorder, _real_wav())
    provider = OpenAISpeechProvider(SecretStr(_SECRET), model="tts-1-hd", client=client)

    audio = provider.synthesize(_request("Speak this.", voice="alloy", speed=1.25))

    assert len(recorder) == 1
    call = recorder[0]
    assert call == {
        "model": "tts-1-hd",
        "voice": "alloy",
        "input": "Speak this.",
        "response_format": "wav",
        "speed": 1.25,
    }
    assert audio.duration_s == pytest.approx(1.0)


def test_openai_provider_never_lets_the_key_reach_the_request_or_artifact() -> None:
    recorder: list[dict[str, Any]] = []
    client = _FakeOpenAI(recorder, _real_wav())
    provider = OpenAISpeechProvider(SecretStr(_SECRET), client=client)

    audio = provider.synthesize(_request())

    # The secret is used only to build the client; it reaches neither the outgoing
    # request, the returned audio bytes, nor any field a cassette would persist.
    assert _SECRET not in str(recorder)
    assert _SECRET.encode() not in audio.data
    assert _SECRET not in tts_cache_key(_request())


def test_openai_transport_failure_becomes_a_tts_error() -> None:
    class _Boom:
        name = "boom"

        def __init__(self) -> None:
            self.audio = self

        @property
        def speech(self) -> _Boom:
            return self

        def create(self, **_: Any) -> None:
            raise RuntimeError("gateway said no")

    provider = OpenAISpeechProvider(SecretStr(_SECRET), client=_Boom())
    with pytest.raises(TTSError, match="synthesis failed"):
        provider.synthesize(_request())
