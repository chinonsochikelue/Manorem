"""JSON Patch mechanics, and the semantic-id invariant that keeps repair honest.

The first tests exercise the RFC 6902 operations on a plain document. The rest
are the guardrail: :func:`apply_scene_patch` lets a repair fix references,
parameters and timing, but rejects any patch that changes *which* objects, cues,
groups, segments or relationships exist -- fabricating or dropping semantic
content is exactly what the bounded repair loop must surface, not paper over.
"""

from __future__ import annotations

from typing import Any

import pytest

from manorem_ai import JsonPatch, PatchError, PatchOp, apply_patch, apply_scene_patch
from manorem_ir import RelationKind
from tests.support.ir_builders import (
    dot_obj,
    relationship,
    scene_with,
    text_obj,
    valid_scene,
)


def _patch(*ops: dict[str, Any]) -> JsonPatch:
    return JsonPatch(operations=tuple(PatchOp.model_validate(op) for op in ops))


def test_apply_patch_covers_the_operations() -> None:
    document = {"a": 1, "list": [10, 20], "b": {"c": "x"}}
    patched = apply_patch(
        document,
        _patch(
            {"op": "replace", "path": "/a", "value": 2},
            {"op": "add", "path": "/list/-", "value": 30},
            {"op": "remove", "path": "/b/c"},
            {"op": "copy", "from": "/a", "path": "/a_copy"},
            {"op": "move", "from": "/list/0", "path": "/first"},
            {"op": "test", "path": "/a", "value": 2},
        ),
    )
    assert patched == {"a": 2, "list": [20, 30], "b": {}, "a_copy": 2, "first": 10}
    # Pure: the input document is untouched.
    assert document == {"a": 1, "list": [10, 20], "b": {"c": "x"}}


def test_apply_patch_failed_test_raises() -> None:
    with pytest.raises(PatchError):
        apply_patch({"a": 1}, _patch({"op": "test", "path": "/a", "value": 2}))


def test_scene_patch_allows_fixing_a_parameter() -> None:
    scene = valid_scene()
    # Retarget nothing; just rewrite narration text -- ids all survive.
    patched = apply_scene_patch(
        scene, _patch({"op": "replace", "path": "/narration/0/text", "value": "Where now?"})
    )
    assert patched.segment_ids == scene.segment_ids
    assert patched.narration[0].text == "Where now?"


def test_scene_patch_rejects_adding_an_object() -> None:
    scene = valid_scene()
    extra = dot_obj("satellite_4").model_dump(mode="json")
    with pytest.raises(PatchError):
        apply_scene_patch(scene, _patch({"op": "add", "path": "/objects/-", "value": extra}))


def test_scene_patch_rejects_dropping_a_cue() -> None:
    scene = valid_scene()
    with pytest.raises(PatchError):
        apply_scene_patch(scene, _patch({"op": "remove", "path": "/timeline/0"}))


def test_scene_patch_rejects_changing_relationships() -> None:
    scene = scene_with(
        objects=[text_obj("title", "T"), dot_obj("phone")],
        relationships=[relationship(RelationKind.POINTS_TO, "title", "phone")],
    )
    with pytest.raises(PatchError):
        apply_scene_patch(scene, _patch({"op": "remove", "path": "/relationships/0"}))


def test_scene_patch_rejects_removing_an_object() -> None:
    scene = scene_with(
        objects=[text_obj("title", "T"), dot_obj("phone")],
        narration=[],
        timeline=[],
    )
    with pytest.raises(PatchError):
        apply_scene_patch(scene, _patch({"op": "remove", "path": "/objects/1"}))
