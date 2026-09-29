"""AnthropicProvider: JSON extraction, system rendering, and structured call path.

The provider is never exercised against the network in CI (no key, no live call).
The SDK client is injectable, so tests use a fake that records the request and
returns a controlled response -- covering the happy path, fence unwrapping,
prose-wrapped JSON, extraction failures, and validation failures.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import BaseModel

from manorem_ai import (
    Completion,
    OutputValidationError,
    Prompt,
    PromptExample,
    ProviderError,
    RateLimitError,
)
from manorem_ai.anthropic import (
    AnthropicProvider,
    _extract_json,
    _is_rate_limit,
    _json_system,
    render_user,
)
from tests.support.ai_builders import outline

_PROMPT = Prompt(
    system="be a story agent",
    user="the idea",
    examples=(PromptExample(input="in", output="out"),),
)
_SCHEMA = type(outline())
_VALID_JSON = outline().model_dump_json()


def test_render_user_flattens_prompt() -> None:
    rendered = render_user(_PROMPT)
    assert "Example input:" in rendered
    assert "Example output:" in rendered
    assert "the idea" in rendered


def test_json_system_contains_schema() -> None:
    class M(BaseModel):
        x: int

    system = _json_system("base instructions", M)
    assert "base instructions" in system
    assert "JSON Schema" in system
    # The schema is embedded as compact JSON (no spaces after colons).
    assert '"properties"' in system


def test_extract_json_plain_object() -> None:
    result = _extract_json('{"a": 1}')
    assert result == '{"a": 1}'


def test_extract_json_strips_fence() -> None:
    result = _extract_json('```json\n{"a": "b"}\n```')
    assert result == '{"a": "b"}'


def test_extract_json_strips_plain_fence() -> None:
    result = _extract_json('```\n{"a": "b"}\n```')
    assert result == '{"a": "b"}'


def test_extract_json_strips_prefix_and_suffix() -> None:
    result = _extract_json('Here is the answer:\n{"a": 1}\nThat is all.')
    assert result == '{"a": 1}'


def test_extract_json_handles_nested_objects() -> None:
    text = '{"outer": {"inner": {"deep": true}}}'
    result = _extract_json(text)
    assert result == text


def test_extract_json_handles_strings_with_braces() -> None:
    text = '{"msg": "a } b"}'
    result = _extract_json(text)
    assert result == text


def test_extract_json_handles_escaped_quotes() -> None:
    text = '{"msg": "say \\"hi\\""}'
    result = _extract_json(text)
    assert result == text


def test_extract_json_no_brace_returns_empty() -> None:
    assert _extract_json("no json here") == ""


def test_is_rate_limit_detects_429_attribute() -> None:
    class FakeError(Exception):
        status_code = 429

    assert _is_rate_limit(FakeError())


def test_is_rate_limit_detects_message_text() -> None:
    assert _is_rate_limit(Exception("429 rate limit exceeded"))
    assert _is_rate_limit(Exception("rate limit hit"))


def _make_provider(
    response_text: str, msg_id: str = "msg-1", usage: Any = None
) -> AnthropicProvider:
    class FakeMessage:
        def __init__(self) -> None:
            self.content = [{"text": response_text}]
            self.id = msg_id
            self.usage = usage

    class FakeMessages:
        def create(self, **kwargs: Any) -> Any:
            return FakeMessage()

    class FakeClient:
        messages = FakeMessages()

    return AnthropicProvider(client=FakeClient())


class _Usage:
    input_tokens = 10
    output_tokens = 5


def test_structured_with_injected_client_returns_completion() -> None:
    """The happy path: a fake client returns JSON text, provider validates it."""
    provider = _make_provider(_VALID_JSON, usage=_Usage())
    result = provider.structured(
        prompt=_PROMPT, schema=_SCHEMA, model="claude-x", temperature=0.4, max_tokens=8192
    )
    assert isinstance(result, Completion)
    assert result.value.title == "How GPS Works"
    assert result.model == "claude-x"
    assert result.raw_id == "msg-1"
    assert result.usage.prompt_tokens == 10
    assert result.usage.completion_tokens == 5


def test_structured_unwraps_fenced_json_from_text() -> None:
    """A response wrapped in markdown fences must still parse."""
    provider = _make_provider(f"```json\n{_VALID_JSON}\n```")
    result = provider.structured(
        prompt=_PROMPT, schema=_SCHEMA, model="claude-x", temperature=0.4, max_tokens=8192
    )
    assert result.value.title == "How GPS Works"


def test_structured_raises_on_no_json() -> None:
    provider = _make_provider("no json here")
    with pytest.raises(ProviderError, match="no text content"):
        provider.structured(
            prompt=_PROMPT, schema=_SCHEMA, model="claude-x", temperature=0.0, max_tokens=8
        )


def test_structured_raises_validation_error_on_bad_output() -> None:
    bad = outline().model_dump()
    bad["title"] = ""  # violates min_length=1
    provider = _make_provider(json.dumps(bad))
    with pytest.raises(OutputValidationError):
        provider.structured(
            prompt=_PROMPT, schema=_SCHEMA, model="claude-x", temperature=0.0, max_tokens=8
        )


def test_structured_raises_rate_limit_error_on_429() -> None:
    class FakeMessages:
        def create(self, **kwargs: Any) -> Any:
            raise type("RateLimitErr", (Exception,), {"status_code": 429})()

    class FakeClient:
        messages = FakeMessages()

    provider = AnthropicProvider(client=FakeClient())
    with pytest.raises(RateLimitError):
        provider.structured(
            prompt=_PROMPT, schema=_SCHEMA, model="claude-x", temperature=0.0, max_tokens=8
        )


def test_structured_raises_provider_error_on_transport_failure() -> None:
    class FakeMessages:
        def create(self, **kwargs: Any) -> Any:
            raise RuntimeError("network down")

    class FakeClient:
        messages = FakeMessages()

    provider = AnthropicProvider(client=FakeClient())
    with pytest.raises(ProviderError, match="anthropic call failed"):
        provider.structured(
            prompt=_PROMPT, schema=_SCHEMA, model="claude-x", temperature=0.0, max_tokens=8
        )


def test_structured_without_client_or_key_raises_provider_error() -> None:
    """Without a client or api_key, the provider must raise a ProviderError."""
    provider = AnthropicProvider()
    with pytest.raises(ProviderError):
        provider.structured(
            prompt=_PROMPT, schema=_SCHEMA, model="claude-x", temperature=0.0, max_tokens=8
        )
