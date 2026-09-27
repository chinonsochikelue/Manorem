"""The ``manorem`` command line.

Five verbs, one pipeline. ``validate`` and ``compile`` operate on a Visual IR
project; ``render`` on a compiled RenderPlan; ``schema`` exports the JSON Schema
that is the source of truth for every other type system; and ``build`` runs the
whole idea-to-video pipeline offline against replayed fixtures. Each command is a
thin wrapper: it parses arguments, calls one library function, prints diagnostics
through :func:`~manorem_cli._support.report`, and sets its exit code from whether
that produced an error -- so a broken IR fails loudly and never renders.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import typer

from manorem_ai import FixtureResearchProvider, Pipeline, PipelineError
from manorem_cli._support import (
    build_provider,
    load_corpus,
    load_model,
    report,
    resolve_aspect,
    write_json,
)
from manorem_compiler import CompileOptions, RenderPlan, compile_project
from manorem_compositor import Compositor
from manorem_core import ConfigError, DiagnosticBag, LocalFSStore, get_settings
from manorem_ir import Project, export_schemas, schema_for, validate_project
from manorem_renderer import ManimRenderer, RenderOptions, StubRenderer

app = typer.Typer(
    name="manorem",
    help="Turn an idea into a narrated, captioned explainer video.",
    no_args_is_help=True,
    add_completion=False,
)


@app.command()
def validate(
    ir: Path = typer.Argument(..., help="Path to a Visual IR project JSON file."),
) -> None:
    """Check a Visual IR project against the structural and semantic validators."""
    project = load_model(ir, Project, label="validate")
    bag = validate_project(project)
    if report(bag, label="validate"):
        raise typer.Exit(code=1)


@app.command("compile")
def compile_cmd(
    ir: Path = typer.Argument(..., help="Path to a Visual IR project JSON file."),
    aspect: str | None = typer.Option(None, "--aspect", "-a", help="16:9 | 9:16 | 1:1."),
    quality: str | None = typer.Option(None, "--quality", "-q", help="draft | medium | final."),
    output: Path | None = typer.Option(None, "--output", "-o", help="Write the RenderPlan here."),
    no_autofix: bool = typer.Option(False, "--no-autofix", help="Skip the safe autofixers."),
) -> None:
    """Compile a Visual IR project to a RenderPlan (deterministic, no rendering)."""
    project = load_model(ir, Project, label="compile")
    options = CompileOptions(aspect=resolve_aspect(aspect), quality=quality, autofix=not no_autofix)
    plan, bag = compile_project(project, options)
    if report(bag, label="compile"):
        raise typer.Exit(code=1)
    if output is not None:
        write_json(output, plan)
        typer.secho(f"compile: wrote {output}", fg=typer.colors.GREEN, err=True)
    else:
        typer.echo(plan.model_dump_json(indent=2))


@app.command()
def render(
    plan: Path = typer.Argument(..., help="Path to a compiled RenderPlan JSON file."),
    output: Path | None = typer.Option(None, "--output", "-o", help="Final MP4 path."),
    quality: str = typer.Option("draft", "--quality", "-q", help="draft | medium | final."),
    engine: str = typer.Option("manim", "--engine", help="manim (real) | stub (solid frames)."),
) -> None:
    """Render a RenderPlan to a captioned MP4, with SRT/VTT sidecars beside it."""
    render_plan = load_model(plan, RenderPlan, label="render")
    renderer = StubRenderer() if engine == "stub" else ManimRenderer()
    result = renderer.render(render_plan, RenderOptions(quality=quality))
    if not result.ok or result.video is None:
        typer.secho(f"render: {result.status.value}", fg=typer.colors.RED, err=True)
        report(DiagnosticBag(list(result.diagnostics)), label="render")
        raise typer.Exit(code=1)

    out = output or Path(f"{plan.stem}.mp4")
    with tempfile.TemporaryDirectory(prefix="manorem-render-") as tmp:
        workspace = Path(tmp)
        scene = workspace / f"scene{result.video.suffix}"
        shutil.copy2(result.video, scene)
        composition = Compositor().compose(render_plan, (scene,), workspace)
        if not composition.ok or composition.video is None:
            report(DiagnosticBag(list(composition.diagnostics)), label="render")
            raise typer.Exit(code=1)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(composition.video, out)
        for sidecar in (composition.subtitles_srt, composition.subtitles_vtt):
            if sidecar is not None:
                shutil.copy2(sidecar, out.with_suffix(sidecar.suffix))
    typer.secho(f"render: wrote {out} (+ .srt/.vtt)", fg=typer.colors.GREEN, err=True)


@app.command()
def schema(
    name: str | None = typer.Argument(None, help="project | scene. Omit for all schemas."),
    output: Path | None = typer.Option(None, "--output", "-o", help="Write schema files here."),
) -> None:
    """Export the JSON Schema for the Visual IR -- the source of truth for all types."""
    if output is not None:
        for path in export_schemas(output):
            typer.secho(f"schema: wrote {path}", fg=typer.colors.GREEN, err=True)
        return
    if name is None:
        for key in ("project", "scene"):
            typer.echo(_schema_json(key))
        return
    typer.echo(_schema_json(name))


def _schema_json(name: str) -> str:
    import json  # noqa: PLC0415 - only this command formats a schema to stdout

    try:
        return json.dumps(schema_for(name), indent=2, sort_keys=True, ensure_ascii=False)
    except KeyError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from None


@app.command()
def build(
    idea: str = typer.Argument(..., help="The idea to explain, in one sentence."),
    aspect: str | None = typer.Option(None, "--aspect", "-a", help="16:9 | 9:16 | 1:1."),
    quality: str | None = typer.Option(None, "--quality", "-q", help="draft | medium | final."),
    corpus: Path | None = typer.Option(
        None, "--corpus", "-c", help="Retrieved-document JSON array for provenance."
    ),
    output: Path = typer.Option(Path("out"), "--output", "-o", help="Directory for all artifacts."),
) -> None:
    """Run the whole pipeline: research -> story -> script -> IR -> render -> video."""
    settings = get_settings()
    try:
        provider = build_provider(settings)
    except ConfigError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from None

    pipeline = Pipeline(
        provider,
        FixtureResearchProvider(load_corpus(corpus)),
        store=LocalFSStore(output / "store"),
    )
    try:
        result = pipeline.build(
            idea, aspect=resolve_aspect(aspect), quality=quality, workspace=output
        )
    except PipelineError as exc:
        typer.secho(f"build: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from None

    write_json(output / "brief.json", result.brief)
    write_json(output / "outline.json", result.outline)
    write_json(output / "script.json", result.script)
    for index, visual_plan in enumerate(result.plans):
        write_json(output / "plan" / f"plan_{index}.json", visual_plan)
    write_json(output / "ir.json", result.project)
    write_json(output / "renderplan.json", result.plan)

    report(result.diagnostics, label="build")
    video = result.video
    if video is None:
        typer.secho(f"build: artifacts in {output}, but the render did not complete", err=True)
        raise typer.Exit(code=1)
    # M1 renders are NOT assessed for visual quality -- say so rather than imply a pass.
    quality_note = "not assessed" if result.quality is None else "assessed"
    typer.secho(
        f"build: wrote {video} (visual quality: {quality_note})", fg=typer.colors.GREEN, err=True
    )


def main() -> None:
    """Console-script entry point (``manorem``)."""
    app()
