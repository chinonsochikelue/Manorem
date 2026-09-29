"""Key-pool failover: round-robin on 429, immediate propagate on other errors."""

from __future__ import annotations

from typing import Any

import pytest

from manorem_ai import Completion, LLMProvider, Prompt, ProviderError, RateLimitError
from manorem_ai.keypool import KeyPoolProvider
from tests.support.ai_builders import outline

_SCHEMA = type(outline())


def test_empty_pool_is_rejected() -> None:
    def _unused(**_: Any) -> LLMProvider:
        raise AssertionError("the factory must not be called for an empty pool")

    with pytest.raises(ValueError, match="non-empty"):
        KeyPoolProvider(provider_factory=_unused, pool=[])


def test_rate_limit_failover_to_next_key() -> None:
    """A 429 on key 0 must trigger a retry on key 1, then succeed."""

    class StubBackend:
        name = "stub"

        def __init__(self, key_index: int) -> None:
            self._idx = key_index

        def structured(self, **_: Any) -> Completion[Any]:
            if self._idx == 0:
                raise RateLimitError("429 on key 1")
            return Completion(value=outline(), model="m")

    counter = [0]

    def factory(*_: Any, **__: Any) -> StubBackend:
        idx = counter[0]
        counter[0] += 1
        return StubBackend(idx)

    pool = KeyPoolProvider(provider_factory=factory, pool=[{"api_key": "k1"}, {"api_key": "k2"}])
    result = pool.structured(
        prompt=Prompt(system="s", user="u"),
        schema=_SCHEMA,
        model="m",
        temperature=0.0,
        max_tokens=8,
    )
    assert isinstance(result, Completion)
    # Key 0 failed with 429, key 1 succeeded.
    assert counter[0] == 2


def test_non_rate_limit_error_propagates_immediately() -> None:
    """A non-429 ProviderError must not trigger failover."""

    class FailingBackend:
        name = "failing"

        def __init__(self, key_index: int) -> None:
            self._idx = key_index

        def structured(self, **_: Any) -> Completion[Any]:
            raise ProviderError("bad schema, not a rate limit")

    counter = [0]

    def factory(*_: Any, **__: Any) -> FailingBackend:
        idx = counter[0]
        counter[0] += 1
        return FailingBackend(idx)

    pool = KeyPoolProvider(
        provider_factory=factory,
        pool=[{"api_key": "k1"}, {"api_key": "k2"}, {"api_key": "k3"}],
    )
    with pytest.raises(ProviderError, match="bad schema"):
        pool.structured(
            prompt=Prompt(system="s", user="u"),
            schema=_SCHEMA,
            model="m",
            temperature=0.0,
            max_tokens=8,
        )
    # Only one attempt, no failover.
    assert counter[0] == 1


def test_all_keys_rate_limited_raises_last_error() -> None:
    """If every key returns 429, the last RateLimitError is raised."""

    class Always429:
        name = "429"

        def __init__(self, _key_index: int) -> None:
            pass

        def structured(self, **_: Any) -> Completion[Any]:
            raise RateLimitError("always throttled")

    counter = [0]

    def factory(*_: Any, **__: Any) -> Always429:
        idx = counter[0]
        counter[0] += 1
        return Always429(idx)

    pool = KeyPoolProvider(provider_factory=factory, pool=[{"api_key": "k1"}, {"api_key": "k2"}])
    with pytest.raises(RateLimitError, match="always throttled"):
        pool.structured(
            prompt=Prompt(system="s", user="u"),
            schema=_SCHEMA,
            model="m",
            temperature=0.0,
            max_tokens=8,
        )
