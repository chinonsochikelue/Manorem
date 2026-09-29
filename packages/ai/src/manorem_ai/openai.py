"""The OpenAI backend: structured output behind the provider seam.

Parallel to :mod:`~manorem_ai.anthropic`. The ``openai`` SDK is imported lazily
inside :meth:`OpenAIProvider.structured` so installing ``manorem-ai`` without the
``openai`` extra still imports cleanly and every offline test runs with no client
present. The SDK client is injectable, which is what the tests use to drive the
provider with a fake in place of a real one.

This provider does not use the SDK's native ``response_format.schema`` structured
output. That path is unavailable through the JustWorker gateway (Cloudflare
blocks the OpenAI endpoint for Python and strips the structured-output envelope
anyway), and on the native endpoint it returns *JSON-as-string* which still needs
extraction. Instead, this adapter asks for JSON in the system turn -- the schema is
appended verbatim -- and extracts the object from the returned text, unwrapping a
```json` fence or surrounding prose, then validates it against the Pydantic model at
the boundary. One request, one validation, identical behaviour whether the call
lands on ``api.openai.com`` or ``api.justwoker.icu``.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ValidationError

from manorem_ai.anthropic import _extract_json, _is_rate_limit, render_user
from manorem_ai.provider import (
    Completion,
    OutputValidationError,
    Prompt,
    ProviderError,
    RateLimitError,
    Usage,
    validation_feedback,
)

__all__ = ["OpenAIProvider"]


def _render_system(system: str, schema: type[BaseModel]) -> str:
    """Append a JSON-only instruction carrying the schema to the standing system.

    Mirrors :func:`manorem_ai.anthropic._json_system` so the two providers speak the
    same contract to their models -- only the exact wording changes to match what
    each model answers best to.
    """
    spec = json.dumps(schema.model_json_schema(), separators=(",", ":"))
    return (
        f"{system}\n\n"
        "Respond with a single JSON object and nothing else -- no prose, no markdown "
        "code fences. It must validate against this JSON Schema:\n"
        f"{spec}"
    )


class OpenAIProvider:
    """OpenAI-compatible models as an :class:`~manorem_ai.provider.LLMProvider`.

    Like :class:`~manorem_ai.gemini.GeminiProvider` and
    :class:`~manorem_ai.anthropic.AnthropicProvider`, it is never exercised in the
    default test run -- CI has no key and the network marker gates any live call.
    It serves live ``build`` runs (``MANOREM_LLM_PROVIDER=openai``) and is wrapped
    by :class:`~manorem_ai.cassette.CassetteProvider` when recording fixtures.

    The Cloudflare block on the OpenAI endpoint for Python is transparent to this
    class: routing through JustWorker (``base_url``) or a local proxy keeps the same
    ``openai`` client interface, only the network path differs.
    """

    name = "openai"

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
            from openai import OpenAI  # noqa: PLC0415 - lazy so `import manorem_ai` is free
        except ImportError as exc:  # pragma: no cover - exercised only without the extra
            raise ProviderError(
                "the openai extra is not installed; `uv sync --extra openai` or use "
                "the cassette provider offline"
            ) from exc
        if self._api_key is None:
            raise ProviderError("OpenAIProvider needs an api_key to build a client")
        # ``base_url`` is passed only when set, so the native endpoint stays the SDK
        # default; a gateway (e.g. JustWorker) is opt-in via the setting.
        kwargs: dict[str, Any] = {"api_key": self._api_key}
        if self._base_url is not None:
            kwargs["base_url"] = self._base_url
        self._client = OpenAI(**kwargs)
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
        # Reuse the same user-message rendering as the Anthropic adapter so the
        # prompt text -- and therefore the cassette key -- is identical across
        # OpenAI and Anthropic providers.
        system = _render_system(prompt.system, schema)
        try:
            response = client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": render_user(prompt)},
                ],
            )
        except Exception as exc:
            if _is_rate_limit(exc):
                raise RateLimitError(f"openai rate limit hit: {exc}") from exc
            raise ProviderError(f"openai call failed: {exc}") from exc

        text = response.choices[0].message.content
        payload = _extract_json(text) if text else ""
        if not payload:
            raise ProviderError("openai returned no text content")
        try:
            value = schema.model_validate_json(payload)
        except ValidationError as exc:
            raise OutputValidationError(
                f"openai output did not validate against {schema.__name__}: {exc}",
                feedback=validation_feedback(schema, exc),
            ) from exc

        usage_meta = getattr(response, "usage", None)
        usage = Usage(
            prompt_tokens=int((usage_meta and usage_meta.prompt_tokens) or 0),
            completion_tokens=int((usage_meta and usage_meta.completion_tokens) or 0),
        )
        return Completion(
            value=value,
            model=model,
            usage=usage,
            raw_id=getattr(response, "id", "") or "",
        )
