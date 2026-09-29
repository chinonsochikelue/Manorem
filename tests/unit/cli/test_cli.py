"""The CLI is a thin skin over the libraries -- these tests hold it to that.

They assert the contract a caller sees: the exit code, the artifacts on disk, and
that a semantically broken IR fails loudly with an ``IR2xx`` error and renders
*nothing*. The library behaviour behind each verb is proven in its own package's
suite; here we only check the wiring, argument parsing, and exit discipline.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from manorem_cli.app import app
from manorem_compiler import RenderPlan
from manorem_core import get_settings
from tests.support.ir_builders import valid_project

runner = CliRunner()

_GPS = Path(__file__).resolve().parents[3] / "examples" / "gps"
_BROKEN_REF = _GPS / "ir_broken_ref.json"
_VQA = Path(__file__).resolve().parents[3] / "examples" / "vqa"


def _write_project(tmp_path: Path) -> Path:
    ir = tmp_path / "ir.json"
    ir.write_text(valid_project().model_dump_json(indent=2) + "\n", encoding="utf-8")
    return ir


def test_help_lists_every_verb() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for verb in ("validate", "compile", "render", "vqa", "schema", "build"):
        assert verb in result.output


def test_schema_project_is_valid_json() -> None:
    result = runner.invoke(app, ["schema", "project"])
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert "properties" in parsed


def test_schema_unknown_name_exits_2() -> None:
    result = runner.invoke(app, ["schema", "nonsense"])
    assert result.exit_code == 2


def test_validate_accepts_a_valid_project(tmp_path: Path) -> None:
    ir = _write_project(tmp_path)
    result = runner.invoke(app, ["validate", str(ir)])
    assert result.exit_code == 0


def test_validate_missing_file_exits_2(tmp_path: Path) -> None:
    result = runner.invoke(app, ["validate", str(tmp_path / "nope.json")])
    assert result.exit_code == 2


def test_compile_writes_a_renderplan(tmp_path: Path) -> None:
    ir = _write_project(tmp_path)
    out = tmp_path / "plan.json"
    result = runner.invoke(app, ["compile", str(ir), "--aspect", "16:9", "-o", str(out)])
    assert result.exit_code == 0
    # The file on disk must be a real RenderPlan, not just bytes.
    RenderPlan.model_validate_json(out.read_text(encoding="utf-8"))


def test_compile_to_stdout_is_a_renderplan(tmp_path: Path) -> None:
    ir = _write_project(tmp_path)
    result = runner.invoke(app, ["compile", str(ir)])
    assert result.exit_code == 0
    # The runner folds the "compile: ok" status (stderr) in ahead of the plan (stdout);
    # the plan is the JSON object, so parse from its opening brace.
    plan_json = result.output[result.output.index("{") :]
    RenderPlan.model_validate_json(plan_json)


def test_broken_reference_fails_loudly_and_renders_nothing(tmp_path: Path) -> None:
    # The single guardrail this whole design turns on: semantic damage is an ERROR,
    # never a quiet repair. validate must exit non-zero, name the dangling id, and
    # compile must refuse to emit a plan.
    validated = runner.invoke(app, ["validate", str(_BROKEN_REF)])
    assert validated.exit_code == 1
    assert "IR201" in validated.output
    assert "satellite_4" in validated.output

    out = tmp_path / "plan.json"
    compiled = runner.invoke(app, ["compile", str(_BROKEN_REF), "-o", str(out)])
    assert compiled.exit_code == 1
    assert not out.exists()


def test_render_stub_engine_writes_mp4_with_sidecars(tmp_path: Path) -> None:
    ir = _write_project(tmp_path)
    plan = tmp_path / "plan.json"
    assert runner.invoke(app, ["compile", str(ir), "-o", str(plan)]).exit_code == 0

    out = tmp_path / "out.mp4"
    result = runner.invoke(app, ["render", str(plan), "--engine", "stub", "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert out.exists()
    assert out.with_suffix(".srt").exists()
    assert out.with_suffix(".vtt").exists()


def test_vqa_passes_a_clean_plan() -> None:
    # The offline geometric assessment finds nothing to complain about.
    result = runner.invoke(app, ["vqa", str(_VQA / "good" / "plan.json")])
    assert result.exit_code == 0


def test_vqa_fails_on_an_error_severity_defect() -> None:
    # A measured visual defect sets a non-zero exit and names its VQA6xx code.
    result = runner.invoke(app, ["vqa", str(_VQA / "overflow" / "plan.json")])
    assert result.exit_code == 1
    assert "VQA601" in result.output


def test_vqa_warning_only_plan_still_passes() -> None:
    # VQA608 is a warning: reported, but never a build failure.
    result = runner.invoke(app, ["vqa", str(_VQA / "density" / "plan.json")])
    assert result.exit_code == 0
    assert "VQA608" in result.output


def test_build_rejects_the_stub_provider(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # `build` needs a provider with prepared responses; the stub has none outside a
    # test harness, so the CLI must refuse it up front with a config exit, not crash
    # halfway through the pipeline.
    monkeypatch.setenv("MANOREM_LLM_PROVIDER", "stub")
    get_settings.cache_clear()
    try:
        result = runner.invoke(app, ["build", "An idea.", "-o", str(tmp_path / "out")])
    finally:
        get_settings.cache_clear()
    assert result.exit_code == 2
