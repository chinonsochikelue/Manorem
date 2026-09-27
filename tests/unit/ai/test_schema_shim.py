"""``to_gemini_schema`` -- down-conversion to Gemini's JSON Schema subset.

The converter removes the constructs Gemini rejects while preserving the shape a
valid answer depends on. A pair of purpose-built models exercises each transform
in isolation ($ref inlining, const->enum, nullable collapse), and the IR models
stand in as the real-world stress test that the forbidden constructs are gone.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from manorem_ai import to_gemini_schema
from manorem_ai.agents.models import StoryOutline, VisualPlan
from manorem_ir import Scene

# Schema *keywords* Gemini rejects. Field names may legitimately collide with some
# JSON Schema words (StoryOutline has a field literally named ``title``), so the
# recursive check targets only keywords that never appear as a field name here.
_FORBIDDEN_KEYWORDS = frozenset({"$ref", "$defs", "allOf", "discriminator", "const"})


class _Leaf(BaseModel):
    kind: Literal["leaf"]
    n: int


class _Root(BaseModel):
    leaf: _Leaf
    note: str | None = None


def _walk(node: Any) -> list[dict[str, Any]]:
    """Every dict node in the schema tree, root first."""
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        found.append(node)
        for value in node.values():
            found.extend(_walk(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_walk(item))
    return found


def test_ref_is_inlined_and_defs_dropped() -> None:
    schema = to_gemini_schema(_Root)
    assert "$defs" not in schema
    leaf = schema["properties"]["leaf"]
    # The referenced model is expanded in place, not left as a $ref.
    assert leaf["type"] == "object"
    assert "n" in leaf["properties"]


def test_const_becomes_single_value_enum() -> None:
    schema = to_gemini_schema(_Root)
    kind = schema["properties"]["leaf"]["properties"]["kind"]
    assert "const" not in kind
    assert kind["enum"] == ["leaf"]


def test_optional_collapses_to_nullable() -> None:
    schema = to_gemini_schema(_Root)
    note = schema["properties"]["note"]
    assert note.get("nullable") is True
    assert "anyOf" not in note


def test_no_forbidden_keywords_in_ir_schemas() -> None:
    for model in (StoryOutline, VisualPlan, Scene):
        schema = to_gemini_schema(model)
        for node in _walk(schema):
            offenders = node.keys() & _FORBIDDEN_KEYWORDS
            assert not offenders, f"{model.__name__}: {offenders}"


def test_required_and_properties_survive() -> None:
    schema = to_gemini_schema(VisualPlan)
    assert schema["type"] == "object"
    assert {"beat_id", "why", "how"} <= set(schema["properties"])
    assert set(schema["required"]) >= {"beat_id", "skills", "what", "why", "how"}
    # ``persist`` has a default, so a valid answer need not supply it.
    assert "persist" not in schema["required"]
