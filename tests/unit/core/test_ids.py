"""Id rules. ``slugify`` normalizes machine-generated names; it never repairs
an author-supplied id, since that is semantic damage the author must see."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from manorem_core import Slug, is_valid_slug, new_run_id, slugify, validate_slug


class Model(BaseModel):
    id: Slug


class TestSlugValidation:
    @pytest.mark.parametrize("value", ["a", "satellite_1", "gps_trilateration", "x" * 63])
    def test_accepts_valid_slugs(self, value: str) -> None:
        assert validate_slug(value) == value
        assert is_valid_slug(value)

    @pytest.mark.parametrize(
        ("value", "reason"),
        [
            ("", "empty"),
            ("1sat", "leading digit"),
            ("_sat", "leading underscore"),
            ("Satellite", "uppercase"),
            ("sat-1", "hyphen"),
            ("sat 1", "space"),
            ("sat.1", "dot"),
            ("sat/1", "slash would corrupt a JSON Pointer"),
            ("x" * 64, "too long"),
        ],
    )
    def test_rejects_invalid_slugs(self, value: str, reason: str) -> None:
        assert not is_valid_slug(value)
        with pytest.raises(ValueError, match="invalid id"):
            validate_slug(value)

    def test_works_as_a_pydantic_annotation(self) -> None:
        assert Model(id="satellite_1").id == "satellite_1"
        with pytest.raises(ValidationError):
            Model(id="Satellite 1")


class TestSlugify:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Satellite 1", "satellite_1"),
            ("  GPS Trilateration  ", "gps_trilateration"),
            ("a---b", "a_b"),
            ("Hello, World!", "hello_world"),
            ("1st satellite", "x_1st_satellite"),
            ("", "item"),
            ("!!!", "item"),
        ],
    )
    def test_produces_valid_slugs(self, text: str, expected: str) -> None:
        result = slugify(text)
        assert result == expected
        assert is_valid_slug(result)

    def test_truncates_long_input_to_a_valid_slug(self) -> None:
        assert is_valid_slug(slugify("word " * 100))


def test_new_run_id_is_unique_and_prefixed() -> None:
    ids = {new_run_id("render") for _ in range(100)}
    assert len(ids) == 100
    assert all(i.startswith("render_") for i in ids)
