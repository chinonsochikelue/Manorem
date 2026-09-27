"""Golden RenderPlans: the aspect contract, locked byte-for-byte.

The primary regression gate is a snapshot, not a render (§28): compiling the same
IR must produce the same plan, and the *same* IR at 16:9 / 9:16 / 1:1 must produce
three plans that differ only where the frame mapping makes them. If a layout tweak
or a rounding change shifts a coordinate, it shows up here as a diff to review, not
as a silently different video.

Regenerate intentionally with ``MANOREM_UPDATE_GOLDENS=1`` after an *expected*
change, then read the diff before committing.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from manorem_compiler import CompileOptions, compile_project
from manorem_core import canonical_json
from manorem_ir import Aspect
from tests.support.diag import error_codes
from tests.support.ir_builders import valid_project

_GOLDENS = Path(__file__).parent / "goldens"
_CASES = [
    (Aspect.WIDESCREEN, "gps_16x9.json"),
    (Aspect.VERTICAL, "gps_9x16.json"),
    (Aspect.SQUARE, "gps_1x1.json"),
]


@pytest.mark.parametrize(("aspect", "filename"), _CASES, ids=[c[1] for c in _CASES])
def test_render_plan_matches_golden(aspect: Aspect, filename: str) -> None:
    plan, bag = compile_project(valid_project(), CompileOptions(aspect=aspect, quality="draft"))
    assert error_codes(bag) == set()
    serialized = canonical_json(plan.model_dump(mode="json"))
    path = _GOLDENS / filename
    if os.environ.get("MANOREM_UPDATE_GOLDENS") == "1":
        path.write_text(serialized + "\n", encoding="utf-8")
    assert serialized == path.read_text(encoding="utf-8").strip(), (
        f"{filename} drifted; rerun with MANOREM_UPDATE_GOLDENS=1 if the change is intended"
    )
