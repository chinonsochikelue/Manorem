"""The post-render repair loop: a visual defect patches the IR, never the pixels.

``_render_qa_repair`` is deliberately separate from the semantic (pre-render) loop
but shares its machinery: an error-severity ``VQA6xx`` finding is grouped by scene,
routed to the same :class:`RepairAgent`/:func:`apply_scene_patch`, then the project
is recompiled and rerendered and reassessed -- bounded by ``max_repair_attempts``.

These tests drive that loop directly with a scripted Visual QA (so the verdict is
controlled, not rendered) and a fake renderer that emits no video (so nothing calls
ffmpeg). What they pin: the loop clears when a patch fixes the frame, stops at the
attempt cap when it never does, and breaks early when a patch is rejected and the
project is left unchanged.
"""

from __future__ import annotations

from pathlib import Path

from manorem_ai import Pipeline
from manorem_ai.cassette import StubProvider
from manorem_ai.patch import JsonPatch, PatchOp
from manorem_ai.research import FixtureResearchProvider
from manorem_compiler import CompileOptions, RenderPlan, compile_project
from manorem_core import Code, Diagnostic, LocalFSStore, Severity, pointer
from manorem_ir import Project
from manorem_renderer import (
    Capability,
    QualityReport,
    RenderOptions,
    RenderResult,
    RenderStatus,
    build_manifest,
)
from tests.support.ir_builders import make_project, valid_scene

_SCENE_ID = "intro"


def _error_report() -> QualityReport:
    return QualityReport(
        findings=(
            Diagnostic(
                code=Code.VQA601_TEXT_OVERFLOW,
                severity=Severity.ERROR,
                message="text 'title' extends past the framed stage",
                pointer=pointer("scenes", _SCENE_ID, "mobjects", "title"),
                scene_id=_SCENE_ID,
                object_id="title",
            ),
        )
    )


def _clean_report() -> QualityReport:
    return QualityReport(findings=())


class _ScriptedVQA:
    """Returns a scripted verdict per call; the last entry repeats."""

    name = "scripted"

    def __init__(self, reports: list[QualityReport]) -> None:
        self._reports = reports
        self.calls = 0

    def assess(self, plan: RenderPlan, result: RenderResult) -> QualityReport | None:
        idx = min(self.calls, len(self._reports) - 1)
        self.calls += 1
        return self._reports[idx]


class _NoVideoRenderer:
    """Reports OK but emits no video, so the compositor is never invoked."""

    name = "no-video"
    capabilities: frozenset[Capability] = frozenset()

    def render(self, plan: RenderPlan, opts: RenderOptions) -> RenderResult:
        return RenderResult(
            status=RenderStatus.OK,
            video=None,
            frame_samples=(),
            manifest=build_manifest(plan, sample_rate_hz=opts.sample_rate_hz),
        )


def _pipeline(provider: StubProvider, tmp_path: Path, vqa: _ScriptedVQA) -> Pipeline:
    return Pipeline(
        provider,
        FixtureResearchProvider(()),
        store=LocalFSStore(tmp_path / "store"),
        renderer=_NoVideoRenderer(),
        visual_qa=vqa,
    )


def _compiled() -> tuple[Project, RenderPlan]:
    project = make_project(valid_scene())
    plan, bag = compile_project(project, CompileOptions())
    assert not bag.has_errors, bag.errors
    return project, plan


def _retitle_patch() -> JsonPatch:
    # Changes the scene's intent -- a legal repair: no entity id set moves.
    return JsonPatch(operations=(PatchOp(op="replace", path="/intent", value="Repaired."),))


def _entity_dropping_patch() -> JsonPatch:
    # Removes an object -- apply_scene_patch must reject this, so no scene changes.
    return JsonPatch(operations=(PatchOp(op="remove", path="/objects/0"),))


def test_visual_repair_clears_after_one_patch(tmp_path: Path) -> None:
    project, plan = _compiled()
    vqa = _ScriptedVQA([_error_report(), _clean_report()])
    provider = StubProvider.sequence([_retitle_patch()])
    pipe = _pipeline(provider, tmp_path, vqa)

    repaired, _plan, _render, report, _comp, attempts = pipe._render_qa_repair(
        project, plan, CompileOptions(), tmp_path / "work"
    )

    assert attempts == 1
    assert report is not None and report.passed
    located = repaired.locate_scene(_SCENE_ID)
    assert located is not None and located[1].intent == "Repaired."
    assert vqa.calls == 2  # initial assessment + one after the repair


def test_visual_repair_respects_the_attempt_cap(tmp_path: Path) -> None:
    project, plan = _compiled()
    # The defect never clears; the loop must still stop at max_repair_attempts.
    vqa = _ScriptedVQA([_error_report()])
    provider = StubProvider.sequence([_retitle_patch(), _retitle_patch()])
    pipe = _pipeline(provider, tmp_path, vqa)

    _project, _plan, _render, report, _comp, attempts = pipe._render_qa_repair(
        project, plan, CompileOptions(), tmp_path / "work"
    )

    assert attempts == pipe._settings.max_repair_attempts == 2
    assert report is not None and not report.passed


def test_visual_repair_stops_when_a_patch_is_rejected(tmp_path: Path) -> None:
    project, plan = _compiled()
    vqa = _ScriptedVQA([_error_report()])
    # Dropping an entity is rejected, so no scene changes and the loop breaks early.
    provider = StubProvider.sequence([_entity_dropping_patch()])
    pipe = _pipeline(provider, tmp_path, vqa)

    result_project, _plan, _render, report, _comp, attempts = pipe._render_qa_repair(
        project, plan, CompileOptions(), tmp_path / "work"
    )

    assert attempts == 1  # one attempt was made, then the loop gave up
    assert result_project is project  # nothing was patched
    assert report is not None and not report.passed
