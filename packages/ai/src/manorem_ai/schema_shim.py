"""Down-convert a Pydantic JSON Schema to the subset Gemini accepts.

Gemini's structured-output schema is a *subset* of JSON Schema, and the docs warn
that a deeply nested or ``$ref``-heavy schema may be rejected outright. Pydantic,
meanwhile, emits exactly that: ``$defs`` with ``$ref`` back-links, ``allOf``
wrappers, ``discriminator`` maps, ``const`` for literal fields, and ``title`` and
``additionalProperties`` on every object. This module rewrites all of it into the
flat, self-contained shape Gemini takes.

Three transforms carry the weight:

* **Inlining.** Every ``$ref`` is resolved against ``$defs`` and expanded in place,
  so the result stands alone with no back-references. A cycle -- which the IR does
  not contain, but which the converter must not loop on -- is broken with a bare
  ``object``.
* **``const`` becomes a one-value ``enum``.** Discriminated-union tags render as
  ``const``; Gemini has no ``const`` but does have ``enum``, and a single-element
  enum means the same thing.
* **``anyOf`` with a null branch becomes ``nullable``.** Pydantic spells
  ``T | None`` as ``anyOf: [T, {"type": "null"}]``; Gemini spells it as ``T`` with
  ``nullable: true``. Collapsing it keeps optional fields legible rather than
  turning every one into a two-way union.

Everything outside the allowlist is dropped. The round-trip test asserts the
result is free of the constructs Gemini rejects and that the fields, enums and
requiredness a valid answer depends on survived the trip.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

__all__ = ["to_gemini_schema"]

#: Keys Gemini's schema understands. Anything else is incidental to Pydantic's
#: rendering (``title``), a validation nicety Gemini ignores (``additionalProperties``),
#: or a construct it rejects (``$ref``, ``discriminator``); all are dropped.
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
        "maxItems",
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
        target = defs.get(name, {})
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
    return out


def _convert_any_of(members: list[_JsonObj], defs: _JsonObj, stack: tuple[str, ...]) -> _JsonObj:
    """Collapse ``T | None`` to nullable; keep genuine unions as ``anyOf``."""
    non_null = [m for m in members if m.get("type") != "null"]
    nullable = len(non_null) != len(members)

    if len(non_null) == 1:
        collapsed = _convert(non_null[0], defs, stack)
        if nullable:
            collapsed["nullable"] = True
        return collapsed

    converted = [_convert(m, defs, stack) for m in non_null]
    out: _JsonObj = {"anyOf": converted}
    if nullable:
        out["nullable"] = True
    return out
