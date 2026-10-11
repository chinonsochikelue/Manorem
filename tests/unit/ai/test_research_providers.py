"""The retrieval seam: offline means offline, and an empty result is a real answer.

Three properties are asserted here, in the order they matter. The offline
backends cannot reach the network -- a cassette that misses *raises* rather than
falling through to a live call, which is what stops an offline run from quietly
becoming an online one. A provider with nothing to return returns nothing,
because a plausible-looking invented source is exactly the fabrication the
provenance layer exists to stop. And the one real backend keeps every
vendor-specific detail inside its own module: the key authenticates a request,
never a filename, never an artifact, and never a cache identity.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest
from pydantic import SecretStr

from manorem_ai.research import (
    BraveResearchProvider,
    CassetteResearchProvider,
    FixtureResearchProvider,
    ResearchError,
    ResearchRequest,
    StubResearchProvider,
    html_to_text,
    research_cache_key,
)
from tests.support.ai_builders import GPS_SNIPPET, gps_retrieved

IDEA = "How GPS determines your location."


def request() -> ResearchRequest:
    return ResearchRequest(topic=IDEA)


def test_a_provider_with_nothing_returns_nothing_rather_than_a_plausible_source() -> None:
    assert StubResearchProvider().research(request()).retrieved == ()


def test_retrieval_never_exceeds_the_requested_bound() -> None:
    provider = StubResearchProvider((gps_retrieved(), gps_retrieved()))
    assert len(provider.research(ResearchRequest(topic=IDEA, max_sources=1)).retrieved) == 1


def test_a_missing_cassette_is_an_error_not_a_live_call(tmp_path: Path) -> None:
    provider = CassetteResearchProvider(tmp_path / "cassettes")
    with pytest.raises(ResearchError, match="no research cassette"):
        provider.research(request())


def test_a_cassette_round_trip_reproduces_the_retrieved_bytes(tmp_path: Path) -> None:
    directory = tmp_path / "cassettes"
    recording = CassetteResearchProvider(
        directory, record=True, inner=StubResearchProvider((gps_retrieved(),))
    )
    written = recording.research(request())

    replayed = CassetteResearchProvider(directory).research(request())
    assert replayed == written
    # Evidence is located in these bytes, so a replay must reproduce them exactly.
    assert replayed.retrieved[0].content == GPS_SNIPPET


def test_recording_without_anywhere_to_record_from_refuses(tmp_path: Path) -> None:
    with pytest.raises(ResearchError, match="inner provider"):
        CassetteResearchProvider(tmp_path / "cassettes", record=True)


def test_html_is_read_as_data_never_as_markup() -> None:
    html = (
        "<html><head><style>p{color:red}</style>"
        "<script>fetch('https://evil.test')</script></head>"
        "<body><h1>Getting started</h1><p>A receiver trilaterates.</p></body></html>"
    )
    text = html_to_text(html)
    assert "Getting started" in text
    assert "trilaterates" in text
    assert "fetch(" not in text
    assert "color:red" not in text


def test_the_live_backend_fails_loudly_when_it_has_no_key() -> None:
    with pytest.raises(ResearchError, match="MANOREM_RESEARCH_API_KEY"):
        BraveResearchProvider().research(request())


def test_the_live_backend_reads_pages_and_drops_what_it_cannot_fetch() -> None:
    calls: list[tuple[str, Mapping[str, str]]] = []

    def transport(url: str, headers: Mapping[str, str]) -> bytes:
        calls.append((url, headers))
        if "/web/search" in url:
            return json.dumps(
                {
                    "web": {
                        "results": [
                            {"url": "https://example.test/a", "title": "A"},
                            {"url": "file:///etc/passwd", "title": "local"},
                            {"url": "javascript:alert(1)", "title": "script"},
                        ]
                    }
                }
            ).encode()
        return (
            b"<html><head><script>fetch('https://evil.test')</script></head>"
            b"<body><p>A receiver trilaterates its position.</p></body></html>"
        )

    provider = BraveResearchProvider(
        api_key=SecretStr("sekrit"), transport=transport, base_url="https://gw.example/v1"
    )
    result = provider.research(ResearchRequest(topic=IDEA, max_sources=6))

    assert [item.source.url for item in result.retrieved] == ["https://example.test/a"]
    # Only http(s) was ever opened, and the page's script never became content.
    assert all(url.startswith(("http://", "https://")) for url, _ in calls)
    content = result.retrieved[0].content
    assert "trilaterates its position" in content
    assert "fetch(" not in content
    # The key authenticates the request; it appears in no URL, no cache identity
    # and no artifact.
    assert all("sekrit" not in url for url, _ in calls)
    assert all(
        headers.get("X-Subscription-Token") == "sekrit"
        for url, headers in calls
        if "/web/search" in url
    )


def test_only_the_live_backend_asks_to_be_reused(tmp_path: Path) -> None:
    # Offline backends are already free and deterministic (and a cassette is
    # already its own cache), so a second layer would only go stale twice.
    assert StubResearchProvider().cache_identity == ""
    assert FixtureResearchProvider(()).cache_identity == ""
    assert CassetteResearchProvider(tmp_path / "cassettes").cache_identity == ""

    live = BraveResearchProvider(api_key="sekrit", base_url="https://gw.example/v1")
    assert live.cache_identity == "brave:https://gw.example/v1"
    assert "sekrit" not in live.cache_identity


def test_a_cache_key_folds_in_the_request_and_provider_but_nothing_secret() -> None:
    here = research_cache_key(request(), provider="brave:https://gw.example/v1")
    assert here == research_cache_key(request(), provider="brave:https://gw.example/v1")
    assert here != research_cache_key(request(), provider="brave:https://other.example")
    assert here != research_cache_key(ResearchRequest(topic="Something else."), provider="brave:x")
    assert len(here) == 64  # a content address, not a readable path
