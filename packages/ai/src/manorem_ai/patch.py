"""JSON Patch (RFC 6902) with the guardrail that keeps repair honest.

The repair agent does not rewrite a scene; it proposes a *patch* -- a minimal,
auditable, revertible list of operations. A patch is easier to review than a fresh
generation, cannot silently rewrite a scene it was not pointed at, and leaves a
record of exactly what changed.

:func:`apply_scene_patch` adds the load-bearing constraint. A repair may adjust
parameters, timing, placement or a dangling *reference* -- but it may **not change
which semantic entities exist**. The set of object, group, cue, narration-segment
and relationship identities must survive the patch unchanged; if it does not, the
patch is rejected. This is guardrail #1 at the repair boundary: a repair that fixes
"cue targets a missing satellite" by pointing the cue at a real object is allowed,
while one that fabricates the satellite -- or quietly drops the cue -- is not. That
is precisely the semantic content the bounded repair loop exists to surface, not to
paper over.
"""

from __future__ import annotations

import copy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from manorem_core import ManoremError
from manorem_ir import Scene

__all__ = ["JsonPatch", "PatchError", "PatchOp", "apply_patch", "apply_scene_patch"]


class PatchError(ManoremError):
    """A patch could not be applied, or applying it violated the id invariant."""


class PatchOp(BaseModel):
    """One RFC 6902 operation. ``value`` and ``from_`` are used per ``op``."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    op: Literal["add", "remove", "replace", "move", "copy", "test"]
    path: str
    value: Any = None
    from_: str | None = Field(default=None, alias="from")


class JsonPatch(BaseModel):
    """An ordered list of operations, applied as a unit."""

    model_config = ConfigDict(frozen=True)

    operations: tuple[PatchOp, ...] = ()


def _unescape(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def _split(path: str) -> list[str]:
    if path == "":
        return []
    if not path.startswith("/"):
        raise PatchError(f"json pointer must start with '/': {path!r}")
    return [_unescape(token) for token in path.split("/")[1:]]


def _child(container: Any, token: str) -> Any:
    if isinstance(container, list):
        return container[_index(container, token, allow_end=False)]
    if isinstance(container, dict):
        if token not in container:
            raise PatchError(f"pointer names missing key {token!r}")
        return container[token]
    raise PatchError(f"cannot descend into {type(container).__name__} at {token!r}")


def _index(array: list[Any], token: str, *, allow_end: bool) -> int:
    if token == "-":
        if allow_end:
            return len(array)
        raise PatchError("'-' is only valid when adding to an array")
    try:
        value = int(token)
    except ValueError:
        raise PatchError(f"array index must be an integer, got {token!r}") from None
    limit = len(array) if allow_end else len(array) - 1
    if value < 0 or value > limit:
        raise PatchError(f"array index {value} out of range")
    return value


def _resolve_parent(document: Any, tokens: list[str]) -> Any:
    parent = document
    for token in tokens[:-1]:
        parent = _child(parent, token)
    return parent


def _get(document: Any, tokens: list[str]) -> Any:
    node = document
    for token in tokens:
        node = _child(node, token)
    return node


def _set(parent: Any, token: str, value: Any, *, insert: bool) -> None:
    if isinstance(parent, list):
        idx = _index(parent, token, allow_end=insert)
        if insert:
            parent.insert(idx, value)
        else:
            parent[idx] = value
    elif isinstance(parent, dict):
        parent[token] = value
    else:
        raise PatchError(f"cannot set {token!r} on {type(parent).__name__}")


def _remove(parent: Any, token: str) -> None:
    if isinstance(parent, list):
        del parent[_index(parent, token, allow_end=False)]
    elif isinstance(parent, dict):
        if token not in parent:
            raise PatchError(f"cannot remove missing key {token!r}")
        del parent[token]
    else:
        raise PatchError(f"cannot remove {token!r} from {type(parent).__name__}")


def _apply_one(document: Any, operation: PatchOp) -> None:
    tokens = _split(operation.path)
    if not tokens:
        raise PatchError("patching the whole document root is not supported")
    parent = _resolve_parent(document, tokens)
    token = tokens[-1]

    if operation.op == "test":
        if _get(document, tokens) != operation.value:
            raise PatchError(f"test failed at {operation.path!r}")
    elif operation.op == "add":
        _set(parent, token, operation.value, insert=True)
    elif operation.op == "replace":
        _get(document, tokens)  # must exist
        _set(parent, token, operation.value, insert=False)
    elif operation.op == "remove":
        _remove(parent, token)
    elif operation.op in ("move", "copy"):
        if operation.from_ is None:
            raise PatchError(f"{operation.op!r} requires a 'from' pointer")
        from_tokens = _split(operation.from_)
        moved = _get(document, from_tokens)
        if operation.op == "move":
            _remove(_resolve_parent(document, from_tokens), from_tokens[-1])
            parent = _resolve_parent(document, tokens)
        _set(parent, token, moved, insert=True)


def apply_patch(document: Any, patch: JsonPatch) -> Any:
    """Apply a patch to a JSON-like document, returning a new document.

    Pure: the input is deep-copied first, so a partially-applied patch never
    leaves a caller's document half-mutated. Any failure is a :class:`PatchError`.
    """
    working = copy.deepcopy(document)
    for operation in patch.operations:
        _apply_one(working, operation)
    return working


def _relationship_keys(scene: Scene) -> set[tuple[str, str, str]]:
    return {(r.kind.value, r.source, r.target) for r in scene.relationships}


def apply_scene_patch(scene: Scene, patch: JsonPatch) -> Scene:
    """Apply a repair patch to one scene, enforcing the semantic-id invariant.

    The patch may change parameters, timing, placement and references; it may not
    change *which* objects, groups, cues, narration segments or relationships
    exist. A patch that does is rejected -- fabricating or dropping semantic
    content is exactly what the repair loop must not do.
    """
    patched = apply_patch(scene.model_dump(mode="json"), patch)
    try:
        new_scene = Scene.model_validate(patched)
    except ValidationError as exc:
        raise PatchError(f"patched scene did not validate: {exc}") from exc

    for name, before, after in (
        ("object", scene.object_ids, new_scene.object_ids),
        ("group", scene.group_ids, new_scene.group_ids),
        ("cue", scene.cue_ids, new_scene.cue_ids),
        ("narration", scene.segment_ids, new_scene.segment_ids),
    ):
        if before != after:
            raise PatchError(
                f"repair changed the set of {name} ids "
                f"(added {after - before or '{}'}, removed {before - after or '{}'}); "
                "a patch may fix references, not fabricate or drop entities"
            )
    if _relationship_keys(scene) != _relationship_keys(new_scene):
        raise PatchError("repair changed the set of relationships; this is forbidden")
    return new_scene
