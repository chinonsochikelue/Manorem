"""The live backend: Gemini structured output behind the provider seam.

This is the only module that talks to a network, and it is deliberately the only
one that imports the SDK -- lazily, inside :meth:`GeminiProvider._ensure_client`,
so that installing ``manorem-ai`` without the ``gemini`` extra still imports
cleanly and every offline test runs with no client present.

Two decisions live here and are pinned by tests, not by convention:

* **Which tool a request bills to.** :data:`TOOL_BY_SCHEMA` maps each response
  schema to its owning :class:`~manorem_core.settings.GeminiTool`; a provider
  built for recording pins one tool for every stage instead. A schema no tool
  owns is refused rather than billed to another tool's credential.
* **What a 429 means.** A daily-quota refusal will not clear inside a backoff
  window, so long waits are reported, not slept through; short, honourable waits
  are slept once and retried a bounded number of times. Either way the error
  names the tool and its variable, never the credential.

The call shape is the one Gemini's structured-output docs specify: a
``generate_content`` request whose ``response_json_schema`` carries a JSON
Schema (with ``response_mime_type="application/json"``), and a text response
parsed back through the Pydantic model. Two things make that safe rather than
hopeful:

* The schema is down-converted first (:func:`~manorem_ai.schema_shim.to_gemini_schema`),
  because Pydantic emits ``$ref``/``$defs``/``const`` that Gemini rejects -- and
  the converter seeds an empty ``propertyOrdering`` on every multi-property
  object, which makes the SDK skip injecting its own full ordering (a shape the
  backend answers with a bare ``400`` on schemas the size of ``Scene``).
* The response is only *syntactically* guaranteed JSON; it is re-validated
  against the model, and a validation failure is a :class:`ProviderError`, not
  a value that slips through half-formed.
"""

from __future__ import annotations

import random
import re
import time
from typing import Any

from pydantic import BaseModel, ValidationError

from manorem_ai.agents.models import Script, StoryOutline, VisualPlan
from manorem_ai.patch import JsonPatch
from manorem_ai.provider import Completion, Prompt, ProviderError, RateLimitError, Usage
from manorem_ai.research.models import EvidenceAssessment, ResearchBrief
from manorem_ai.schema_shim import to_gemini_schema
from manorem_core import GeminiTool
from manorem_ir import Scene

__all__ = ["TOOL_BY_SCHEMA", "GeminiProvider", "render_prompt", "tool_for_schema"]

#: Which tool owns each response schema. A request bills to its schema's tool;
#: recording pins one tool for every stage instead (see ``GeminiProvider``).
TOOL_BY_SCHEMA: dict[type[BaseModel], GeminiTool] = {
    EvidenceAssessment: GeminiTool.EVIDENCE,
    JsonPatch: GeminiTool.REPAIR,
    ResearchBrief: GeminiTool.RESEARCH,
    Scene: GeminiTool.SCENE,
    Script: GeminiTool.SCRIPT,
    StoryOutline: GeminiTool.STORY,
    VisualPlan: GeminiTool.VISUAL_PLAN,
}


def tool_for_schema(schema: type[BaseModel]) -> GeminiTool | None:
    """The tool that owns ``schema``, or ``None`` when none does."""
    return TOOL_BY_SCHEMA.get(schema)


# A 429 (quota/rate limit) is deliberately *not* folded into the transient
# budget below: a daily-quota refusal will not clear within a backoff window,
# and retrying it only burns more of the very quota that is exhausted. Short,
# honourable waits are slept once; anything longer is reported at once so the
# operator sees it. Other 4xx raise immediately too.
_RETRYABLE_CODES = frozenset({500, 502, 503, 504})
_MAX_ATTEMPTS = 6
_MAX_RATE_LIMIT_RETRIES = 2
_BACKOFF_BASE_S = 3.0
_BACKOFF_CAP_S = 30.0
_JITTER_FLOOR = 0.5
_JITTER_CEILING = 1.5
_RETRY_AFTER_CAP_S = 60
_TRANSIENT_TRANSPORTS = frozenset({"httpx", "httpcore"})

_sleep = time.sleep


def _is_transient(exc: Exception) -> bool:
    """Whether ``exc`` is worth one more attempt: a 5xx, or a transport fault.

    SDK errors carry an integer ``code``; transport faults (``httpx``,
    ``httpcore``) carry none, so they are recognised by origin instead. Anything
    else -- a 4xx, a bug -- is permanent and must surface at once.
    """
    code = getattr(exc, "code", None)
    if isinstance(code, int) and code in _RETRYABLE_CODES:
        return True
    return type(exc).__module__.split(".", 1)[0] in _TRANSIENT_TRANSPORTS


def _is_rate_limit(exc: Exception) -> bool:
    """Whether ``exc`` is the backend refusing for quota reasons."""
    return getattr(exc, "code", None) == 429


def _retry_after_s(exc: Exception) -> float | None:
    """The ``retryDelay`` the backend asked for, in seconds, if it named one."""
    match = re.search(r"""retryDelay['"]?\s*:\s*['"]?(\d+(?:\.\d+)?)s""", str(exc))
    return float(match.group(1)) if match is not None else None


def _human_duration(seconds: float) -> str:
    """``62328`` -> ``17h18m``: a wait an operator can read at a glance."""
    total = int(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours > 0:
        return f"{hours}h{minutes:02d}m"
    if minutes > 0:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def _backoff(attempt: int) -> float:
    """Capped exponential backoff with jitter, so a fleet does not march in step."""
    grown = min(_BACKOFF_BASE_S * 2**attempt, _BACKOFF_CAP_S)
    return float(grown * random.uniform(_JITTER_FLOOR, _JITTER_CEILING))


def _rate_limit_message(tool: GeminiTool | None, delay: float | None) -> str:
    """Name the tool and its variable -- never the credential value."""
    name = tool.value if tool is not None else "gemini"
    variable = tool.env_var if tool is not None else "its API key"
    if delay is None:
        return (
            f"gemini rate-limited the {name} tool ({variable}) with no usable "
            "retry delay, after its bounded retries. No credential value is "
            "reported here."
        )
    return (
        f"gemini rate-limited the {name} tool ({variable}); the backend asked "
        f"to retry in {_human_duration(delay)}, which is longer than this "
        "client will defer -- record a cassette, wait it out, or rotate the "
        "key. No credential value is reported here."
    )


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

    Takes exactly one of ``api_key`` (a literal credential, for tests and
    one-off scripts) and ``resolver`` (per-tool credentials from settings).
    With a resolver, each request draws its schema's tool -- unless ``tool``
    pins one, which concentrates every stage on a single credential. Recording
    deliberately does not pin: each stage bills its own tool, so the spend
    follows the same per-tool budgets as a live run.
    """

    name = "gemini"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        resolver: Any | None = None,
        tool: GeminiTool | None = None,
    ) -> None:
        if (api_key is None) == (resolver is None):
            raise ValueError(
                "GeminiProvider takes exactly one of api_key= / resolver=, not both and not neither"
            )
        self._api_key = api_key
        self._resolver = resolver
        self._tool = tool
        self._clients: dict[str, Any] = {}

    def _ensure_client(self, tool: GeminiTool | None) -> Any:
        """One client per tool, so per-tool credentials never share a client.

        The SDK's own retry loop is switched off here: its default five
        attempts would multiply every attempt of the policy below, turning one
        refused call into thirty requests against a twenty-a-day quota. This
        module is the sole retry authority.
        """
        key = tool.value if tool is not None else "__api_key__"
        if key not in self._clients:
            try:
                from google import genai  # noqa: PLC0415 - lazy optional import, keep as-is
                from google.genai import types as genai_types  # noqa: PLC0415 - same
            except ImportError as exc:  # pragma: no cover - exercised only without the extra
                raise ProviderError(
                    "the gemini extra is not installed; `uv sync --extra gemini` or use "
                    "the cassette provider offline"
                ) from exc
            if self._resolver is not None:
                if tool is None:  # pragma: no cover - structured() refuses this first
                    raise ProviderError("a resolver needs a tool to draw a credential for")
                credential = self._resolver.key(tool)
            else:
                assert self._api_key is not None  # guaranteed by __init__
                credential = self._api_key
            http_options = genai_types.HttpOptions(
                retry_options=genai_types.HttpRetryOptions(attempts=1)
            )
            self._clients[key] = genai.Client(api_key=credential, http_options=http_options)
        return self._clients[key]

    @staticmethod
    def _generate_with_retry(
        client: Any, *, model: str, contents: str, config: Any, tool: GeminiTool | None
    ) -> Any:
        """Call ``generate_content``, retrying transient 5xx and short 429s.

        429s get at most :data:`_MAX_RATE_LIMIT_RETRIES` retries: a named wait
        within the cap is slept once, a wait past it raises immediately, and a
        wait never named gets the ordinary backoff. Anything else transient
        shares the :data:`_MAX_ATTEMPTS` budget; anything permanent raises at
        once. A 429 that survives all of this raises :class:`RateLimitError`
        unwrapped, so a key pool can fail over on it.
        """
        rate_limit_tries = 0
        for attempt in range(_MAX_ATTEMPTS):
            try:
                return client.models.generate_content(model=model, contents=contents, config=config)
            except Exception as exc:
                if _is_rate_limit(exc):
                    delay = _retry_after_s(exc)
                    if delay is not None and delay > _RETRY_AFTER_CAP_S:
                        raise RateLimitError(_rate_limit_message(tool, delay)) from exc
                    if rate_limit_tries >= _MAX_RATE_LIMIT_RETRIES:
                        raise RateLimitError(_rate_limit_message(tool, delay)) from exc
                    _sleep(delay if delay is not None else _backoff(attempt))
                    rate_limit_tries += 1
                    continue
                if attempt + 1 >= _MAX_ATTEMPTS or not _is_transient(exc):
                    raise
                _sleep(_backoff(attempt))
        raise AssertionError("unreachable: loop either returns or raises")  # pragma: no cover

    def structured[T: BaseModel](
        self,
        *,
        prompt: Prompt,
        schema: type[T],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> Completion[T]:
        tool = self._tool if self._tool is not None else tool_for_schema(schema)
        if self._resolver is not None and tool is None:
            raise ProviderError(
                f"no Gemini tool is registered for schema {schema.__name__}; add it to "
                "TOOL_BY_SCHEMA so this request can draw its own credential"
            )
        client = self._ensure_client(tool)
        from google.genai import types as genai_types  # noqa: PLC0415 - lazy, as the client

        config = genai_types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
            response_mime_type="application/json",
            response_schema=to_gemini_schema(schema),
        )
        try:
            response = self._generate_with_retry(
                client, model=model, contents=render_prompt(prompt), config=config, tool=tool
            )
        except RateLimitError:
            # Already worded for an operator, and carrying the tool it belongs
            # to; re-wrapping it in a plain ProviderError would hide the rate
            # limit from a key pool's failover.
            raise
        except Exception as exc:
            raise ProviderError(f"gemini call failed: {exc}") from exc

        raw = getattr(response, "text", None)
        if not raw:
            raise ProviderError("gemini returned no text")
        try:
            value = schema.model_validate_json(raw)
        except ValidationError as exc:
            raise ProviderError(
                f"gemini output did not validate against {schema.__name__}: {exc}"
            ) from exc

        return Completion(
            value=value,
            model=model,
            usage=_usage_from(response),
            raw_id=str(getattr(response, "response_id", "")),
        )
