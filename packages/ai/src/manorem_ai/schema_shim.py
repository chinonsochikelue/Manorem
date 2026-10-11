"""Down-convert a Pydantic JSON Schema to the subset Gemini accepts.

Gemini's structured-output schema is a *subset* of JSON Schema, and the docs warn
that a deeply nested or ``$ref``-heavy schema may be rejected outright. Pydantic,
meanwhile, emits exactly that: ``$defs`` with ``$ref`` back-links, ``allOf``
wrappers, ``discriminator`` maps, ``const`` for literal fields, and ``title`` and
``additionalProperties`` on every object. This module rewrites all of it into the
flat, self-contained shape Gemini takes.

Four transforms carry the weight:

* **Inlining.** Every ``$ref`` is resolved against ``$defs`` and expanded in
  place, so the result stands alone with no back-references. A cycle -- which the
  IR does not contain, but which the converter must not loop on -- is broken with
  a bare ``object``, as is a ref with nothing of that name in scope: ``{}`` means
  "any" to JSON Schema but is *invalid* to Gemini, so one of those rejects the
  whole request rather than the one field it belongs to.
* **Two rejects are rewritten instead of dropped.** Pydantic spells a
  discriminated union (a ``Literal`` tag plus a ``mode`` sibling) as
  ``oneOf: [...]`` beside a ``discriminator`` map, and a fixed-length tuple as
  ``prefixItems: [...]``. Neither keyword exists in Gemini's subset, but neither
  can simply be dropped: an emptied property is valid JSON Schema meaning "any"
  and is rejected by Gemini, and an array left without ``items`` is rejected
  too. The tuple is re-spelled as ``items``; the union is *flattened* (next
  point), and ``discriminator`` itself is still discarded. Both bugs shared a
  shape worth naming: they looked correct locally, because nothing local
  validates against a provider, and only failed at the request boundary.
* **A tagged union of objects is fused into one object.** A ``oneOf``/``anyOf``
  whose branches are all objects sharing a single-value tag (``SceneObject.props``
  is 21 such branches, keyed by ``kind``) is not kept as a union: measured on
  ``gemini-3.8-flash``, a *required* many-branch union is answered with a
  degenerate member -- the wrong tag and none of its fields -- so every object
  fails validation and the scene is unbuildable, even though the request itself
  is accepted. In its place goes a single object whose tag is an ``enum`` over
  every branch, whose other fields are merged and left optional, and whose only
  required field is the tag -- a shape the sampler fills correctly. The per-branch
  requirements are not lost: Pydantic re-checks the real discriminated union on
  the answer, exactly as it re-checks the array bounds the shim drops.
* **``const`` becomes a one-value ``enum``.** Discriminated-union tags render as
  ``const``; Gemini has no ``const`` but does have ``enum``, and a single-element
  enum means the same thing.
* **``anyOf`` with a null branch becomes ``nullable``.** Pydantic spells
  ``T | None`` as ``anyOf: [T, {"type": "null"}]``; Gemini spells it as ``T`` with
  ``nullable: true``. Collapsing it keeps optional fields legible rather than
  turning every one into a two-way union.

One keyword is dropped on purpose even though Gemini accepts it in general:

* **``maxItems``.** Gemini prices an array bound against the schema it repeats
  and rejects the entire request when the implied answer grows too large --
  answered with a bare ``400 INVALID_ARGUMENT`` naming no field, so nothing
  local can see it coming. The price is not a function of the number alone:
  ``maxItems: 50`` over nine properties is refused while ``maxItems: 100`` over
  two is accepted, and ``Scene`` still fails when only the cheap caps are kept
  beside an otherwise stripped schema. Dropping all of them is the one shape
  measured to be accepted, and nothing is lost by it: Pydantic emits
  ``maxItems`` only from ``Field(max_length=...)`` on the IR model, which
  validates the identical bound on the answer whether or not the sampler was
  told it.

And one keyword is *seeded* for the opposite reason:

* **``propertyOrdering: []``.** The SDK injects a full ``property_ordering``
  into every multi-property object on the ``response_schema`` path, and the
  backend answers that shape -- full lists in either spelling -- with a bare
  ``400`` on schemas the size of ``Scene``. Seeding the documented camelCase
  spelling *empty* makes the SDK skip its injection, and the backend treats the
  vacuous list as a no-op: the full ``Scene`` schema with 58 empty orderings is
  accepted where the injected full ones are refused. Measured live on
  ``gemini-3.8-flash`` (and gated on ``gemini-3.1-flash-lite``); the round-trip
  test pins the seeding.

Everything else outside the allowlist is dropped. The round-trip test asserts
the result is free of the constructs Gemini rejects, that no field was emptied
or left bare on the way, and that the fields, enums and requiredness a valid
answer depends on survived the trip.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

__all__ = ["to_gemini_schema"]

#: Keys Gemini's schema understands. Anything else is incidental to Pydantic's
#: rendering (``title``), a validation nicety Gemini ignores (``additionalProperties``),
#: a construct it rejects outright (``$ref``, ``discriminator``), or -- for
#: ``maxItems`` -- one it prices into rejecting the whole request; all are dropped.
_ALLOWED_KEYS: frozenset[str] = frozenset(
    {
        "type",
        "format",
        "description",
        "nullable",
        "enum",
        "items",
        "properties",
        "required",
        "anyOf",
        "minimum",
        "maximum",
        "minItems",
        "minLength",
        "maxLength",
    }
)

_JsonObj = dict[str, Any]


def to_gemini_schema(model: type[BaseModel]) -> _JsonObj:
    """Convert a model's JSON Schema to Gemini's supported subset."""
    root = model.model_json_schema()
    defs: _JsonObj = root.get("$defs", {})
    return _convert(root, defs, ())


def _ref_name(ref: str) -> str:
    """``#/$defs/Foo`` -> ``Foo``. The only ref shape Pydantic emits."""
    return ref.rsplit("/", 1)[-1]


def _convert(node: _JsonObj, defs: _JsonObj, stack: tuple[str, ...]) -> _JsonObj:
    """Rewrite one schema node into Gemini's subset, inlining as it goes."""
    if "$ref" in node:
        name = _ref_name(node["$ref"])
        if name in stack:
            # A recursive definition. The IR has none, but a break beats a loop.
            return {"type": "object"}
        target = defs.get(name)
        if not target:
            # Nothing of that name is in scope. ``{}`` means "any" to JSON Schema
            # but is invalid to Gemini, so fall back to a type it accepts.
            return {"type": "object"}
        merged = _convert(target, defs, (*stack, name))
        # A ref can carry a sibling description ("field doc"); keep it.
        if "description" in node and "description" not in merged:
            merged["description"] = node["description"]
        return merged

    if "allOf" in node:
        # Pydantic wraps a single ref plus metadata in allOf; merge the members.
        out: _JsonObj = {}
        for member in node["allOf"]:
            out.update(_convert(member, defs, stack))
        for key in ("description", "nullable"):
            if key in node:
                out[key] = node[key]
        return out

    return _convert_plain(node, defs, stack)


def _convert_plain(node: _JsonObj, defs: _JsonObj, stack: tuple[str, ...]) -> _JsonObj:
    out: _JsonObj = {}
    for key, value in node.items():
        if key == "const":
            out["enum"] = [value]
            continue
        if key == "oneOf":
            # Rewritten before the allowlist gate, not after: Pydantic spells a
            # discriminated union (a ``Literal`` tag plus a ``mode`` sibling) as
            # ``oneOf: [...]`` with a ``discriminator`` sibling, and Gemini takes
            # only ``anyOf``. Routing it through the union converter the same way
            # ``anyOf`` is routed is what keeps the field from being emptied --
            # an emptied property is a *valid* JSON Schema (meaning "any") that
            # Gemini rejects outright, taking the whole request with it.
            out.update(_convert_any_of(value, defs, stack))
            continue
        if key == "prefixItems":
            # JSON Schema 2020-12 spells a fixed-length tuple as ``prefixItems``;
            # Gemini's subset has no such keyword, and it *requires* ``items`` on
            # every array -- so dropping it as incidental left ``type: "array"``
            # bare, a 400 on the whole request. ``items`` is a single schema, so a
            # tuple is only expressible when its members agree, which is the only
            # shape the IR has (``tuple[float, float, float]`` ranges). A tuple
            # that disagrees keeps the first member rather than failing a build
            # over a keyword the target cannot represent.
            members = [_convert(m, defs, stack) for m in value]
            if members:
                out["items"] = members[0]
            continue
        if key not in _ALLOWED_KEYS:
            continue
        if key == "properties":
            out["properties"] = {k: _convert(v, defs, stack) for k, v in value.items()}
        elif key == "items":
            out["items"] = _convert(value, defs, stack)
        elif key == "anyOf":
            out.update(_convert_any_of(value, defs, stack))
        else:
            out[key] = value
    properties = out.get("properties")
    if isinstance(properties, dict) and len(properties) > 1 and "propertyOrdering" not in out:
        # Seed the documented spelling empty so the SDK skips injecting its own
        # full list over it (see the ``propertyOrdering`` note up top). The
        # backend reads the vacuous list as a no-op; a full one 400s the request.
        out["propertyOrdering"] = []
    return out


def _convert_any_of(members: list[_JsonObj], defs: _JsonObj, stack: tuple[str, ...]) -> _JsonObj:
    """Collapse ``T | None`` to nullable; flatten a tagged object union; else ``anyOf``."""
    non_null = [m for m in members if m.get("type") != "null"]
    nullable = len(non_null) != len(members)

    if len(non_null) == 1:
        collapsed = _convert(non_null[0], defs, stack)
        if nullable:
            collapsed["nullable"] = True
        return collapsed

    converted = [_convert(m, defs, stack) for m in non_null]
    flattened = _flatten_tagged_union(converted)
    if flattened is not None:
        if nullable:
            flattened["nullable"] = True
        return flattened

    out: _JsonObj = {"anyOf": converted}
    if nullable:
        out["nullable"] = True
    return out


def _flatten_tagged_union(members: list[_JsonObj]) -> _JsonObj | None:
    """Fuse a discriminated union of objects into one object, or ``None`` if it is not one.

    Measured on ``gemini-3.8-flash``: a required field typed as a many-branch
    ``anyOf`` (``SceneObject.props`` is 21 branches) is answered with a degenerate
    member -- the wrong discriminator and none of its required fields -- so every
    object fails validation and the scene is unbuildable. One object the sampler
    *can* fill replaces it: the discriminator becomes an ``enum`` over every tag,
    the other fields are merged and left optional, and only the discriminator is
    required. The per-branch field requirements are not lost -- Pydantic re-checks
    the identical discriminated union on the answer, exactly as it does for the
    array bounds the shim also drops.
    """
    if not members or not all(
        m.get("type") == "object" and isinstance(m.get("properties"), dict) for m in members
    ):
        return None

    common = set(members[0]["properties"])
    for member in members[1:]:
        common &= set(member["properties"])
    discriminator = next(
        (
            key
            for key in sorted(common)
            if all(len(m["properties"][key].get("enum", [])) == 1 for m in members)
        ),
        None,
    )
    if discriminator is None:
        return None

    merged: _JsonObj = {}
    tags: list[Any] = []
    tag_type: str | None = None
    for member in members:
        for key, sub in member["properties"].items():
            if key == discriminator:
                tags.extend(sub["enum"])
                tag_type = tag_type or sub.get("type")
            elif key not in merged:
                merged[key] = sub

    tag_schema: _JsonObj = {"enum": list(dict.fromkeys(tags))}
    if tag_type is not None:
        tag_schema["type"] = tag_type
    merged[discriminator] = tag_schema

    out: _JsonObj = {"type": "object", "properties": merged, "required": [discriminator]}
    if len(merged) > 1:
        out["propertyOrdering"] = []
    return out
