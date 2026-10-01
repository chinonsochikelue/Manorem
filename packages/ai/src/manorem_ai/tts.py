"""Speech synthesis behind one provider seam -- the audio twin of ``provider.py``.

One protocol, :class:`TTSProvider`, sits between the pipeline and whatever turns
narration text into sound: a deterministic in-process :class:`StubTTSProvider`, an
offline record/replay :class:`CassetteTTSProvider`, and one opt-in real
:class:`OpenAISpeechProvider`. The pipeline names a provider-neutral
:class:`TTSRequest` and gets back a :class:`SynthesizedAudio` whose duration was
*measured from the WAV header* -- which is the whole point of M3: once a clip
exists, its real length (not the words-per-minute estimate) drives the narration
window, cue anchoring, frame quantization and subtitles.

Two rules are load-bearing and enforced by structure, not discipline:

* **The request is provider-neutral.** Nothing OpenAI-shaped lives in
  :class:`TTSRequest`, so :func:`tts_cache_key` -- and therefore every cassette and
  every content-addressed asset -- is a function of *what was said*, never of which
  vendor said it. All OpenAI translation stays inside :class:`OpenAISpeechProvider`.
* **Secrets never leave the provider.** An api key is unwrapped only to build the
  client; it never enters the request, the cache key, a cassette, or a log line.
"""

from __future__ import annotations

import io
import json
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from manorem_core import ManoremError, canonical_json, sha256_of

__all__ = [
    "CassetteTTSProvider",
    "OpenAISpeechProvider",
    "StubTTSProvider",
    "SynthesizedAudio",
    "TTSError",
    "TTSProvider",
    "TTSRequest",
    "tts_cache_key",
    "wav_duration_seconds",
]


class TTSError(ManoremError):
    """A speech backend could not return audio for a request.

    Raised for a transport failure, a missing cassette, or audio that cannot be
    read. The pipeline treats it as a *fallback* signal, not a defect to repair:
    the affected scene reverts to WPM timing (``AUD901``/``AUD902``), never the
    LLM repair loop. There is no IR to fix when the audio simply did not render.
    """


class TTSRequest(BaseModel):
    """The provider-neutral request for one narration segment's speech.

    A model, not a tuple, so it serializes canonically into :func:`tts_cache_key`:
    two runs that ask for the same words in the same voice resolve to the same clip.
    Deliberately free of anything vendor-specific -- no OpenAI ``response_format``,
    no model id -- so the cache key and every stored asset stay about *what is said*.
    """

    model_config = ConfigDict(frozen=True)

    text: str = Field(min_length=1)
    voice: str = Field(min_length=1)
    language: str = Field(min_length=1)
    speed: float = Field(gt=0.0, le=4.0)
    sample_rate: int = Field(gt=0)
    #: Container the provider must emit. WAV only in M3 -- its header carries the
    #: frame count and rate this module reads the duration from, with no decoder.
    fmt: str = Field(default="wav", min_length=1)


def tts_cache_key(request: TTSRequest) -> str:
    """Content address of a request, mirroring :func:`~manorem_ai.provider.prompt_cache_key`.

    A pure function of the request fields -- which, by construction, hold no secret.
    """
    return sha256_of(canonical_json(request))


@dataclass(frozen=True, slots=True)
class SynthesizedAudio:
    """Rendered speech plus the facts the compositor and timing need.

    ``duration_s`` is always read back from ``data``'s own WAV header rather than
    trusted from the request, so the number that becomes the narration window is
    the audio that actually exists -- not what a provider claimed it would make.
    """

    data: bytes
    sample_rate: int
    channels: int
    format: str
    duration_s: float


def wav_duration_seconds(data: bytes) -> float:
    """Seconds of audio in a WAV blob, read from its header (stdlib ``wave`` only).

    Raises :class:`TTSError` for anything that is not a readable, non-empty WAV --
    an empty blob, a truncated header, or a zero frame-rate -- which the pipeline
    turns into an ``AUD902`` scene fallback rather than a zero-length window.
    """
    try:
        with wave.open(io.BytesIO(data), "rb") as wav:
            frames = wav.getnframes()
            rate = wav.getframerate()
    except (wave.Error, EOFError) as exc:
        raise TTSError(f"audio is not a readable WAV: {exc}") from exc
    if rate <= 0 or frames <= 0:
        raise TTSError(f"audio has no duration: {frames} frames at {rate} Hz")
    return frames / float(rate)


class TTSProvider(Protocol):
    """A backend that turns a narration request into rendered speech."""

    name: str

    def synthesize(self, request: TTSRequest) -> SynthesizedAudio: ...


#: The stub's pacing model. Deliberately a function of *characters*, not words,
#: so its durations never coincide with the WPM estimate -- a test can prove that
#: a retimed window came from measured audio and not from the fallback.
_STUB_SECONDS_PER_CHAR = 0.06
_STUB_MIN_SECONDS = 0.4


def _silent_wav(num_frames: int, sample_rate: int) -> bytes:
    """A PCM-16 mono WAV of ``num_frames`` of silence; byte-identical per input."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)  # PCM-16
        wav.setframerate(sample_rate)
        wav.writeframes(b"\x00\x00" * num_frames)
    return buffer.getvalue()


class StubTTSProvider:
    """Deterministic offline speech: silent PCM-16 WAV, duration from char count.

    The audio is silence -- the pipeline needs a *length*, not a sound, to prove
    the timing path -- and the length is ``chars * k / speed``, a model chosen to
    be distinct from WPM so an estimate can never masquerade as a measurement.
    Identical input yields byte-identical output, which is what lets a golden test
    pin the whole audio artifact.
    """

    name = "stub"

    def synthesize(self, request: TTSRequest) -> SynthesizedAudio:
        seconds = max(len(request.text) * _STUB_SECONDS_PER_CHAR, _STUB_MIN_SECONDS)
        seconds /= request.speed
        num_frames = max(1, round(seconds * request.sample_rate))
        data = _silent_wav(num_frames, request.sample_rate)
        return SynthesizedAudio(
            data=data,
            sample_rate=request.sample_rate,
            channels=1,
            format="wav",
            duration_s=wav_duration_seconds(data),
        )


class CassetteTTSProvider:
    """Record/replay against a directory of WAV cassettes, keyed by request hash.

    Mirrors :class:`~manorem_ai.cassette.CassetteProvider`: in replay a missing
    cassette is an error, never a live call, so an offline test can never reach the
    network; in record mode every call goes to ``inner`` and the clip is written
    back. Each entry is a ``<key>.wav`` beside a tiny ``<key>.json`` of audio
    metadata -- never a secret, since the key itself is secret-free.
    """

    name = "cassette"

    def __init__(
        self,
        directory: Path,
        *,
        record: bool = False,
        inner: TTSProvider | None = None,
    ) -> None:
        if record and inner is None:
            raise TTSError("recording a cassette needs an inner provider to record from")
        self._dir = directory
        self._record = record
        self._inner = inner

    def _paths(self, key: str) -> tuple[Path, Path]:
        return self._dir / f"{key}.wav", self._dir / f"{key}.json"

    def synthesize(self, request: TTSRequest) -> SynthesizedAudio:
        key = tts_cache_key(request)
        wav_path, meta_path = self._paths(key)

        if not self._record:
            if not wav_path.exists():
                raise TTSError(
                    f"no tts cassette at {wav_path.name}; record with MANOREM_TTS_RECORD=1 "
                    "or check the narration has not drifted"
                )
            data = wav_path.read_bytes()
            meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
            return SynthesizedAudio(
                data=data,
                sample_rate=int(meta.get("sample_rate", request.sample_rate)),
                channels=int(meta.get("channels", 1)),
                format=str(meta.get("format", "wav")),
                duration_s=wav_duration_seconds(data),
            )

        assert self._inner is not None  # guaranteed by __init__
        audio = self._inner.synthesize(request)
        self._dir.mkdir(parents=True, exist_ok=True)
        wav_path.write_bytes(audio.data)
        meta_path.write_text(
            json.dumps(
                {
                    "sample_rate": audio.sample_rate,
                    "channels": audio.channels,
                    "format": audio.format,
                    "duration_s": audio.duration_s,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return audio


class OpenAISpeechProvider:
    """OpenAI-compatible ``/audio/speech`` as a :class:`TTSProvider`. Opt-in only.

    Never exercised in the default test run -- CI has no key and the ``network``
    marker gates any live call -- and never reachable under ``--offline``, which
    pins the stub. The ``openai`` SDK is imported lazily (so ``import manorem_ai``
    is free without the extra) and the client is injectable, which is what tests
    use to drive it with a fake. All OpenAI-specific translation lives here and
    nowhere else; the api key is unwrapped only to build the client and is never
    logged, hashed, or persisted.

    Routing through the JustWorker gateway (``base_url``) keeps the same client
    interface -- only the network path differs -- exactly as the LLM OpenAI adapter.
    """

    name = "openai"

    def __init__(
        self,
        api_key: SecretStr | str | None = None,
        *,
        base_url: str | None = None,
        model: str = "tts-1",
        client: Any | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._model = model
        self._client = client

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from openai import OpenAI  # noqa: PLC0415 - lazy so `import manorem_ai` is free
        except ImportError as exc:  # pragma: no cover - exercised only without the extra
            raise TTSError(
                "the openai extra is not installed; `uv sync --extra openai` or use the "
                "stub/cassette tts provider offline"
            ) from exc
        if self._api_key is None:
            raise TTSError("OpenAISpeechProvider needs an api_key to build a client")
        secret = (
            self._api_key.get_secret_value()
            if isinstance(self._api_key, SecretStr)
            else self._api_key
        )
        kwargs: dict[str, Any] = {"api_key": secret}
        if self._base_url is not None:
            kwargs["base_url"] = self._base_url
        self._client = OpenAI(**kwargs)
        return self._client

    def synthesize(self, request: TTSRequest) -> SynthesizedAudio:
        client = self._ensure_client()
        try:
            response = client.audio.speech.create(
                model=self._model,
                voice=request.voice,
                input=request.text,
                response_format="wav",
                speed=request.speed,
            )
            data = response.read()
        except Exception as exc:
            raise TTSError(f"openai speech synthesis failed: {exc}") from exc
        return SynthesizedAudio(
            data=data,
            sample_rate=request.sample_rate,
            channels=1,
            format="wav",
            duration_s=wav_duration_seconds(data),
        )
