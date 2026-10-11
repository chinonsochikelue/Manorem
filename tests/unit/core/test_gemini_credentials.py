"""Gemini credential resolution -- one resolver, named variables, no leaked values.

Manorem can point each of its Gemini consumers at its own credential or at one
shared credential, and which it picks must never depend on call-site convention.
These tests pin that contract from the operator's side: the variable each tool
reads, what happens when one is absent, that fallback is a decision rather than a
default, that validation happens for the tools a run actually needs -- and that a
secret never reaches an error message.
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from manorem_core import (
    PIPELINE_GEMINI_TOOLS,
    ConfigError,
    GeminiCredentialResolver,
    GeminiKeyMode,
    GeminiTool,
    Settings,
    gemini_credentials,
)


def _dedicated(*with_keys: GeminiTool, fallback: bool = False) -> Settings:
    """Dedicated-mode settings carrying a credential only for ``with_keys``."""
    fields = {f"{tool.value}_gemini_apikey": f"key-{tool.value}" for tool in with_keys}
    return Settings(
        gemini_key_mode=GeminiKeyMode.DEDICATED,
        gemini_allow_shared_fallback=fallback,
        **fields,
    )


def test_shared_mode_is_the_default_and_serves_every_tool() -> None:
    resolver = gemini_credentials(Settings(gemini_apikey="shared-key", gemini_api_key=None))

    assert resolver.mode is GeminiKeyMode.SHARED
    for tool in GeminiTool:
        assert resolver.key(tool) == "shared-key"


def test_the_legacy_variable_is_still_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    # Backward compatibility: a checkout that only has the pre-existing spelling
    # keeps working untouched, with no new variable to discover.
    monkeypatch.setenv("MANOREM_GEMINI_API_KEY", "legacy-key")
    monkeypatch.delenv("MANOREM_GEMINI_APIKEY", raising=False)

    assert gemini_credentials(Settings()).key(GeminiTool.SCENE) == "legacy-key"


def test_every_tool_reads_the_variable_it_advertises(monkeypatch: pytest.MonkeyPatch) -> None:
    """The naming contract, checked end to end for all eight tools.

    ``GeminiTool.env_var`` promises ``MANOREM_<TOOL>_GEMINI_APIKEY``; pydantic-settings
    has to agree with that promise when turning the name back into a field. If the two
    ever drift, a key an operator set would simply never be found -- so each tool is
    set through its advertised name and read back through the resolver.
    """
    monkeypatch.setenv("MANOREM_GEMINI_KEY_MODE", "dedicated")
    for tool in GeminiTool:
        monkeypatch.setenv(tool.env_var, f"key-for-{tool.value}")

    resolver = gemini_credentials(Settings())

    for tool in GeminiTool:
        assert resolver.key(tool) == f"key-for-{tool.value}"
    assert len({tool.env_var for tool in GeminiTool}) == len(GeminiTool)


def test_dedicated_mode_prefers_a_tools_own_credential() -> None:
    settings = _dedicated(GeminiTool.SCENE, GeminiTool.RESEARCH)
    resolver = GeminiCredentialResolver(settings)

    assert resolver.key(GeminiTool.SCENE) == "key-scene"
    assert resolver.key(GeminiTool.RESEARCH) == "key-research"
    # One tool's key is never another tool's by default.
    with pytest.raises(ConfigError, match=r"MANOREM_VISUAL_PLAN_GEMINI_APIKEY"):
        resolver.key(GeminiTool.VISUAL_PLAN)


def test_a_missing_credential_names_the_variable_and_nothing_else() -> None:
    settings = _dedicated(GeminiTool.SCENE)
    with pytest.raises(ConfigError) as excinfo:
        GeminiCredentialResolver(settings).key(GeminiTool.STORY)

    message = str(excinfo.value)
    assert "MANOREM_STORY_GEMINI_APIKEY" in message
    # A neighbouring credential that *is* configured must not be quoted back.
    assert "key-scene" not in message


def test_shared_fallback_is_off_by_default() -> None:
    settings = Settings(
        gemini_key_mode=GeminiKeyMode.DEDICATED,
        gemini_apikey="shared-key",
        gemini_api_key=None,
    )
    with pytest.raises(ConfigError, match=r"MANOREM_SCRIPT_GEMINI_APIKEY"):
        GeminiCredentialResolver(settings).key(GeminiTool.SCRIPT)


def test_shared_fallback_is_a_decision_not_a_default() -> None:
    settings = Settings(
        gemini_key_mode=GeminiKeyMode.DEDICATED,
        gemini_allow_shared_fallback=True,
        gemini_apikey="shared-key",
        gemini_api_key=None,
    )
    resolver = GeminiCredentialResolver(settings)

    assert resolver.key(GeminiTool.SCRIPT) == "shared-key"
    assert resolver.key(GeminiTool.CASSETTE) == "shared-key"


def test_fallback_still_fails_loudly_when_no_shared_credential_exists() -> None:
    settings = Settings(
        gemini_key_mode=GeminiKeyMode.DEDICATED,
        gemini_allow_shared_fallback=True,
        gemini_apikey=None,
        gemini_api_key=None,
    )
    with pytest.raises(ConfigError, match=r"MANOREM_GEMINI_APIKEY"):
        GeminiCredentialResolver(settings).key(GeminiTool.SCENE)


def test_validate_covers_the_tools_this_run_will_use() -> None:
    stages = tuple(tool for tool in GeminiTool if tool is not GeminiTool.CASSETTE)

    # A live run draws every stage's credential and nothing else.
    GeminiCredentialResolver(_dedicated(*stages)).validate(*PIPELINE_GEMINI_TOOLS)
    # A recording run draws only the recorder's, so only that one is required.
    GeminiCredentialResolver(_dedicated(GeminiTool.CASSETTE)).validate(GeminiTool.CASSETTE)


def test_pipeline_tools_leave_the_recorder_out() -> None:
    assert set(PIPELINE_GEMINI_TOOLS) == set(GeminiTool) - {GeminiTool.CASSETTE}


def test_validate_fails_at_startup_on_the_first_missing_tool() -> None:
    # Caught before any client is built, so a half-configured run never begins
    # and dies halfway through a build.
    resolver = GeminiCredentialResolver(_dedicated(GeminiTool.SCENE))
    with pytest.raises(ConfigError, match=r"MANOREM_EVIDENCE_GEMINI_APIKEY"):
        resolver.validate(*PIPELINE_GEMINI_TOOLS)


def test_shared_mode_validates_against_the_one_credential() -> None:
    GeminiCredentialResolver(Settings(gemini_apikey="shared-key", gemini_api_key=None)).validate(
        *PIPELINE_GEMINI_TOOLS
    )


def test_shared_mode_fails_validation_when_nothing_is_configured() -> None:
    resolver = GeminiCredentialResolver(Settings(gemini_apikey=None, gemini_api_key=None))
    with pytest.raises(ConfigError, match=r"MANOREM_GEMINI_APIKEY"):
        resolver.validate()


def test_key_mode_parses_from_its_wire_value(monkeypatch: pytest.MonkeyPatch) -> None:
    assert GeminiKeyMode("shared") is GeminiKeyMode.SHARED
    assert GeminiKeyMode("dedicated") is GeminiKeyMode.DEDICATED

    monkeypatch.setenv("MANOREM_GEMINI_KEY_MODE", "dedicated")
    assert Settings().gemini_key_mode is GeminiKeyMode.DEDICATED


def test_a_credential_stays_a_secret_in_settings() -> None:
    settings = Settings(gemini_apikey="plain-text-on-purpose")

    assert isinstance(settings.gemini_apikey, SecretStr)
    assert "plain-text-on-purpose" not in repr(settings)
    assert settings.gemini_apikey.get_secret_value() == "plain-text-on-purpose"
