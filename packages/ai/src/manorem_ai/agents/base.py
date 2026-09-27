"""Shared machinery for the pipeline's agents.

Every agent does the same three things: assemble a :class:`~manorem_ai.provider.Prompt`
from a checked-in prompt file plus its typed input, ask the provider for a validated
instance of its output schema, and hand back the :class:`~manorem_ai.provider.Completion`
so the pipeline gets usage and tracing for free. That shared shape lives here; each
agent module supplies only its prompt name, its schema, and how its input renders.

Prompts are files, not string literals, so a prompt is diffable, reviewable, and not
tangled up with the code that sends it -- one prompt per agent, never one giant prompt.
Structured input is embedded as canonical JSON so the same input always renders the
same bytes, which is what keeps a cassette keyed on (prompt, schema, model) stable.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from manorem_ai.provider import Completion, LLMProvider, Prompt, PromptExample
from manorem_core import canonical_json

__all__ = ["Agent", "load_prompt", "render_input"]

_PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


@lru_cache(maxsize=32)
def load_prompt(name: str) -> str:
    """Read a checked-in prompt file by stem. Cached; prompts do not change at runtime."""
    path = _PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"no prompt file for agent {name!r} at {path}")
    return path.read_text(encoding="utf-8").strip()


def render_input(**sections: object) -> str:
    """Render named input sections as labelled canonical-JSON blocks, in order.

    Deterministic by construction: canonical JSON sorts keys and drops
    insignificant whitespace, so the user message is a pure function of the input.
    """
    blocks: list[str] = []
    for label, value in sections.items():
        heading = label.replace("_", " ").upper()
        blocks.append(f"{heading}:\n{canonical_json(value)}")
    return "\n\n".join(blocks)


class Agent:
    """Provider plus call configuration; the base every agent extends."""

    def __init__(
        self,
        provider: LLMProvider,
        *,
        model: str,
        temperature: float = 0.4,
        max_tokens: int = 8192,
    ) -> None:
        self._provider = provider
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens

    def _complete[O: BaseModel](
        self,
        *,
        system: str,
        user: str,
        schema: type[O],
        examples: tuple[PromptExample, ...] = (),
    ) -> Completion[O]:
        prompt = Prompt(system=system, user=user, examples=examples)
        return self._provider.structured(
            prompt=prompt,
            schema=schema,
            model=self._model,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )
