"""The live backend: Gemini structured output behind the provider seam.

This is the only module that talks to a network, and it is deliberately the only
one that imports the SDK -- lazily, inside :meth:`GeminiProvider.structured`, so
that installing ``manorem-ai`` without the ``gemini`` extra still imports cleanly
and every offline test runs with no client present. The SDK client is also
injectable, which is what a record run uses to wrap it in a cassette.

The call shape is the one Gemini's structured-output docs specify: a request whose
``response_format`` carries a JSON Schema, and a text response parsed back through
the Pydantic model. Two things make that safe rather than hopeful:

* The schema is down-converted first (:func:`~manorem_ai.schema_shim.to_gemini_schema`),
  because Pydantic emits ``$ref``/``$defs``/``const`` that Gemini rejects.
* The response is only *syntactically* guaranteed JSON; it is re-validated against
  the model, and a validation failure is a :class:`ProviderError`, not a value that
  slips through half-formed. The docs are explicit that structure is not semantics,
  so the boundary re-checks rather than trusts.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ValidationError

from manorem_ai.provider import Completion, Prompt, ProviderError, Usage
from manorem_ai.schema_shim import to_gemini_schema

__all__ = ["GeminiProvider", "render_prompt"]


def render_prompt(prompt: Prompt) -> str:
    """Flatten a :class:`Prompt` into the single ``input`` string the API takes.

    System instruction first, then any few-shot pairs in order, then the request.
    The exact text is part of the cassette key, so this must be deterministic --
    same prompt, same string, same recording.
    """
    parts: list[str] = [prompt.system]
    for example in prompt.examples:
        parts.append(f"Example input:\n{example.input}\n\nExample output:\n{example.output}")
    parts.append(prompt.user)
    return "\n\n---\n\n".join(parts)


def _usage_from(interaction: Any) -> Usage:
    """Best-effort token accounting; zeros when the SDK does not report it."""
    meta = getattr(interaction, "usage", None) or getattr(interaction, "usage_metadata", None)
    if meta is None:
        return Usage()
    return Usage(
        prompt_tokens=int(getattr(meta, "prompt_token_count", 0) or 0),
        completion_tokens=int(getattr(meta, "candidates_token_count", 0) or 0),
    )


class GeminiProvider:
    """Google Gemini as an :class:`~manorem_ai.provider.LLMProvider`.

    Never exercised in the default test run -- CI has no key and the network
    marker gates any live call. It exists to be wrapped by
    :class:`~manorem_ai.cassette.CassetteProvider` in record mode, which is how
    the committed fixtures are refreshed.
    """

    name = "gemini"

    def __init__(self, *, api_key: str | None = None, client: Any | None = None) -> None:
        self._api_key = api_key
        self._client = client

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from google import genai  # noqa: PLC0415 - lazy so `import manorem_ai` needs no extra
        except ImportError as exc:  # pragma: no cover - exercised only without the extra
            raise ProviderError(
                "the gemini extra is not installed; `uv sync --extra gemini` or use "
                "the cassette provider offline"
            ) from exc
        if self._api_key is None:
            raise ProviderError("GeminiProvider needs an api_key to build a client")
        self._client = genai.Client(api_key=self._api_key)
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
        response_format = {
            "type": "text",
            "mime_type": "application/json",
            "schema": to_gemini_schema(schema),
        }
        try:
            interaction = client.interactions.create(
                model=model,
                input=render_prompt(prompt),
                response_format=response_format,
                temperature=temperature,
                max_output_tokens=max_tokens,
            )
        except Exception as exc:
            raise ProviderError(f"gemini call failed: {exc}") from exc

        raw = getattr(interaction, "output_text", None)
        if not raw:
            raise ProviderError("gemini returned no output_text")
        try:
            value = schema.model_validate_json(raw)
        except ValidationError as exc:
            raise ProviderError(
                f"gemini output did not validate against {schema.__name__}: {exc}"
            ) from exc

        return Completion(
            value=value,
            model=model,
            usage=_usage_from(interaction),
            raw_id=str(getattr(interaction, "id", "")),
        )
