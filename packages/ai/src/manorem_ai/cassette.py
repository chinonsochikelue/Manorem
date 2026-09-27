"""Offline providers: a hand-written stub and a record/replay cassette.

Neither touches the network, which is what makes every test deterministic. The
:class:`StubProvider` answers from a callback the test supplies -- ideal for
exercising one agent against one crafted response. The :class:`CassetteProvider`
answers from disk, keyed by the exact (prompt, schema, model) that produced the
recording, so an end-to-end run replays byte-for-byte; pointed at a real backend
with recording on, it captures fresh answers to commit.

The key is the whole contract. Two runs that assemble the same prompt against the
same schema and model resolve to the same cassette; change any of the three and the
lookup misses rather than replaying an answer that no longer fits the request.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import cast

from pydantic import BaseModel

from manorem_ai.provider import (
    Completion,
    LLMProvider,
    Prompt,
    ProviderError,
    Usage,
    prompt_cache_key,
)

__all__ = ["CassetteProvider", "StubProvider"]


class StubProvider:
    """A provider that answers from a callback. For unit tests, not for replay.

    The callback receives the requested schema and the prompt and returns an
    instance of that schema. A mismatch is a :class:`ProviderError`, so a test that
    wires the wrong fixture fails loudly rather than smuggling a wrong-typed value
    past the boundary.
    """

    name = "stub"

    def __init__(self, handler: Callable[[Prompt, type[BaseModel]], BaseModel]) -> None:
        self._handler = handler

    @classmethod
    def sequence(cls, values: object) -> StubProvider:
        """Answer successive calls from an iterable of prepared instances, in order.

        Convenient when a test drives several stages: the responses are consumed
        one per call regardless of schema, and each is type-checked against the
        schema it is handed to.
        """
        iterator: Iterator[BaseModel] = iter(cast("list[BaseModel]", values))

        def handler(_prompt: Prompt, _schema: type[BaseModel]) -> BaseModel:
            try:
                return next(iterator)
            except StopIteration:
                raise ProviderError("stub provider ran out of prepared responses") from None

        return cls(handler)

    def structured[T: BaseModel](
        self,
        *,
        prompt: Prompt,
        schema: type[T],
        model: str,
        temperature: float,  # noqa: ARG002 - a stub ignores sampling; the seam keeps the signature
        max_tokens: int,  # noqa: ARG002
    ) -> Completion[T]:
        value = self._handler(prompt, schema)
        if not isinstance(value, schema):
            raise ProviderError(f"stub returned {type(value).__name__}, expected {schema.__name__}")
        return Completion(value=value, model=model, raw_id="stub")


class CassetteProvider:
    """Record/replay against a directory of JSON cassettes keyed by request hash.

    In replay mode a missing cassette is an error, not a live call: a test must
    never silently reach the network. In record mode every call goes to ``inner``
    and the validated result is written back, so refreshing the fixtures is one
    environment variable and one run.
    """

    name = "cassette"

    def __init__(
        self,
        directory: Path,
        *,
        record: bool = False,
        inner: LLMProvider | None = None,
    ) -> None:
        if record and inner is None:
            raise ProviderError("recording a cassette needs an inner provider to record from")
        self._dir = directory
        self._record = record
        self._inner = inner

    def _path(self, key: str) -> Path:
        return self._dir / f"{key}.json"

    def structured[T: BaseModel](
        self,
        *,
        prompt: Prompt,
        schema: type[T],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> Completion[T]:
        key = prompt_cache_key(prompt=prompt, schema=schema, model=model)
        path = self._path(key)

        if not self._record:
            if not path.exists():
                raise ProviderError(
                    f"no cassette for {schema.__name__} at {path.name}; "
                    "record with MANOREM_AI_RECORD=1 or check the prompt has not drifted"
                )
            payload = json.loads(path.read_text(encoding="utf-8"))
            value = schema.model_validate(payload["output"])
            return Completion(value=value, model=payload.get("model", model), raw_id=key)

        assert self._inner is not None  # guaranteed by __init__
        completion = self._inner.structured(
            prompt=prompt,
            schema=schema,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        self._dir.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "schema": schema.__name__,
                    "model": completion.model,
                    "output": completion.value.model_dump(mode="json"),
                },
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return Completion(value=completion.value, model=completion.model, usage=Usage(), raw_id=key)
