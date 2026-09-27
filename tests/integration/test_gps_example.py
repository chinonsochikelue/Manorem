"""The hand-authored GPS explainer -- the Slice 1 acceptance gate.

``examples/gps/ir.json`` is the reference Visual IR: nine scenes authored purely
in the semantic vocabulary. This test holds it to the contract the whole design
rests on -- that a well-formed authored IR reaches the renderer with zero errors,
in every aspect, because layout lives in stage space and only P6 touches pixels.

It also proves the committed JSON is exactly what ``build_ir.py`` emits, so the
artifact stays re-derivable rather than hand-edited into drift.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from examples.gps.build_ir import build_project

from manorem_compiler import CompileOptions, compile_project
from manorem_core import Severity
from manorem_ir import Project, parse_project
from manorem_ir.enums import Aspect

_IR_JSON = Path(__file__).resolve().parents[2] / "examples" / "gps" / "ir.json"


def _project() -> Project:
    return parse_project(json.loads(_IR_JSON.read_text(encoding="utf-8")))


def _errors(project: Project, aspect: Aspect) -> set[str]:
    _, bag = compile_project(project, CompileOptions(aspect=aspect))
    return {d.code.value for d in bag if d.severity is Severity.ERROR}


def test_committed_json_matches_the_builder() -> None:
    # If this fails, someone hand-edited ir.json; regenerate it via build_ir.py.
    committed = _IR_JSON.read_text(encoding="utf-8")
    fresh = build_project().model_dump_json(indent=2) + "\n"
    assert committed == fresh


def test_parses_as_nine_scenes() -> None:
    project = _project()
    assert project.id == "gps"
    assert project.scene_count == 9


@pytest.mark.parametrize("aspect", [Aspect.WIDESCREEN, Aspect.VERTICAL, Aspect.SQUARE])
def test_compiles_with_zero_errors_in_every_aspect(aspect: Aspect) -> None:
    # Warnings (T3 pacing/geometry lints) are allowed; errors are not. The same IR
    # must lower cleanly to 16:9, 9:16 and 1:1 -- that is the aspect contract.
    assert _errors(_project(), aspect) == set()


def test_timing_is_aspect_independent() -> None:
    # Layout changes with aspect; the schedule does not. All three plans run the
    # same number of frames because timing is resolved before P6 ever sees pixels.
    project = _project()
    plans = [
        compile_project(project, CompileOptions(aspect=a))[0]
        for a in (Aspect.WIDESCREEN, Aspect.VERTICAL, Aspect.SQUARE)
    ]
    assert len({p.total_frames for p in plans}) == 1
