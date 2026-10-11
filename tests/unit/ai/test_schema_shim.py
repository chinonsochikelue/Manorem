"""``to_gemini_schema`` -- down-conversion to Gemini's JSON Schema subset.

The converter removes the constructs Gemini rejects while preserving the shape a
valid answer depends on. Purpose-built models exercise each transform in
isolation ($ref inlining, const->enum, nullable collapse, oneOf->anyOf,
prefixItems->items), plus the one keyword dropped for a reason of its own, and
the IR models stand in as the real-world stress test that the forbidden
constructs are gone *and* that nothing was emptied on the way out.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from manorem_ai import to_gemini_schema
from manorem_ai.agents.models import StoryOutline, VisualPlan
from manorem_ir import Scene

# Schema *keywords* Gemini rejects. Field names may legitimately collide with some
# JSON Schema words (StoryOutline has a field literally named ``title``), so the
# recursive check targets only keywords that never appear as a field name here.
_FORBIDDEN_KEYWORDS = frozenset(
    {"$ref", "$defs", "allOf", "oneOf", "prefixItems", "discriminator", "const"}
)


class _Leaf(BaseModel):
    kind: Literal["leaf"]
    n: int


class _Root(BaseModel):
    leaf: _Leaf
    note: str | None = None


class _Circle(BaseModel):
    kind: Literal["circle"]
    r: int


class _Square(BaseModel):
    kind: Literal["square"]
    side: int


class _Unioned(BaseModel):
    """A discriminated union: Pydantic's only ``oneOf`` + ``discriminator`` emitter."""

    shape: Annotated[_Circle | _Square, Field(discriminator="kind")]


class _Ranged(BaseModel):
    """A fixed-length tuple: Pydantic's only ``prefixItems`` emitter."""

    span: tuple[float, float, float]


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


def test_discriminated_union_survives_as_an_anyof() -> None:
    # Pydantic emits ``oneOf`` + ``discriminator`` for a tagged union, and the
    # allowlist used to drop both before anything could rewrite the ``oneOf`` --
    # leaving the field ``{}``, which means "any" to JSON Schema and is *invalid*
    # to Gemini, so the whole request was rejected. The union must be re-spelled,
    # never emptied.
    shape = to_gemini_schema(_Unioned)["properties"]["shape"]
    assert shape != {}
    assert "oneOf" not in shape
    assert "discriminator" not in shape
    members = shape["anyOf"]
    assert len(members) == 2
    kinds = {member["properties"]["kind"]["enum"][0] for member in members}
    assert kinds == {"circle", "square"}


def test_no_field_degrades_to_an_empty_schema() -> None:
    # One of two failure modes that do not announce themselves locally: an empty
    # schema is well-formed JSON Schema (meaning "any"), so nothing here can
    # complain -- only the provider's request validator sees the problem.
    for model in (StoryOutline, VisualPlan, Scene, _Unioned, _Ranged):
        for node in _walk(to_gemini_schema(model)):
            assert node, f"{model.__name__} produced an empty schema node"


def test_every_array_keeps_its_items() -> None:
    # The other silent failure: Gemini requires ``items`` on any array, and
    # Pydantic spells a fixed tuple with ``prefixItems`` -- a keyword outside the
    # subset that the allowlist dropped, leaving ``type: "array"`` bare.
    for model in (StoryOutline, VisualPlan, Scene, _Ranged):
        for node in _walk(to_gemini_schema(model)):
            if node.get("type") == "array":
                assert "items" in node, f"{model.__name__}: array with {sorted(node)}"


def test_prefix_items_become_items() -> None:
    span = to_gemini_schema(_Ranged)["properties"]["span"]
    assert span["type"] == "array"
    assert "prefixItems" not in span
    assert span["items"] == {"type": "number"}
    # The lower bound survives; the upper one is dropped with every other
    # ``maxItems`` (see below), so Pydantic's own tuple check is what rejects a
    # fourth element.
    assert span["minItems"] == 3
    assert "maxItems" not in span


def test_multi_property_objects_carry_an_empty_property_ordering() -> None:
    # The SDK injects a full ``property_ordering`` into every multi-property
    # object on the ``response_schema`` path, and the backend answers that shape
    # with a bare 400 on schemas the size of Scene. Seeding the documented
    # camelCase spelling empty makes the SDK skip its injection, and the backend
    # reads the vacuous list as a no-op -- measured live on gemini-3.8-flash
    # (and gated on gemini-3.1-flash-lite) for the full Scene schema.
    for model in (StoryOutline, VisualPlan, Scene):
        for node in _walk(to_gemini_schema(model)):
            properties = node.get("properties")
            if isinstance(properties, dict) and len(properties) > 1:
                assert node["propertyOrdering"] == [], f"{model.__name__}: ordering not seeded"


def test_array_size_bounds_are_dropped() -> None:
    # ``maxItems`` is the one keyword Gemini accepts in general but still
    # rejects these schemas for: it prices the bound against the schema it
    # repeats and 400s the whole request with no field named, so the failure
    # cannot be observed locally. Keeping only the cheap caps did not help --
    # Scene failed with seven of them -- so the shim drops every one. Nothing
    # is lost: each came from ``Field(max_length=...)`` on the IR model, which
    # validates the identical bound on the answer.
    for model in (StoryOutline, VisualPlan, Scene, _Ranged, _Unioned, _Root):
        for node in _walk(to_gemini_schema(model)):
            assert "maxItems" not in node, f"{model.__name__}: maxItems survived"
