"""The provider seam: stub, cassette, and the request cache key.

The stub answers from a callback and must reject a wrong-typed answer at the
boundary. The cassette keys recordings on (prompt, schema, model) and must miss
-- never replay a stale answer -- when any of the three changes. The cache key
is the contract both rely on, so its stability is tested directly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from manorem_ai import (
    Completion,
    Prompt,
    ProviderError,
    StubProvider,
    prompt_cache_key,
)
from manorem_ai.agents.models import Script, StoryOutline
from manorem_ai.cassette import CassetteProvider
from tests.support.ai_builders import outline, script

_PROMPT = Prompt(system="be a story agent", user="the idea")


def _stub_returning(value: object) -> StubProvider:
    return StubProvider(lambda _p, _s: value)  # type: ignore[arg-type, return-value]


def test_stub_returns_the_prepared_value() -> None:
    provider = _stub_returning(outline())
    completion = provider.structured(
        prompt=_PROMPT, schema=StoryOutline, model="m", temperature=0.0, max_tokens=8
    )
    assert isinstance(completion, Completion)
    assert completion.value.arc == "question_led"


def test_stub_rejects_wrong_type() -> None:
    provider = _stub_returning(script())  # a Script where a StoryOutline is asked
    with pytest.raises(ProviderError):
        provider.structured(
            prompt=_PROMPT, schema=StoryOutline, model="m", temperature=0.0, max_tokens=8
        )


def test_stub_sequence_consumes_in_order() -> None:
    provider = StubProvider.sequence([outline(), script()])
    first = provider.structured(
        prompt=_PROMPT, schema=StoryOutline, model="m", temperature=0.0, max_tokens=8
    )
    second = provider.structured(
        prompt=_PROMPT, schema=Script, model="m", temperature=0.0, max_tokens=8
    )
    assert isinstance(first.value, StoryOutline)
    assert isinstance(second.value, Script)


def test_stub_sequence_exhaustion_is_an_error() -> None:
    provider = StubProvider.sequence([outline()])
    provider.structured(
        prompt=_PROMPT, schema=StoryOutline, model="m", temperature=0.0, max_tokens=8
    )
    with pytest.raises(ProviderError):
        provider.structured(
            prompt=_PROMPT, schema=StoryOutline, model="m", temperature=0.0, max_tokens=8
        )


def test_cache_key_is_stable_and_schema_sensitive() -> None:
    key_a = prompt_cache_key(prompt=_PROMPT, schema=StoryOutline, model="m")
    key_b = prompt_cache_key(prompt=_PROMPT, schema=StoryOutline, model="m")
    key_other_schema = prompt_cache_key(prompt=_PROMPT, schema=Script, model="m")
    key_other_model = prompt_cache_key(prompt=_PROMPT, schema=StoryOutline, model="n")
    assert key_a == key_b
    assert key_a != key_other_schema
    assert key_a != key_other_model


def test_cassette_missing_recording_is_an_error(tmp_path: Path) -> None:
    provider = CassetteProvider(tmp_path)
    with pytest.raises(ProviderError):
        provider.structured(
            prompt=_PROMPT, schema=StoryOutline, model="m", temperature=0.0, max_tokens=8
        )


def test_cassette_records_then_replays(tmp_path: Path) -> None:
    inner = StubProvider.sequence([outline()])
    recorder = CassetteProvider(tmp_path, record=True, inner=inner)
    recorded = recorder.structured(
        prompt=_PROMPT, schema=StoryOutline, model="m", temperature=0.0, max_tokens=8
    )
    replayer = CassetteProvider(tmp_path)
    replayed = replayer.structured(
        prompt=_PROMPT, schema=StoryOutline, model="m", temperature=0.0, max_tokens=8
    )
    assert replayed.value == recorded.value
