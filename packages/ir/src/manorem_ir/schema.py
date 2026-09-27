"""JSON Schema export.

The Pydantic models are the single source of truth; every other type system in
the project is *generated* from these schemas rather than hand-maintained:

* the TypeScript IR types (``packages-ts/ir``), with CI failing on drift;
* the frontend inspector, which validates edits client-side against the same
  schema the backend enforces;
* the Gemini structured-output request, after the down-converter in
  ``manorem_ai.schema_shim`` reduces it to the subset the API accepts.

Two type systems maintained by hand diverge; one generated from the other cannot.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from manorem_core import sha256_of
from manorem_ir.project import IR_VERSION, Project
from manorem_ir.scene import Scene

#: Exported schemas by name. ``scene`` is exported separately because IR is
#: generated one scene at a time -- the whole-project schema nests too deeply for
#: structured-output APIs to accept.
SCHEMA_MODELS: dict[str, type[BaseModel]] = {
    "project": Project,
    "scene": Scene,
}


def schema_for(name: str) -> dict[str, Any]:
    """JSON Schema for one exported model, in validation (input) mode."""
    model = SCHEMA_MODELS.get(name)
    if model is None:
        known = ", ".join(sorted(SCHEMA_MODELS))
        raise KeyError(f"unknown schema {name!r} (known: {known})")
    schema = model.model_json_schema(mode="validation")
    schema["$id"] = f"https://manorem.dev/schema/{name}/v{IR_VERSION}.json"
    schema["x-ir-version"] = IR_VERSION
    return schema


def all_schemas() -> dict[str, dict[str, Any]]:
    return {name: schema_for(name) for name in SCHEMA_MODELS}


def schema_digest(name: str) -> str:
    """Content address of a schema -- the value CI compares to detect drift."""
    return sha256_of(schema_for(name))


def export_schemas(directory: Path) -> list[Path]:
    """Write every schema as pretty-printed JSON, returning the paths written."""
    directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, schema in all_schemas().items():
        path = directory / f"{name}.schema.json"
        path.write_text(
            json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        written.append(path)
    return written
