"""What every LLM backend promises, and what it hands back.

One protocol, :class:`LLMProvider`, sits between the agents and whatever produces
JSON -- Gemini, a recorded cassette, or a hand-written stub. An agent names a
Pydantic ``schema`` and gets back a parsed, validated instance of it or a
:class:`ProviderError`; it never sees raw text, a model id, or an SDK. That is the
seam the whole AI layer is built on, and it is deliberately narrow: *structured
output only*. There is no free-text ``complete`` method, because nothing in the
pipeline wants prose it would then have to parse.

**Synchronous by design in M1.** The provider call is a blocking request. M1 runs
one scene at a time in one process, so there is no concurrency for ``async`` to
buy here; per-scene fan-out is a job-queue concern (Slice 4, ``arq``), and that is
the layer where an event loop belongs. Keeping the provider sync keeps the CLI and
the entire test suite free of an async runner. The seam can grow an async variant
later without any agent changing, because agents depend on this protocol, not on a
concrete backend.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from manorem_core import ManoremError, canonical_json, sha256_of

__all__ = [
    "Completion",
    "LLMProvider",
    "Prompt",
    "PromptExample",
    "ProviderError",
    "Usage",
]


class ProviderError(ManoremError):
    """A backend could not return a valid instance of the requested schema.

    Raised for a transport failure, a response that would not parse, or a
    validation error against the schema. The pipeline treats it as a stage
    failure, not as a diagnostic the repair loop can act on -- there is no IR to
    repair when the model never produced one.
    """


class PromptExample(BaseModel):
    """One few-shot pair. Kept in the prompt so it is part of the cache key."""

    model_config = ConfigDict(frozen=True)

    input: str
    output: str


class Prompt(BaseModel):
    """The full instruction to a model, assembled by an agent.

    A model, not a string, so it serializes canonically into the cassette key: two
    runs that build the same instruction hit the same recording, and a changed
    instruction misses it rather than replaying a stale answer against new intent.
    """

    model_config = ConfigDict(frozen=True)

    #: The standing instruction -- who the model is and what it must produce.
    system: str = Field(min_length=1)
    #: The specific request -- the idea, the beat, the diagnostics to repair.
    user: str = Field(min_length=1)
    #: Few-shot exemplars, prepended in order. Part of the cache key.
    examples: tuple[PromptExample, ...] = ()


@dataclass(frozen=True, slots=True)
class Usage:
    """Token accounting for one call. Zeros when a backend cannot report it."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True, slots=True)
class Completion[T: BaseModel]:
    """A parsed, validated result plus the trace metadata every call carries.

    ``value`` is the whole point; the rest is what makes §27 tracing free -- which
    model answered, how many tokens it cost, how long it took, and the backend's own
    id for the call so a log line can be joined back to a provider dashboard.
    """

    value: T
    model: str
    usage: Usage = field(default_factory=Usage)
    latency_ms: int = 0
    #: The backend's identifier for this call (Gemini interaction id, cassette
    #: key, or ``""`` for the stub). Never used for control flow; trace only.
    raw_id: str = ""


def prompt_cache_key(*, prompt: Prompt, schema: type[BaseModel], model: str) -> str:
    """Content address of a request: (prompt, schema, model).

    The cassette layer keys recordings on exactly this, so a replay is a function of
    what was asked and nothing else. The schema is folded in by its JSON Schema, so
    changing a field -- and therefore what a valid answer looks like -- misses the
    old recording instead of replaying an answer that no longer fits.
    """
    payload = {
        "prompt": prompt.model_dump(mode="json"),
        "schema": schema.model_json_schema(),
        "model": model,
    }
    return sha256_of(canonical_json(payload))


class LLMProvider(Protocol):
    """A backend that turns a prompt into a validated instance of a schema."""

    name: str

    def structured[T: BaseModel](
        self,
        *,
        prompt: Prompt,
        schema: type[T],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> Completion[T]: ...
