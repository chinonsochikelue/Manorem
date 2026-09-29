"""The Anthropic backend: Claude structured output behind the provider seam.

A sibling of :mod:`~manorem_ai.gemini`. Like it, this is a network module and the
only one that imports the ``anthropic`` SDK -- lazily, inside
:meth:`AnthropicProvider.structured`, so installing ``manorem-ai`` without the
``anthropic`` extra still imports cleanly and every offline test runs with no
client present. The SDK client is injectable, which is what the tests use to drive
the provider with a fake in place of a real one.

The SDK's ``messages.parse`` (native structured output via ``output_format``) is the
clean path against ``api.anthropic.com``. It does not survive an OpenAI-style gateway:
routing Claude through one (e.g. JustWorker at ``api.justwoker.icu``) reaches a
``/v1/messages`` endpoint that ignores the structured-output tool protocol and returns
the JSON as fenced text in an ordinary text block, on which ``parse`` raises. So this
adapter takes the gateway-agnostic path that also works natively: it asks for JSON in
the ``system`` turn (the schema is appended verbatim), then extracts the object from
the returned text -- unwrapping a ```` ```json ```` fence or surrounding prose -- and
validates it against the Pydantic model at the boundary. One request, one validation,
no dependence on vendor-specific structured-output support.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ValidationError

from manorem_ai.provider import (
    Completion,
    OutputValidationError,
    Prompt,
    ProviderError,
    RateLimitError,
    Usage,
    validation_feedback,
)

__all__ = ["AnthropicProvider", "render_user"]


def render_user(prompt: Prompt) -> str:
    """Flatten a :class:`Prompt` into the ``user`` message Claude receives.

    The standing instruction goes to the API's dedicated ``system`` field, so only
    the few-shot pairs and the request itself belong here. Deterministic by design:
    the same prompt yields the same string, which is part of the cassette key.
    """
    parts: list[str] = []
    for example in prompt.examples:
        parts.append(f"Example input:\n{example.input}\n\nExample output:\n{example.output}")
    parts.append(prompt.user)
    return "\n\n---\n\n".join(parts)


def _json_system(system: str, schema: type[BaseModel]) -> str:
    """Append a JSON-only instruction carrying the schema to the standing system turn.

    This is what replaces native ``output_format``: the model is told to return one
    JSON object matching the schema and nothing else. Claude honours it on both the
    native endpoint and an OpenAI-style gateway that never implements structured output.
    """
    spec = json.dumps(schema.model_json_schema(), separators=(",", ":"))
    return (
        f"{system}\n\n"
        "Respond with a single JSON object and nothing else -- no prose, no Markdown "
        f"code fences. It must validate against this JSON Schema:\n{spec}"
    )


def _text_of(message: Any) -> str:
    """Concatenate the text blocks of a Messages response into one string."""
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content or []:
        text = getattr(block, "text", None)
        if text is None and isinstance(block, dict):
            text = block.get("text")
        if text:
            parts.append(str(text))
    return "".join(parts)


def _extract_json(text: str) -> str:
    """Recover the JSON object from a text answer.

    Unwraps a leading ```` ``` ```` / ```` ```json ```` fence and trailing fence, then
    extracts the outermost balanced ``{...}`` span so trailing prose or comments do
    not poison the parse. Uses a brace-matching scan (not ``rfind('}')``) so a ``}``
    that appears in trailing text is not mistaken for the JSON close.
    """
    s = text.strip()
    if s.startswith("```"):
        s = s[3:]
        if s[:4].lower() == "json":
            s = s[4:]
        s = s.strip()
    if s.endswith("```"):
        s = s[: s.rfind("```")].strip()

    start = s.find("{")
    if start == -1:
        return ""
    # Walk forward to the matching close, tracking nesting and string context so we
    # stop at the real JSON boundary rather than a stray ``}`` in trailing prose.
    depth = 0
    in_str = False
    escaped = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
    # No balanced close found; return what we have so validation can report the gap.
    return s[start:]


def _usage_from(message: Any) -> Usage:
    """Best-effort token accounting; zeros when the SDK does not report it."""
    meta = getattr(message, "usage", None)
    if meta is None:
        return Usage()
    return Usage(
        prompt_tokens=int(getattr(meta, "input_tokens", 0) or 0),
        completion_tokens=int(getattr(meta, "output_tokens", 0) or 0),
    )


def _is_rate_limit(exc: Exception) -> bool:
    """Is this SDK error a quota refusal (HTTP 429)?

    Mirrors the Gemini check: the ``anthropic`` error carries the status on
    ``status_code`` (and some paths on ``code``); we check both, then fall back to
    the message text so a wrapped or re-raised error is still recognised. Getting
    this wrong only costs a wasted failover attempt, so the check is deliberately
    generous.
    """
    for attr in ("status_code", "code"):
        if getattr(exc, attr, None) == 429:
            return True
    text = str(exc).lower()
    return "429" in text or "rate limit" in text or "rate_limit" in text


class AnthropicProvider:
    """Anthropic Claude as an :class:`~manorem_ai.provider.LLMProvider`.

    Like :class:`~manorem_ai.gemini.GeminiProvider`, it is never exercised in the
    default test run -- CI has no key and the network marker gates any live call.
    It exists to serve live ``build`` runs (``MANOREM_LLM_PROVIDER=anthropic``) and
    to be wrapped by :class:`~manorem_ai.cassette.CassetteProvider` when recording
    fixtures against Claude.
    """

    name = "anthropic"

    def __init__(
        self, *, api_key: str | None = None, base_url: str | None = None, client: Any | None = None
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._client = client

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from anthropic import Anthropic  # noqa: PLC0415 - lazy so `import manorem_ai` is free
        except ImportError as exc:  # pragma: no cover - exercised only without the extra
            raise ProviderError(
                "the anthropic extra is not installed; `uv sync --extra anthropic` or use "
                "the cassette provider offline"
            ) from exc
        if self._api_key is None:
            raise ProviderError("AnthropicProvider needs an api_key to build a client")
        # ``base_url`` is passed only when set, so the native endpoint stays the SDK
        # default; a gateway (e.g. AgentRouter) is opt-in via the setting.
        kwargs: dict[str, Any] = {"api_key": self._api_key}
        if self._base_url is not None:
            kwargs["base_url"] = self._base_url
        self._client = Anthropic(**kwargs)
        return self._client

    def structured[T: BaseModel](
        self,
        *,
        prompt: Prompt,
        schema: type[T],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> Completion[T]:
        client = self._ensure_client()
        try:
            # ``create`` (not ``parse``): the JSON contract lives in the system turn,
            # so this path is independent of vendor structured-output support and works
            # through an OpenAI-style gateway. ``parse`` takes ``temperature``; ``create``
            # does not on this SDK, so sampling goes through ``extra_body``, which the SDK
            # merges into the request body the Messages API reads it from.
            message = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=_json_system(prompt.system, schema),
                messages=[{"role": "user", "content": render_user(prompt)}],
                extra_body={"temperature": temperature},
            )
        except Exception as exc:
            if _is_rate_limit(exc):
                raise RateLimitError(f"anthropic rate limit hit: {exc}") from exc
            raise ProviderError(f"anthropic call failed: {exc}") from exc

        payload = _extract_json(_text_of(message))
        if not payload:
            raise ProviderError("anthropic returned no text content")
        try:
            value = schema.model_validate_json(payload)
        except ValidationError as exc:
            raise OutputValidationError(
                f"anthropic output did not validate against {schema.__name__}: {exc}",
                feedback=validation_feedback(schema, exc),
            ) from exc

        return Completion(
            value=value,
            model=model,
            usage=_usage_from(message),
            raw_id=str(getattr(message, "id", "")),
        )
