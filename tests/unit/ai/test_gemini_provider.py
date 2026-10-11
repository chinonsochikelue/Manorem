"""Gemini credential routing and rate-limit handling -- without touching the network.

The live backend owns exactly two decisions worth pinning: which tool a request
bills to (implied by its schema, or pinned when the provider is the recorder) and
what happens when Gemini answers 429. The second one deliberately refuses to
solve a daily quota by sleeping or by looping -- it honours a wait the backend
can reasonably be held to, and otherwise reports the tool and its variable so an
operator can act, with no credential ever quoted back.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from manorem_ai import gemini as gemini_module
from manorem_ai.agents.models import Script, StoryOutline, VisualPlan
from manorem_ai.gemini import TOOL_BY_SCHEMA, GeminiProvider, tool_for_schema
from manorem_ai.patch import JsonPatch
from manorem_ai.provider import Prompt, ProviderError, RateLimitError
from manorem_ai.research.models import EvidenceAssessment, ResearchBrief
from manorem_core import GeminiKeyMode, GeminiTool, Settings, gemini_credentials
from manorem_ir import Scene


class Unregistered(BaseModel):
    """A schema no pipeline stage ever produces."""

    value: str = ""


class _Response:
    def __init__(self, text: str) -> None:
        self.text = text
        self.response_id = "resp-1"


class _Models:
    """Replays a scripted sequence of answers, repeating the last one forever."""

    def __init__(self, outcomes: list[Any]) -> None:
        self._outcomes = outcomes
        self.calls = 0

    def generate_content(self, *, model: str, contents: str, config: Any) -> _Response:
        del model, contents, config
        outcome = self._outcomes[min(self.calls, len(self._outcomes) - 1)]
        self.calls += 1
        if isinstance(outcome, BaseException):
            raise outcome
        return _Response(outcome)


class _Client:
    def __init__(self, *outcomes: Any) -> None:
        self.models = _Models(list(outcomes))


class _HTTPError(Exception):
    """Shaped like the SDK's error: a status code plus a body."""

    def __init__(self, code: int, body: str) -> None:
        super().__init__(f"{code} {body}")
        self.code = code


def _rate_limited(retry_after: str | None = None) -> _HTTPError:
    body = "RESOURCE_EXHAUSTED. {'error': {'code': 429, 'status': 'RESOURCE_EXHAUSTED'"
    if retry_after is not None:
        body += f", 'details': [{{'@type': 'RetryInfo', 'retryDelay': '{retry_after}s'}}]"
    return _HTTPError(429, body + "}")


def _unavailable() -> _HTTPError:
    return _HTTPError(503, "the model is temporarily unavailable")


def _generate(client: _Client, tool: GeminiTool | None) -> Any:
    return GeminiProvider._generate_with_retry(
        client, model="gemini-test", contents="prompt", config=None, tool=tool
    )


def test_every_registered_schema_maps_to_its_own_tool() -> None:
    expected: dict[type[BaseModel], GeminiTool] = {
        EvidenceAssessment: GeminiTool.EVIDENCE,
        JsonPatch: GeminiTool.REPAIR,
        ResearchBrief: GeminiTool.RESEARCH,
        Scene: GeminiTool.SCENE,
        Script: GeminiTool.SCRIPT,
        StoryOutline: GeminiTool.STORY,
        VisualPlan: GeminiTool.VISUAL_PLAN,
    }
    assert expected == TOOL_BY_SCHEMA
    assert tool_for_schema(Scene) is GeminiTool.SCENE
    assert tool_for_schema(Unregistered) is None


def test_an_unregistered_schema_is_refused_rather_than_billed_to_another_tool() -> None:
    provider = GeminiProvider(
        resolver=gemini_credentials(Settings(gemini_apikey="shared-key", gemini_api_key=None))
    )

    with pytest.raises(ProviderError, match="no Gemini tool is registered for schema Unregistered"):
        provider.structured(
            prompt=Prompt(system="s", user="u"),
            schema=Unregistered,
            model="gemini-test",
            temperature=0.0,
            max_tokens=64,
        )


def test_a_pinned_key_and_a_resolver_never_both() -> None:
    with pytest.raises(ValueError, match="not both"):
        GeminiProvider(
            api_key="literal-key",
            resolver=gemini_credentials(Settings(gemini_apikey="shared-key")),
        )


def test_a_short_retry_after_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    waits: list[float] = []
    monkeypatch.setattr(gemini_module, "_sleep", waits.append)
    client = _Client(_rate_limited("30"), '{"operations": []}')

    result = _generate(client, GeminiTool.SCENE)

    assert isinstance(result, _Response)
    assert waits == [30.0]
    assert client.models.calls == 2


def test_a_daily_quota_is_reported_instead_of_slept_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waits: list[float] = []
    monkeypatch.setattr(gemini_module, "_sleep", waits.append)
    client = _Client(_rate_limited("62328"))

    with pytest.raises(RateLimitError) as excinfo:
        _generate(client, GeminiTool.SCENE)

    # A 17-hour deference is not a backoff: no wait, no second attempt, and no
    # further spend of a quota that is already gone.
    assert waits == []
    assert client.models.calls == 1
    message = str(excinfo.value)
    assert "scene" in message
    assert "MANOREM_SCENE_GEMINI_APIKEY" in message
    assert "17h18m" in message


def test_rate_limit_retries_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    waits: list[float] = []
    monkeypatch.setattr(gemini_module, "_sleep", waits.append)
    client = _Client(_rate_limited())

    with pytest.raises(RateLimitError):
        _generate(client, GeminiTool.RESEARCH)

    assert client.models.calls == 3  # the first call plus exactly two retries
    assert len(waits) == 2
    assert all(wait > 0 for wait in waits)


def test_transient_5xx_retries_with_a_jittered_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    waits: list[float] = []
    monkeypatch.setattr(gemini_module, "_sleep", waits.append)
    client = _Client(_unavailable(), '{"operations": []}')

    assert isinstance(_generate(client, GeminiTool.SCENE), _Response)
    assert client.models.calls == 2
    # First attempt: base 3.0s, jittered within [0.5x, 1.5x], never past the cap.
    assert 1.5 <= waits[0] <= 4.5


def test_a_client_error_is_never_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    waits: list[float] = []
    monkeypatch.setattr(gemini_module, "_sleep", waits.append)
    client = _Client(_HTTPError(400, "Request contains an invalid argument."))

    with pytest.raises(_HTTPError):
        _generate(client, GeminiTool.SCENE)

    assert waits == []
    assert client.models.calls == 1


def test_the_resolver_supplies_the_credential_for_the_requested_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    genai = pytest.importorskip("google.genai")
    captured: dict[str, Any] = {}

    class _FakeClient:
        def __init__(self, *, api_key: str, http_options: Any = None) -> None:
            captured["api_key"] = api_key
            captured["http_options"] = http_options
            self.models = _Models(['{"operations": []}'])

    monkeypatch.setattr(genai, "Client", _FakeClient)

    provider = GeminiProvider(
        resolver=gemini_credentials(
            Settings(
                gemini_key_mode=GeminiKeyMode.DEDICATED,
                repair_gemini_apikey="repair-credential",
                scene_gemini_apikey="scene-credential",
            )
        )
    )
    completion = provider.structured(
        prompt=Prompt(system="s", user="u"),
        schema=JsonPatch,
        model="gemini-test",
        temperature=0.0,
        max_tokens=64,
    )

    # JsonPatch is the repair stage's schema, so the repair credential is the one
    # drawn -- not the scene's, and not a shared one.
    assert captured["api_key"] == "repair-credential"
    assert completion.value.operations == ()
    # The SDK's own retries are switched off, so one attempt of the policy below
    # is exactly one HTTP request instead of five multiplied by it.
    assert captured["http_options"].retry_options.attempts == 1


def test_a_pinned_tool_bills_the_recorder_for_every_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    genai = pytest.importorskip("google.genai")
    captured: dict[str, Any] = {}

    class _FakeClient:
        def __init__(self, *, api_key: str, http_options: Any = None) -> None:
            captured["api_key"] = api_key
            captured["http_options"] = http_options
            self.models = _Models(['{"operations": []}'])

    monkeypatch.setattr(genai, "Client", _FakeClient)

    provider = GeminiProvider(
        resolver=gemini_credentials(
            Settings(
                gemini_key_mode=GeminiKeyMode.DEDICATED,
                cassette_gemini_apikey="cassette-credential",
                repair_gemini_apikey="repair-credential",
            )
        ),
        tool=GeminiTool.CASSETTE,
    )
    provider.structured(
        prompt=Prompt(system="s", user="u"),
        schema=JsonPatch,
        model="gemini-test",
        temperature=0.0,
        max_tokens=64,
    )

    assert captured["api_key"] == "cassette-credential"


def test_a_rate_limit_error_never_quotes_the_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    genai = pytest.importorskip("google.genai")
    captured: dict[str, Any] = {}

    class _FakeClient:
        def __init__(self, *, api_key: str, http_options: Any = None) -> None:
            captured["api_key"] = api_key
            captured["http_options"] = http_options
            self.models = _Models([_rate_limited("62328")])

    monkeypatch.setattr(genai, "Client", _FakeClient)
    waits: list[float] = []
    monkeypatch.setattr(gemini_module, "_sleep", waits.append)

    provider = GeminiProvider(
        resolver=gemini_credentials(
            Settings(gemini_apikey="do-not-print-this", gemini_api_key=None)
        )
    )
    with pytest.raises(RateLimitError) as excinfo:
        provider.structured(
            prompt=Prompt(system="s", user="u"),
            schema=JsonPatch,
            model="gemini-test",
            temperature=0.0,
            max_tokens=64,
        )

    message = str(excinfo.value)
    assert captured["api_key"] == "do-not-print-this"
    assert "do-not-print-this" not in message
    assert "MANOREM_REPAIR_GEMINI_APIKEY" in message
    assert waits == []


def test_a_permanently_failing_server_error_stops_at_the_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Overload that never clears gets a fixed number of requests, no more.

    The SDK would otherwise add its own five on top of these, which is how one
    refused call turns into thirty requests against a twenty-a-day quota.
    """
    waits: list[float] = []
    monkeypatch.setattr(gemini_module, "_sleep", waits.append)
    client = _Client(_unavailable())

    with pytest.raises(_HTTPError):
        _generate(client, GeminiTool.SCENE)

    budget = gemini_module._MAX_ATTEMPTS
    assert client.models.calls == budget
    assert len(waits) == budget - 1


def test_a_transport_fault_is_retried_even_with_no_status_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    httpx = pytest.importorskip("httpx")
    fault = httpx.ReadError("connection reset by peer")
    assert gemini_module._is_transient(fault) is True
    assert gemini_module._is_rate_limit(fault) is False

    waits: list[float] = []
    monkeypatch.setattr(gemini_module, "_sleep", waits.append)
    client = _Client(fault, '{"operations": []}')

    assert isinstance(_generate(client, GeminiTool.SCENE), _Response)
    assert client.models.calls == 2
    assert 1.5 <= waits[0] <= 4.5


def test_an_ordinary_error_is_never_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    waits: list[float] = []
    monkeypatch.setattr(gemini_module, "_sleep", waits.append)
    client = _Client(RuntimeError("a bug, not the network"), '{"operations": []}')

    with pytest.raises(RuntimeError, match="a bug, not the network"):
        _generate(client, GeminiTool.SCENE)

    assert waits == []
    assert client.models.calls == 1
