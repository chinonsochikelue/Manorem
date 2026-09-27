"""JSON Schema export: the boundary where the IR stops being Python.

Three consumers derive their types from these documents rather than restating
them -- the TypeScript IR (CI fails on drift), the frontend inspector that
validates edits client-side, and the Gemini structured-output request after the
shim reduces the schema to the subset that API accepts. Two hand-maintained type
systems diverge; one generated from the other cannot.

So what matters here is not that a schema *exists* but that it is **addressable
and stable**: named, versioned, byte-identical across runs, and carrying the
vocabulary a generator has to choose from. ``schema_digest`` is the value CI
compares, which makes accidental non-determinism in this module a build that
fails at random rather than a build that fails when the IR actually changed.

``scene`` is exported alongside ``project`` because IR is generated one scene at a
time -- the whole-project schema nests deeper than structured-output APIs accept.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from manorem_ir import (
    IR_VERSION,
    SCHEMA_MODELS,
    LayoutKind,
    NarrationRole,
    ObjectKind,
    Project,
    Scene,
    SemanticOp,
    all_schemas,
    export_schemas,
    schema_digest,
    schema_for,
)


def _walk(node: Any) -> list[dict[str, Any]]:
    """Every mapping in a schema document, so a sweep needs no path knowledge."""
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        found.append(node)
        for value in node.values():
            found.extend(_walk(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_walk(item))
    return found


def _enum_values(schema: dict[str, Any]) -> set[str]:
    """Union of every ``enum`` list anywhere in the document."""
    values: set[str] = set()
    for node in _walk(schema):
        entries = node.get("enum")
        if isinstance(entries, list):
            values.update(str(entry) for entry in entries)
    return values


def _discriminators(schema: dict[str, Any]) -> set[tuple[str, frozenset[str]]]:
    """Every exported discriminator as ``(property name, arm tags)``."""
    return {
        (node["discriminator"]["propertyName"], frozenset(node["discriminator"]["mapping"]))
        for node in _walk(schema)
        if "discriminator" in node
    }


class TestExportedSet:
    """What is exported, and why those two."""

    def test_project_and_scene_are_both_exported(self) -> None:
        # Per-scene generation is not an optimization: the whole-project schema
        # nests too deeply for structured-output APIs, so ``scene`` is the unit the
        # IR generator is actually handed.
        assert set(SCHEMA_MODELS) == {"project", "scene"}
        assert SCHEMA_MODELS["project"] is Project
        assert SCHEMA_MODELS["scene"] is Scene

    def test_all_schemas_covers_the_exported_set(self) -> None:
        assert set(all_schemas()) == set(SCHEMA_MODELS)

    def test_an_unknown_name_names_what_it_knows(self) -> None:
        # The error is read by whoever mistyped a name in a build script, so it
        # has to say what the options were.
        with pytest.raises(KeyError, match="project, scene"):
            schema_for("episode")


class TestIdentityAndVersioning:
    """A stored schema has to say what it is."""

    @pytest.mark.parametrize("name", sorted(SCHEMA_MODELS))
    def test_each_schema_carries_an_id_and_a_version(self, name: str) -> None:
        # A generated TypeScript file or a cached inspector schema outlives the
        # build that produced it; without these two fields a reader cannot tell
        # which IR it is validating against.
        schema = schema_for(name)

        assert schema["$id"] == f"https://manorem.dev/schema/{name}/v{IR_VERSION}.json"
        assert schema["x-ir-version"] == IR_VERSION

    def test_the_two_schemas_have_distinct_ids(self) -> None:
        assert schema_for("project")["$id"] != schema_for("scene")["$id"]

    def test_the_version_matches_the_models(self) -> None:
        # One version string, not two: a schema claiming 1.0 while ``Project``
        # defaults to 1.1 would advertise documents it cannot represent.
        assert schema_for("project")["x-ir-version"] == Project(id="p", title="T").ir_version


class TestDeterminism:
    """``schema_digest`` is the drift gate, so it must only move when the IR does."""

    @pytest.mark.parametrize("name", sorted(SCHEMA_MODELS))
    def test_repeated_export_is_byte_identical(self, name: str) -> None:
        # Anything set-ordered or dict-insertion-dependent inside schema
        # generation would make CI fail at random instead of on real drift.
        assert schema_digest(name) == schema_digest(name)
        assert json.dumps(schema_for(name), sort_keys=True) == json.dumps(
            schema_for(name), sort_keys=True
        )

    def test_the_two_schemas_have_distinct_digests(self) -> None:
        assert schema_digest("project") != schema_digest("scene")

    def test_a_schema_is_json_serializable_as_is(self) -> None:
        # It is written to disk and posted to an HTTP API; a stray Python object
        # in there would fail at the point of use, far from this module.
        for name in SCHEMA_MODELS:
            json.dumps(schema_for(name), allow_nan=False)


class TestVocabularyIsInTheSchema:
    """The closed vocabularies have to reach the model that must choose from them.

    The IR-generation prompt is built from the schema plus the operation table. If
    an enum did not survive export, the model would be free-forming exactly the
    terms the compiler is guaranteed to understand.
    """

    def test_every_object_kind_appears(self) -> None:
        assert {k.value for k in ObjectKind} <= _enum_values(schema_for("scene"))

    def test_every_semantic_operation_appears(self) -> None:
        assert {op.value for op in SemanticOp} <= _enum_values(schema_for("scene"))

    def test_every_layout_and_narration_role_appears(self) -> None:
        present = _enum_values(schema_for("scene"))

        assert {kind.value for kind in LayoutKind} <= present
        assert {role.value for role in NarrationRole} <= present

    def test_the_project_schema_inherits_the_scene_vocabulary(self) -> None:
        # ``project`` nests ``scene``, so a generator handed the whole-project
        # schema sees the same closed menu.
        assert {op.value for op in SemanticOp} <= _enum_values(schema_for("project"))


class TestDiscriminatorsSurviveExport:
    """A discriminated union has to arrive as one, or clients guess.

    The TypeScript generator emits a tagged union from ``discriminator``; without
    it the union degrades to a structural or-type, and the inspector can no longer
    tell an author which arm a malformed object was meant to be.
    """

    @pytest.mark.parametrize(
        ("property_name", "arms"),
        [
            ("at", {"absolute", "after", "with", "narration"}),
            ("kind", {"seconds", "narration", "auto"}),
            ("kind", {k.value for k in ObjectKind}),
            ("mode", {"auto", "slot", "anchor", "stage"}),
        ],
    )
    def test_each_union_exports_its_full_mapping(self, property_name: str, arms: set[str]) -> None:
        # Asserting the whole mapping, not just its presence: an arm missing from
        # the mapping is an arm no client can construct.
        assert (property_name, frozenset(arms)) in _discriminators(schema_for("scene"))

    def test_the_project_schema_carries_them_too(self) -> None:
        assert ("mode", frozenset({"auto", "slot", "anchor", "stage"})) in _discriminators(
            schema_for("project")
        )


class TestExportToDisk:
    """What ``manorem schema`` writes, and where."""

    def test_one_pretty_printed_file_per_schema(self, tmp_path: Path) -> None:
        written = export_schemas(tmp_path / "schema")

        assert {p.name for p in written} == {"project.schema.json", "scene.schema.json"}
        assert all(p.exists() for p in written)

    def test_the_written_file_is_the_exported_schema(self, tmp_path: Path) -> None:
        (path,) = [p for p in export_schemas(tmp_path) if p.name == "scene.schema.json"]

        assert json.loads(path.read_text(encoding="utf-8")) == schema_for("scene")

    def test_the_output_is_diffable(self, tmp_path: Path) -> None:
        # These files are committed and reviewed, so a schema change has to read as
        # a small diff rather than one reordered line.
        (path,) = [p for p in export_schemas(tmp_path) if p.name == "scene.schema.json"]
        text = path.read_text(encoding="utf-8")

        assert text.endswith("\n")
        assert "\n  " in text

    def test_the_directory_is_created_if_absent(self, tmp_path: Path) -> None:
        target = tmp_path / "generated" / "schema"

        assert len(export_schemas(target)) == 2
        assert target.is_dir()

    def test_re_exporting_overwrites_rather_than_accumulates(self, tmp_path: Path) -> None:
        first = export_schemas(tmp_path)
        second = export_schemas(tmp_path)

        assert first == second
        assert sorted(p.name for p in tmp_path.iterdir()) == [
            "project.schema.json",
            "scene.schema.json",
        ]
