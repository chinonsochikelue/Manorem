"""The provider-neutral retrieval seam, and the offline backends behind it.

One protocol, :class:`ResearchProvider`, sits between the pipeline and whatever
finds sources. A provider turns a :class:`ResearchRequest` -- *what needs to be
known* -- into a :class:`ResearchResult`, and never sees an LLM, a story plan or
the Visual IR. Nothing vendor-shaped reaches the persisted artifacts: the request
carries no search syntax and the result carries no api key, header or provider
credential.

Three rules are load-bearing here:

* **Offline first.** :class:`StubResearchProvider` and
  :class:`CassetteResearchProvider` never touch the network, so content
  intelligence runs with no internet and no keys. Offline mode must never
  *silently* perform network research, which is why the cassette treats a miss as
  an error rather than a live call.
* **No fabrication.** A provider that has nothing returns nothing. It does not
  invent a URL, a title or a quotation to keep a build alive -- an empty result
  is an honest result, and a failed retrieval raises.
* **Deterministic replay.** Cassette entries are keyed on
  :func:`research_cache_key`, a pure function of the request and the provider
  identity, so the same input replays byte for byte.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol, runtime_checkable

from manorem_ai.research.models import (
    Document,
    ResearchRequest,
    ResearchResult,
    RetrievedSource,
    research_cache_key,
)
from manorem_core import ManoremError

__all__ = [
    "CassetteResearchProvider",
    "FixtureResearchProvider",
    "ResearchError",
    "ResearchProvider",
    "StubResearchProvider",
]


class ResearchError(ManoremError):
    """Retrieval could not produce a result.

    Distinct from a *claim* problem: this means the source could not be fetched
    or replayed at all. The pipeline reports it as ``RES809`` and falls back
    where a fallback is configured, or fails clearly -- it never manufactures a
    source to paper over the gap.
    """


@runtime_checkable
class ResearchProvider(Protocol):
    """A source of retrieved documents for a research request.

    M4 ships :class:`StubResearchProvider`, :class:`FixtureResearchProvider` and
    :class:`CassetteResearchProvider` plus one real opt-in backend
    (:class:`~manorem_ai.research.brave.BraveResearchProvider`) behind this same
    seam.
    """

    name: str

    #: Secret-free identity of this provider's configuration, folded into every
    #: cache key so reconfiguring a provider *misses* rather than replaying what
    #: the old configuration returned. Empty means "do not cache": the offline
    #: backends are already free, deterministic, and (for cassettes) their own
    #: cache, so a second layer would only be a second place to go stale.
    cache_identity: str

    def research(self, request: ResearchRequest) -> ResearchResult: ...

    def retrieve(self, query: str, *, limit: int = 8) -> tuple[Document, ...]:
        """The M1 retrieval seam, kept so the pipeline and corpus callers keep working.

        New code calls :meth:`research` and reads :class:`ResearchResult`;
        ``retrieve`` stays until the pipeline migrates off ``Document``.
        """
        ...


class StubResearchProvider:
    """Serve a fixed corpus, so research is offline and deterministic.

    The corpus is supplied by the caller -- a test fixture, a committed sample,
    or the ``--corpus`` file -- and is returned as-is regardless of the request,
    truncated to the request's ``max_sources``. With no corpus it returns an
    empty result: *nothing was retrieved* is a truthful answer, and inventing a
    plausible-looking document instead would be exactly the fabrication the
    provenance layer exists to prevent.
    """

    name = "stub"
    #: Already deterministic and free -- there is nothing worth reusing, and a
    #: cache in front of a fixed corpus can only ever be a second place to go stale.
    cache_identity = ""

    def __init__(self, sources: tuple[RetrievedSource, ...] = ()) -> None:
        self._sources = sources

    @property
    def sources(self) -> tuple[RetrievedSource, ...]:
        return self._sources

    def research(self, request: ResearchRequest) -> ResearchResult:
        return ResearchResult(
            request=request,
            retrieved=self._sources[: request.max_sources],
        )

    def retrieve(self, query: str, *, limit: int = 8) -> tuple[Document, ...]:  # noqa: ARG002
        """The M1 retrieval seam, kept so existing corpus callers keep working."""
        return tuple(
            Document(source=item.source, content=item.content) for item in self._sources[:limit]
        )


class FixtureResearchProvider(StubResearchProvider):
    """A named stub serving a pre-built fixture corpus.

    Identical behaviour to :class:`StubResearchProvider`; the distinct ``name``
    matters because the provider identity is part of every cache key, and two
    fixtures that shared a name would share cache entries they should not.
    """

    name = "fixture"


class CassetteResearchProvider:
    """Record/replay against a directory of research cassettes keyed by request.

    In replay a missing cassette is an error, never a live call: an offline run
    can never slip out to the network by accident. In record mode every call goes
    to ``inner`` and the validated result is written back, so refreshing the
    fixtures is one environment variable and one run.

    The entry holds the whole :class:`~manorem_ai.research.models.ResearchResult`
    -- request, sources *and* their retrieved content -- so a replay reproduces
    the exact bytes evidence will be located in, not just the metadata.
    """

    name = "cassette"
    #: The cassette *is* the cache; putting a cache in front of it would add a
    #: second thing to invalidate when the recordings are refreshed.
    cache_identity = ""

    def __init__(
        self,
        directory: Path,
        *,
        record: bool = False,
        inner: ResearchProvider | None = None,
    ) -> None:
        if record and inner is None:
            raise ResearchError("recording a research cassette needs an inner provider")
        self._dir = directory
        self._record = record
        self._inner = inner

    def _path(self, request: ResearchRequest) -> Path:
        return self._dir / f"{research_cache_key(request, provider=self.name)}.json"

    def research(self, request: ResearchRequest) -> ResearchResult:
        path = self._path(request)

        if not self._record:
            if not path.exists():
                raise ResearchError(
                    f"no research cassette at {path}; record with MANOREM_RESEARCH_RECORD=1 "
                    "or check the request has not drifted"
                )
            return ResearchResult.model_validate_json(path.read_text(encoding="utf-8"))

        assert self._inner is not None  # guaranteed by __init__
        result = self._inner.research(request)
        self._dir.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                result.model_dump(mode="json"), indent=2, ensure_ascii=False, sort_keys=True
            ),
            encoding="utf-8",
        )
        return result

    def retrieve(self, query: str, *, limit: int = 8) -> tuple[Document, ...]:
        """The M1 retrieval seam, adapted onto :meth:`research`."""
        result = self.research(ResearchRequest(topic=query, max_sources=limit))
        return tuple(
            Document(source=item.source, content=item.content) for item in result.retrieved[:limit]
        )
