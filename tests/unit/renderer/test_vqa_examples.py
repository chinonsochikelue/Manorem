"""The committed ``examples/vqa/`` corpus asserts one defect per fixture.

Where :mod:`test_vqa` builds geometry inline to unit-test each check, these tests
prove the *shipped* fixtures still exhibit exactly the defect they are named for --
loaded from JSON, assessed through the offline ``assess_plan(plan, build_manifest)``
path the ``manorem vqa`` command uses. Assertions are on codes and JSON Pointers,
never on message wording (see :mod:`tests.support.diag`).

Regenerate the corpus with ``uv run python examples/vqa/build_fixtures.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from manorem_compiler import RenderPlan
from manorem_core import Code, DiagnosticBag, Severity, pointer
from manorem_renderer import VQA_ERROR_CODES, assess_plan, build_manifest
from tests.support.diag import error_codes, only, warning_codes

_EXAMPLES = Path(__file__).resolve().parents[3] / "examples" / "vqa"

_MOBJECT_PTR = pointer("scenes", "s1", "mobjects", "{oid}")
_SCENE_PTR = pointer("scenes", "s1")


def _bag(name: str) -> DiagnosticBag:
    plan = RenderPlan.model_validate_json((_EXAMPLES / name / "plan.json").read_text("utf-8"))
    report = assess_plan(plan, build_manifest(plan))
    return DiagnosticBag(list(report.findings))


# name -> (code, owning object id) for the single error-severity defect it exhibits.
_ERROR_FIXTURES: dict[str, tuple[Code, str]] = {
    "overflow": (Code.VQA601_TEXT_OVERFLOW, "hdr"),
    "off-stage": (Code.VQA602_OBJECT_OFF_STAGE, "stray"),
    "overlap": (Code.VQA603_OBJECT_OVERLAP, "a"),
    "tiny-text": (Code.VQA604_TINY_TEXT, "fine"),
    "contrast": (Code.VQA606_BAD_CONTRAST, "murk"),
    "cut-off": (Code.VQA607_CUT_OFF_OBJECT, "planet"),
}


@pytest.mark.parametrize(
    ("name", "code", "oid"), [(n, c, o) for n, (c, o) in _ERROR_FIXTURES.items()]
)
def test_error_fixture_pins_its_code_and_pointer(name: str, code: Code, oid: str) -> None:
    bag = _bag(name)
    finding = only(bag, code)
    assert finding.severity is Severity.ERROR
    assert code in VQA_ERROR_CODES
    assert finding.pointer == _MOBJECT_PTR.format(oid=oid)
    assert finding.object_id == oid
    assert finding.scene_id == "s1"


def test_empty_frame_fixture_points_at_the_scene() -> None:
    bag = _bag("empty-frame")
    finding = only(bag, Code.VQA605_EMPTY_FRAME)
    assert finding.severity is Severity.ERROR
    assert finding.pointer == _SCENE_PTR
    assert finding.scene_id == "s1"


def test_good_fixture_has_no_findings() -> None:
    bag = _bag("good")
    assert not error_codes(bag)
    assert not warning_codes(bag)


def test_density_fixture_is_a_scene_level_warning() -> None:
    bag = _bag("density")
    finding = only(bag, Code.VQA608_EXCESSIVE_DENSITY)
    assert finding.severity is Severity.WARNING
    assert finding.pointer == _SCENE_PTR
    assert Code.VQA608_EXCESSIVE_DENSITY not in VQA_ERROR_CODES
    # A warning never fails a build.
    assert Code.VQA608_EXCESSIVE_DENSITY not in error_codes(bag)


def test_camera_fixture_flags_composition_as_a_warning() -> None:
    bag = _bag("camera")
    finding = only(bag, Code.VQA609_CAMERA_COMPOSITION)
    assert finding.severity is Severity.WARNING
    assert finding.pointer == _SCENE_PTR
    assert Code.VQA609_CAMERA_COMPOSITION in warning_codes(bag)
