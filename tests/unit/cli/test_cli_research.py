"""``build``'s research flags, and the offline invariant behind them.

``--offline`` is the load-bearing one. It must make it structurally impossible
for a real backend to be *constructed* -- not merely unused -- so no key can be
read and no socket opened, and live recording must be refused rather than quietly
degraded. The rest of the file covers the flags folding into settings and the
corpus loader refusing a source that claims bytes it does not contain.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from manorem_ai.research import ResearchRequest
from manorem_cli._support import build_research_provider, load_corpus
from manorem_cli.app import _resolve_build_settings, app
from manorem_core import (
    ConfigError,
    LLMProviderName,
    ResearchProviderName,
    Settings,
    sha256_of,
)

runner = CliRunner()

SNIPPET = "A receiver trilaterates its position."


def _corpus(path: Path, *, content_hash: str | None = None) -> Path:
    path.write_text(
        json.dumps(
            [
                {
                    "url": "https://example.test/gps",
                    "title": "How GPS works",
                    "snippet": SNIPPET,
                    "retrieved_at": "2026-01-01T00:00:00+00:00",
                    "content_hash": content_hash
                    if content_hash is not None
                    else sha256_of(SNIPPET),
                }
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_build_adopts_the_research_flags() -> None:
    result = runner.invoke(app, ["build", "--help"])
    assert result.exit_code == 0
    for flag in ("--research", "--no-research", "--research-provider", "--offline"):
        assert flag in result.output


def test_an_unknown_research_backend_exits_2_naming_the_choices() -> None:
    result = runner.invoke(app, ["build", "An idea.", "--research-provider", "nonsense"])
    assert result.exit_code == 2
    assert "unknown research provider" in result.output
    assert "brave" in result.output


def test_the_research_flags_fold_into_settings() -> None:
    base = Settings()

    enabled = _resolve_build_settings(
        base, tts=None, offline=False, research=True, research_provider="brave"
    )
    assert enabled.research_enabled is True
    assert enabled.research_provider is ResearchProviderName.BRAVE

    disabled = _resolve_build_settings(
        base, tts=None, offline=False, research=False, research_provider=None
    )
    assert disabled.research_enabled is False

    untouched = _resolve_build_settings(
        base, tts=None, offline=False, research=None, research_provider=None
    )
    assert untouched.research_enabled == base.research_enabled


def test_offline_pins_every_backend_and_turns_off_live_recording() -> None:
    settings = _resolve_build_settings(
        Settings(research_record=True),
        tts="openai",
        offline=True,
        research=None,
        research_provider=None,
    )
    assert settings.llm_provider is LLMProviderName.CASSETTE
    assert settings.research_record is False


def test_offline_never_constructs_the_live_backend(capsys: pytest.CaptureFixture[str]) -> None:
    settings = Settings(
        research_provider=ResearchProviderName.BRAVE, research_api_key=SecretStr("sekrit")
    )
    primary, fallback = build_research_provider(settings, corpus=None, offline=True)

    assert primary.name == "cassette"
    assert fallback is None
    assert "offline pins research" in capsys.readouterr().err


def test_the_live_backend_always_has_a_recorded_fallback() -> None:
    settings = Settings(
        research_provider=ResearchProviderName.BRAVE, research_api_key=SecretStr("sekrit")
    )
    primary, fallback = build_research_provider(settings, corpus=None, offline=False)

    assert primary.name == "brave"
    assert fallback is not None
    assert fallback.name == "cassette"


def test_refreshing_a_cassette_offline_is_refused_rather_than_degraded() -> None:
    settings = Settings(research_provider=ResearchProviderName.CASSETTE, research_record=True)
    with pytest.raises(ConfigError, match="cannot refresh research cassettes"):
        build_research_provider(settings, corpus=None, offline=True)


def test_the_default_backend_is_the_offline_fixture(tmp_path: Path) -> None:
    primary, fallback = build_research_provider(
        Settings(), corpus=_corpus(tmp_path / "corpus.json"), offline=True
    )

    assert primary.name == "fixture"
    assert fallback is None
    retrieved = primary.research(ResearchRequest(topic="How GPS works."))
    assert retrieved.retrieved[0].content == SNIPPET


def test_a_corpus_claiming_bytes_it_does_not_contain_is_refused(tmp_path: Path) -> None:
    path = _corpus(tmp_path / "corpus.json", content_hash="not-what-the-snippet-hashes-to")
    with pytest.raises(ConfigError, match="declares content_hash"):
        load_corpus(path)


def test_a_corpus_without_a_declared_digest_is_still_usable(tmp_path: Path) -> None:
    # The digest is derived from the snippet, so an absent declaration is simply
    # nothing left to contradict it -- an entry that is only a URL and a date is
    # an empty source, not a rejection.
    path = tmp_path / "corpus.json"
    path.write_text(
        json.dumps(
            [
                {
                    "url": "https://example.test/a",
                    "retrieved_at": "2026-01-01T00:00:00+00:00",
                }
            ]
        ),
        encoding="utf-8",
    )

    retrieved = load_corpus(path)
    assert len(retrieved) == 1
    assert retrieved[0].source.url == "https://example.test/a"
    assert retrieved[0].content == ""
    assert retrieved[0].source.content_digest == sha256_of("")


def test_an_empty_corpus_is_an_honest_empty_corpus(tmp_path: Path) -> None:
    path = tmp_path / "corpus.json"
    path.write_text("[]", encoding="utf-8")
    assert load_corpus(path) == ()
