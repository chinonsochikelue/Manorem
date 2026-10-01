"""The M3 audio settings block -- env-driven, typed, and secret-safe.

``Settings`` is the one place a provider name, voice, or key enters the system, so
these tests pin that the audio fields parse from the ``MANOREM_`` environment the
way every other setting does, that the provider enum round-trips through its wire
value, and that an api key stays wrapped in a ``SecretStr`` (never a bare string a
log line could leak).
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from manorem_core import Settings, TTSProviderName


def test_audio_defaults_keep_the_pipeline_silent() -> None:
    # Audio is opt-in: a default Settings is the pre-M3 silent-but-timed promise.
    settings = Settings()
    assert settings.audio_enabled is False
    assert settings.tts_provider is TTSProviderName.STUB
    assert settings.tts_api_key is None


def test_audio_fields_parse_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MANOREM_AUDIO_ENABLED", "true")
    monkeypatch.setenv("MANOREM_TTS_PROVIDER", "openai")
    monkeypatch.setenv("MANOREM_TTS_VOICE", "alloy")
    monkeypatch.setenv("MANOREM_TTS_LANGUAGE", "fr")
    monkeypatch.setenv("MANOREM_TTS_SPEED", "1.25")
    monkeypatch.setenv("MANOREM_TTS_SAMPLE_RATE", "48000")
    monkeypatch.setenv("MANOREM_TTS_MODEL", "gpt-4o-mini-tts")
    monkeypatch.setenv("MANOREM_TTS_API_KEY", "sk-should-stay-wrapped")

    settings = Settings()

    assert settings.audio_enabled is True
    assert settings.tts_provider is TTSProviderName.OPENAI
    assert settings.tts_voice == "alloy"
    assert settings.tts_language == "fr"
    assert settings.tts_speed == 1.25
    assert settings.tts_sample_rate == 48000
    assert settings.tts_model == "gpt-4o-mini-tts"


def test_tts_api_key_is_a_secret_that_does_not_leak(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MANOREM_TTS_API_KEY", "sk-super-secret")
    settings = Settings()

    assert isinstance(settings.tts_api_key, SecretStr)
    # The raw secret must not surface in the model's own string forms.
    assert "sk-super-secret" not in repr(settings)
    assert "sk-super-secret" not in str(settings.tts_api_key)
    assert settings.tts_api_key.get_secret_value() == "sk-super-secret"


def test_tts_provider_name_round_trips_through_its_wire_value() -> None:
    for provider in TTSProviderName:
        assert TTSProviderName(provider.value) is provider
    assert {p.value for p in TTSProviderName} == {"stub", "cassette", "openai"}


def test_tts_speed_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    # A non-positive or absurd rate is a config error, not a silent clamp.
    monkeypatch.setenv("MANOREM_TTS_SPEED", "0")
    with pytest.raises(ValueError, match=r"tts_speed|greater than"):
        Settings()
