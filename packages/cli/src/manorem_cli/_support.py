"""Shared plumbing for the commands: IO, diagnostics, provider wiring.

The commands stay thin -- parse arguments, call one library function, report.
Everything reusable across them (loading a model from disk, printing a diagnostic
bag with the right exit behaviour, choosing an LLM backend from settings) lives
here so no command re-implements it and they all fail the same way.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import typer
from pydantic import BaseModel, SecretStr, ValidationError

from manorem_ai import (
    AnthropicProvider,
    CassetteProvider,
    CassetteTTSProvider,
    GeminiProvider,
    KeyPoolProvider,
    LLMProvider,
    OpenAIProvider,
    OpenAISpeechProvider,
    StubTTSProvider,
    TTSProvider,
)
from manorem_ai.research import (
    BraveResearchProvider,
    CassetteResearchProvider,
    FixtureResearchProvider,
    ResearchProvider,
    RetrievedSource,
    Source,
    StubResearchProvider,
)
from manorem_core import (
    PIPELINE_GEMINI_TOOLS,
    ConfigError,
    DiagnosticBag,
    LLMProviderName,
    ResearchProviderName,
    Settings,
    TTSProviderName,
    gemini_credentials,
    sha256_of,
)
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


def _key_or_raise(key: SecretStr | None, name: str) -> str:
    if key is None:
        raise ConfigError(
            f"MANOREM_{name.upper()}_API_KEY is not set. Set it, or use "
            "MANOREM_LLM_PROVIDER=cassette to replay recorded responses."
        )
    return key.get_secret_value()


def build_provider(settings: Settings) -> LLMProvider:
    """Choose the LLM backend named in settings.

    ``cassette`` is the default and needs no key: it replays committed fixtures, so a
    ``build`` runs offline and deterministically. ``gemini``, ``anthropic`` and
    ``openai`` require keys. ``keypool`` wraps a pool of keys for one of the backends
    with rate-limit failover. The ``stub`` provider has no prepared responses outside a
    test and is refused here.
    """
    provider = settings.llm_provider
    if provider is LLMProviderName.GEMINI:
        credentials = gemini_credentials(settings)
        credentials.validate(*PIPELINE_GEMINI_TOOLS)
        return GeminiProvider(resolver=credentials)
    if provider is LLMProviderName.ANTHROPIC:
        return AnthropicProvider(
            api_key=_key_or_raise(settings.anthropic_api_key, "anthropic"),
            base_url=settings.anthropic_base_url,
        )
    if provider is LLMProviderName.OPENAI:
        return OpenAIProvider(
            api_key=_key_or_raise(settings.openai_api_key, "openai"),
            base_url=settings.openai_base_url,
        )
    if provider is LLMProviderName.KEYPOOL:
        if not settings.keypool_key_pool:
            raise ConfigError("MANOREM_KEYPOOL_KEY_POOL is not set for keypool provider")
        pool = [{"api_key": k} for k in settings.keypool_key_pool]
        return KeyPoolProvider(
            provider_factory=GeminiProvider,
            pool=pool,
            cooldown_after_rate_limit=settings.keypool_cooldown,
        )
    if provider is LLMProviderName.CASSETTE:
        inner: LLMProvider | None = None
        if settings.ai_record:
            # Deliberately *unpinned*: every stage draws its own tool's
            # credential, so recording spend follows the same per-tool budgets
            # as a live run instead of concentrating on one key. The recorded
            # bytes do not depend on which credential paid for them.
            credentials = gemini_credentials(settings)
            credentials.validate(*PIPELINE_GEMINI_TOOLS)
            inner = GeminiProvider(resolver=credentials)
        return CassetteProvider(settings.ai_cassette_dir, record=settings.ai_record, inner=inner)
    raise ConfigError(
        "the stub provider needs responses prepared in a test; set "
        "MANOREM_LLM_PROVIDER=cassette, =gemini, =anthropic, =openai, or =keypool for the CLI"
    )


def build_tts_provider(settings: Settings) -> TTSProvider:
    """Choose the speech backend named in settings, mirroring :func:`build_provider`.

    ``stub`` is the deterministic default: it emits silent, content-addressed WAVs
    whose durations are a documented function of the text, so an offline ``build``
    gets *real measured* timing without a network. ``cassette`` replays committed
    clips (and, with ``MANOREM_TTS_RECORD=1``, records them from the real provider).
    ``openai`` is the one real provider and the only one that needs a key -- it is
    opt-in and, by invariant, never selected under ``--offline`` (the build command
    pins ``stub`` first and refuses to construct it).
    """
    provider = settings.tts_provider
    if provider is TTSProviderName.STUB:
        return StubTTSProvider()
    if provider is TTSProviderName.CASSETTE:
        inner = (
            OpenAISpeechProvider(
                api_key=_key_or_raise(settings.tts_api_key, "tts"),
                base_url=settings.tts_base_url,
                model=settings.tts_model,
            )
            if settings.tts_record
            else None
        )
        return CassetteTTSProvider(
            settings.tts_cassette_dir, record=settings.tts_record, inner=inner
        )
    if provider is TTSProviderName.OPENAI:
        return OpenAISpeechProvider(
            api_key=_key_or_raise(settings.tts_api_key, "tts"),
            base_url=settings.tts_base_url,
            model=settings.tts_model,
        )
    raise ConfigError(
        f"unknown tts provider {provider!r}; set MANOREM_TTS_PROVIDER=stub, =cassette, or =openai"
    )


def load_corpus(path: Path | None) -> tuple[RetrievedSource, ...]:
    """Load a retrieved-document corpus (a JSON array) for the research provider.

    Entries are flat ``{url, title?, snippet?, retrieved_at, content_hash?}``
    records. A declared ``content_hash`` that is not the sha256 of the snippet
    is a :class:`ConfigError`: the corpus claims bytes it does not contain. An
    absent declaration is simply derived -- an entry that is only a URL and a
    date is an empty source, not a rejection.
    """
    if path is None:
        return ()
    data = json.loads(path.read_text(encoding="utf-8"))
    return tuple(_corpus_entry(item, index) for index, item in enumerate(data))


def _corpus_entry(item: object, index: int) -> RetrievedSource:
    """One flat corpus record as a retrieved source, or a loud refusal."""
    if not isinstance(item, dict):
        raise ConfigError(f"corpus entry {index} is not an object: {item!r}")
    snippet = str(item.get("snippet", "") or "")
    declared = item.get("content_hash")
    if declared is not None and declared != sha256_of(snippet):
        raise ConfigError(
            f"corpus entry {index} declares content_hash {declared!r} which is not "
            f"the sha256 of its snippet ({sha256_of(snippet)!r})"
        )
    try:
        retrieved_at = datetime.fromisoformat(str(item["retrieved_at"]))
    except (KeyError, ValueError) as exc:
        raise ConfigError(f"corpus entry {index} needs an ISO retrieved_at: {exc}") from exc
    try:
        url = str(item["url"])
    except KeyError as exc:
        raise ConfigError(f"corpus entry {index} needs a url") from exc
    source = Source.of(
        url=url,
        content=snippet,
        title=str(item.get("title", "") or ""),
        retrieved_at=retrieved_at,
    )
    return RetrievedSource(source=source, content=snippet)


def build_research_provider(
    settings: Settings, *, corpus: Path | None, offline: bool
) -> tuple[ResearchProvider, ResearchProvider | None]:
    """Choose the retrieval backend named in settings, honouring ``--offline``.

    Offline is structural: a live backend is never constructed (so no key is
    read and no socket opens) -- a configured ``brave`` replays its cassettes
    with a notice, and asking to *record* cassettes offline is an error rather
    than a silent downgrade. Online, the live backend always carries a recorded
    fallback, so a retrieval failure stays on the record instead of inventing
    a source.
    """
    provider = settings.research_provider
    if offline:
        if settings.research_record:
            raise ConfigError(
                "cannot refresh research cassettes while --offline: "
                "recording needs the live backend"
            )
        if provider is ResearchProviderName.BRAVE:
            print(
                "offline pins research to its cassette replay; the live backend is not constructed",
                file=sys.stderr,
            )
            return CassetteResearchProvider(settings.research_cassette_dir), None
        if provider is ResearchProviderName.CASSETTE:
            return CassetteResearchProvider(settings.research_cassette_dir), None
        return FixtureResearchProvider(load_corpus(corpus)), None
    if provider is ResearchProviderName.BRAVE:
        key = _key_or_raise(settings.research_api_key, "research")
        live: ResearchProvider = BraveResearchProvider(api_key=key)
        return live, CassetteResearchProvider(settings.research_cassette_dir)
    if provider is ResearchProviderName.CASSETTE:
        if settings.research_record:
            key = _key_or_raise(settings.research_api_key, "research")
            return (
                CassetteResearchProvider(
                    settings.research_cassette_dir,
                    record=True,
                    inner=BraveResearchProvider(api_key=key),
                ),
                None,
            )
        return CassetteResearchProvider(settings.research_cassette_dir), None
    if provider is ResearchProviderName.STUB:
        return StubResearchProvider(load_corpus(corpus)), None
    return FixtureResearchProvider(load_corpus(corpus)), None
