"""Key-pooling wrapper: round-robin across provider keys, failover on 429.

A thin decorator over any :class:`~manorem_ai.provider.LLMProvider` that is itself
a network backend (``GeminiProvider`` / ``AnthropicProvider`` / ``OpenAIProvider``).
It is *not* itself a backend -- it holds no model logic, only a list of
``ProviderError``-raising callables and the failover policy. The live provider
is constructed from a single key from the pool on each attempt, so a rate-limited
key is swapped for the next key in the same round, then the same on a retry.

The SDK client (if any) is built lazily inside the wrapped provider; ``KeyPoolProvider``
only holds api keys and base URLs and hands them to the wrapped provider factory on
each attempt. This keeps the pool out of the import graph of the real backends --
nothing in ``provider.py`` or the cassette ever references it -- and makes the
failover boundary explicit: ``RateLimitError`` retries, any other
``ProviderError`` propagates immediately rather than burning the rest of the keys.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from manorem_ai.provider import (
    Completion,
    LLMProvider,
    Prompt,
    ProviderError,
    RateLimitError,
)

__all__ = ["KeyPoolProvider"]

log = logging.getLogger(__name__)


class KeyPoolProvider:
    """Failover wrapper around an ordered pool of api-key entries.

    Each pool entry is a ``dict`` of kwargs for the provider factory -- typically
    ``{"api_key": "..."}`` and optionally ``{"base_url": "..."}``. On each call the
    pool is rotated and the next fresh provider is tried. A ``RateLimitError``
    (HTTP 429) from one key triggers a retry on the next; any other
    ``ProviderError`` is raised immediately so a genuine bug or schema mismatch
    is not masked by burning through keys.

    The pool cycles round-robin by default. ``cooldown_after_rate_limit`` marks a
    key as temporarily unusable for ``cooldown`` attempts after it trips a 429, so
    a hot key is not immediately retried once the cycle wraps. This is a blunt
    instrument -- production would read ``Retry-After`` / token buckets -- but it
    prevents a fast loop from hammering one key while the rest sit idle.
    """

    name = "keypool"

    def __init__(
        self,
        *,
        provider_factory: Callable[..., LLMProvider],
        pool: list[dict[str, Any]],
        max_retries: int = 3,
        cooldown_after_rate_limit: int = 2,
    ) -> None:
        if not pool:
            raise ValueError("KeyPoolProvider requires a non-empty pool of keys")
        self._factory = provider_factory
        self._pool = list(pool)
        self._max_retries = max_retries
        self._cooldown = cooldown_after_rate_limit
        self._fail_counts: dict[int, int] = defaultdict(int)

    def _live_keys(self) -> list[int]:
        """Indices of pool entries not currently in cooldown."""
        return [i for i in range(len(self._pool)) if self._fail_counts.get(i, 0) <= 0]

    def _pick(self, used: list[int]) -> int:
        """Choose the next key index, round-robin over the live set."""
        live = self._live_keys()
        if not live:
            # Everyone is in cooldown: reset and retry. A real 429 storm should
            # surface as a ProviderError, not an infinite loop.
            log.warning("all keys in cooldown; resetting fail counters")
            self._fail_counts.clear()
            live = self._live_keys() or list(range(len(self._pool)))
        remaining = [i for i in live if i not in used]
        if remaining:
            return remaining[0]
        # Wrapped the whole pool without success.
        return live[len(used) % len(live)]

    def structured[T: BaseModel](
        self,
        *,
        prompt: Prompt,
        schema: type[T],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> Completion[T]:
        used: list[int] = []
        last_error: ProviderError | None = None
        for attempt in range(self._max_retries):
            idx = self._pick(used)
            used.append(idx)
            entry = self._pool[idx]
            provider = self._factory(**entry)
            log.debug("keypool attempt %d using key index %d (%s)", attempt + 1, idx, provider.name)
            try:
                return provider.structured(
                    prompt=prompt,
                    schema=schema,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except RateLimitError as exc:
                last_error = exc
                self._fail_counts[idx] = self._fail_counts.get(idx, 0) + self._cooldown
                log.warning("key index %d rate-limited; trying next key", idx)
                continue
            except ProviderError:
                # Non-rate-limit provider errors (transport failure, validation
                # failure, missing extra) propagate immediately: they are not
                # key-specific, so retrying the same request on another key
                # cannot help and only wastes rate budget.
                raise
        # Exhausted all retries on rate limits.
        if last_error is not None:
            raise last_error
        raise ProviderError("keypool exhausted without a provider error")  # pragma: no cover
