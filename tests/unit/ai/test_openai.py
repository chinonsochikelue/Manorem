"""OpenAIProvider: JSON extraction and structured call path.

Tests mirror :mod:`tests/unit/ai/test_anthropic` but for the OpenAI-style
``chat.completions.create`` interface. The SDK client is injectable, so tests
use a fake that returns a controlled response.
"""

from __future__ import annotations

import json as _json_mod
from typing import Any

import pytest

from manorem_ai import (
    Completion,
    OutputValidationError,
    Prompt,
    PromptExample,
    ProviderError,
    RateLimitError,
)
from manorem_ai.openai import OpenAIProvider
from tests.support.ai_builders import outline

_PROMPT = Prompt(
    system="be a story agent",
    user="the idea",
    examples=(PromptExample(input="in", output="out"),),
)
_SCHEMA = type(outline())
_VALID_JSON = outline().model_dump_json()


class _Usage:
    prompt_tokens = 7
    completion_tokens = 3


class _Msg:
    def __init__(self, text: str) -> None:
        self.content = text
        self.role = "user"


class _Choice:
    def __init__(self, text: str) -> None:
        self.message = _Msg(text)


class _Response:
    def __init__(self, text: str, usage: Any = None, resp_id: str = "resp-1") -> None:
        self.choices = [_Choice(text)]
        self.id = resp_id
        self.usage = usage


def _fake_client(response: _Response) -> Any:
    class _Completions:
        def create(self, **kwargs: Any) -> _Response:
            return response

    class _Chat:
        completions = _Completions()

    class FakeClient:
        chat = _Chat()

    return FakeClient()


def test_structured_with_injected_client_returns_completion() -> None:
    response = _Response(_VALID_JSON, _Usage())
    provider = OpenAIProvider(client=_fake_client(response))
    result = provider.structured(
        prompt=_PROMPT, schema=_SCHEMA, model="gpt-4", temperature=0.4, max_tokens=512
    )
    assert isinstance(result, Completion)
    assert result.value.title == "How GPS Works"
    assert result.model == "gpt-4"
    assert result.usage.prompt_tokens == 7
    assert result.usage.completion_tokens == 3


def test_structured_unwraps_fenced_json() -> None:
    response = _Response(f"```json\n{_VALID_JSON}\n```", _Usage())
    provider = OpenAIProvider(client=_fake_client(response))
    result = provider.structured(
        prompt=_PROMPT, schema=_SCHEMA, model="gpt-4", temperature=0.4, max_tokens=512
    )
    assert result.value.title == "How GPS Works"


def test_structured_unwraps_prose_around_json() -> None:
    response = _Response(f"Here is the answer:\n{_VALID_JSON}\nDone.", _Usage())
    provider = OpenAIProvider(client=_fake_client(response))
    result = provider.structured(
        prompt=_PROMPT, schema=_SCHEMA, model="gpt-4", temperature=0.0, max_tokens=8
    )
    assert result.value.title == "How GPS Works"


def test_structured_raises_on_no_json() -> None:
    response = _Response("no json here", _Usage())
    provider = OpenAIProvider(client=_fake_client(response))
    with pytest.raises(ProviderError, match="no text content"):
        provider.structured(
            prompt=_PROMPT, schema=_SCHEMA, model="gpt-4", temperature=0.0, max_tokens=8
        )


def test_structured_raises_validation_error_on_bad_output() -> None:
    bad = outline().model_dump()
    bad["title"] = ""  # violates min_length=1
    response = _Response(_json_mod.dumps(bad), _Usage())
    provider = OpenAIProvider(client=_fake_client(response))
    with pytest.raises(OutputValidationError):
        provider.structured(
            prompt=_PROMPT, schema=_SCHEMA, model="gpt-4", temperature=0.0, max_tokens=8
        )


def test_structured_raises_rate_limit_error_on_429() -> None:
    class _Completions:
        def create(self, **kwargs: Any) -> Any:
            raise type("RateLimitErr", (Exception,), {"status_code": 429})()

    class _Chat:
        completions = _Completions()

    class FakeClient:
        chat = _Chat()

    provider = OpenAIProvider(client=FakeClient())
    with pytest.raises(RateLimitError):
        provider.structured(
            prompt=_PROMPT, schema=_SCHEMA, model="gpt-4", temperature=0.0, max_tokens=8
        )


def test_structured_raises_provider_error_on_transport_failure() -> None:
    class _Completions:
        def create(self, **kwargs: Any) -> Any:
            raise RuntimeError("network down")

    class _Chat:
        completions = _Completions()

    class FakeClient:
        chat = _Chat()

    provider = OpenAIProvider(client=FakeClient())
    with pytest.raises(ProviderError, match="openai call failed"):
        provider.structured(
            prompt=_PROMPT, schema=_SCHEMA, model="gpt-4", temperature=0.0, max_tokens=8
        )


def test_structured_without_client_or_key_raises_provider_error() -> None:
    """Without a client or api_key, the provider must raise a ProviderError."""
    provider = OpenAIProvider()
    with pytest.raises(ProviderError):
        provider.structured(
            prompt=_PROMPT, schema=_SCHEMA, model="gpt-4", temperature=0.0, max_tokens=8
        )


def test_reuses_anthropic_json_extraction() -> None:
    """OpenAIProvider reuses _extract_json from anthropic to avoid divergence."""
    from manorem_ai.anthropic import _extract_json  # noqa: PLC0415

    result = _extract_json('```json\n{"a": 1}\n```')
    assert result == '{"a": 1}'
