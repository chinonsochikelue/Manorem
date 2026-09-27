"""Content addressing underpins versioning, caching and determinism checks."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from manorem_core import canonical_bytes, canonical_json, sha256_of, short_digest


class Sample(BaseModel):
    b: int
    a: str


class TestCanonicalJson:
    def test_sorts_keys_regardless_of_insertion_order(self) -> None:
        assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1})

    def test_omits_incidental_whitespace(self) -> None:
        assert canonical_json({"a": 1, "b": [1, 2]}) == '{"a":1,"b":[1,2]}'

    def test_serializes_pydantic_models(self) -> None:
        assert canonical_json(Sample(b=1, a="x")) == '{"a":"x","b":1}'

    def test_preserves_unicode(self) -> None:
        assert canonical_json({"k": "café"}) == '{"k":"café"}'

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
    def test_rejects_non_finite_floats(self, bad: float) -> None:
        # NaN would serialize to invalid JSON and silently poison a content address.
        with pytest.raises(ValueError, match="Out of range"):
            canonical_json({"v": bad})

    def test_bytes_are_utf8_of_text(self) -> None:
        value = {"k": "café"}
        assert canonical_bytes(value) == canonical_json(value).encode("utf-8")


class TestSha256Of:
    def test_is_stable_across_key_order(self) -> None:
        assert sha256_of({"a": 1, "b": 2}) == sha256_of({"b": 2, "a": 1})

    def test_differs_on_content_change(self) -> None:
        assert sha256_of({"a": 1}) != sha256_of({"a": 2})

    def test_model_and_equivalent_dict_agree(self) -> None:
        assert sha256_of(Sample(b=1, a="x")) == sha256_of({"a": "x", "b": 1})

    def test_returns_full_hex_digest(self) -> None:
        digest = sha256_of({"a": 1})
        assert len(digest) == 64
        assert set(digest) <= set("0123456789abcdef")

    def test_distinguishes_types(self) -> None:
        # "1" and 1 must not collide, or artifacts of different kinds could dedupe.
        assert sha256_of({"a": 1}) != sha256_of({"a": "1"})


def test_short_digest_truncates_without_changing_identity() -> None:
    digest = sha256_of({"a": 1})
    assert short_digest(digest) == digest[:12]
    assert short_digest(digest, 8) == digest[:8]
