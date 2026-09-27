"""Shared plumbing for the commands: IO, diagnostics, provider wiring.

The commands stay thin -- parse arguments, call one library function, report.
Everything reusable across them (loading a model from disk, printing a diagnostic
bag with the right exit behaviour, choosing an LLM backend from settings) lives
here so no command re-implements it and they all fail the same way.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from pydantic import BaseModel, ValidationError

from manorem_ai import CassetteProvider, GeminiProvider, LLMProvider
from manorem_ai.research import Document
from manorem_core import ConfigError, DiagnosticBag, LLMProviderName, Settings
from manorem_ir import Aspect


def load_model[M: BaseModel](path: Path, model: type[M], *, label: str) -> M:
    """Parse ``path`` as ``model`` JSON, turning a bad file into a clean exit."""
    try:
        return model.model_validate_json(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        typer.secho(f"{label}: no such file: {path}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from None
    except ValidationError as exc:
        typer.secho(
            f"{label}: {path} is not a valid {model.__name__}:", fg=typer.colors.RED, err=True
        )
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from None


def write_json(path: Path, model: BaseModel) -> None:
    """Write ``model`` as pretty, deterministic JSON (byte-stable across runs)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(model.model_dump_json(indent=2) + "\n", encoding="utf-8")


def report(bag: DiagnosticBag, *, label: str) -> bool:
    """Print every diagnostic, errors in red and warnings in yellow.

    Returns ``True`` when the bag holds an error, so a caller can decide the exit
    code. Nothing is printed when the bag is empty except a terse all-clear.
    """
    for diagnostic in bag:
        colour = typer.colors.RED if diagnostic.severity.value == "error" else typer.colors.YELLOW
        typer.secho(str(diagnostic), fg=colour, err=True)
    if bag.has_errors:
        n = len(bag.errors)
        typer.secho(f"{label}: {n} error{'s' if n != 1 else ''}", fg=typer.colors.RED, err=True)
        return True
    if len(bag) == 0:
        typer.secho(f"{label}: ok", fg=typer.colors.GREEN, err=True)
    return False


def resolve_aspect(value: str | None) -> Aspect | None:
    """Map a ``--aspect`` string to an :class:`Aspect`, or exit listing the choices."""
    if value is None:
        return None
    try:
        return Aspect(value)
    except ValueError:
        choices = ", ".join(a.value for a in Aspect)
        typer.secho(f"unknown aspect {value!r} (choices: {choices})", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from None


def build_provider(settings: Settings) -> LLMProvider:
    """Choose the LLM backend named in settings -- Gemini live, or cassette replay.

    ``cassette`` is the default and needs no key: it replays committed fixtures, so
    a ``build`` runs offline and deterministically. ``gemini`` requires a key. The
    ``stub`` provider has no prepared responses outside a test and is refused here.
    """
    if settings.llm_provider is LLMProviderName.GEMINI:
        return GeminiProvider(api_key=settings.gemini_key_or_raise)
    if settings.llm_provider is LLMProviderName.CASSETTE:
        inner = GeminiProvider(api_key=settings.gemini_key_or_raise) if settings.ai_record else None
        return CassetteProvider(settings.ai_cassette_dir, record=settings.ai_record, inner=inner)
    raise ConfigError(
        "the stub provider needs responses prepared in a test; set "
        "MANOREM_LLM_PROVIDER=cassette or =gemini for the CLI"
    )


def load_corpus(path: Path | None) -> tuple[Document, ...]:
    """Load a retrieved-document corpus (a JSON array) for the research provider."""
    if path is None:
        return ()
    data = json.loads(path.read_text(encoding="utf-8"))
    return tuple(Document.model_validate(item) for item in data)
