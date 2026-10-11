"""Persisting the research artifacts where they can actually be read.

Everything the research stage produces is written twice over, for two different
readers:

* **``<workspace>/research/``** -- pretty-printed, one file per concept, in the
  order a human would read them. This is the run directory: ``request.json``,
  ``sources.json``, ``sources/<content_digest>.json``, ``evidence.json``,
  ``claims.json``, ``manifest.json``. A reviewer can answer "where did this come
  from?" without running anything.
* **the object store** -- the content-addressed copy of each source body under
  its :attr:`~manorem_ai.research.models.Source.artifact_key`, canonical bytes
  and nothing else, so two runs that retrieved the same bytes share one object.

The two are deliberately different formats. The run directory is for people
(indentation, stable ordering, a manifest naming every file); the store is for
the hashing machinery. A source's body lives *only* in these artifacts -- never
in the Visual IR and never inside ``sources.json`` -- which is what keeps a
webpage's worth of text out of the document every downstream stage hashes.

Retrieval timestamps are part of what was written, so they are part of the
digest of what was written. They are deliberately *not* part of a source's
identity: a source is identified by its content digest, not by when it was
fetched.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from manorem_ai.research.models import ResearchBrief, ResearchResult
from manorem_core import ObjectStore, Slug, canonical_bytes, sha256_of

__all__ = [
    "ResearchManifest",
    "SourceArtifactRef",
    "store_source_artifacts",
    "write_research_artifacts",
]


class SourceArtifactRef(BaseModel):
    """One line of the manifest's index into the stored source bodies."""

    model_config = ConfigDict(frozen=True)

    id: Slug
    #: Object-store key of the artifact holding this source's metadata + body.
    key: str
    #: Content digest of the body, and the filename it is filed under.
    content_digest: str


class ResearchManifest(BaseModel):
    """Index of a run's research artifacts: what exists, where, and at what digest."""

    model_config = ConfigDict(frozen=True)

    #: The provider that produced the sources. A name, never a credential.
    provider: str
    #: Logical file name -> path relative to ``<workspace>/research/``.
    files: dict[str, str] = Field(default_factory=dict)
    #: Logical file name -> sha256 of its canonical JSON.
    digests: dict[str, str] = Field(default_factory=dict)
    #: Record counts, so a glance at the manifest shows what the run actually got.
    counts: dict[str, int] = Field(default_factory=dict)
    source_artifacts: tuple[SourceArtifactRef, ...] = ()


def _write_pretty(path: Path, payload: object) -> str:
    """Write an indented, human-readable JSON file; return its canonical digest."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")
    return sha256_of(payload)


def _records(models: tuple[BaseModel, ...]) -> list[object]:
    return [model.model_dump(mode="json") for model in models]


def store_source_artifacts(
    result: ResearchResult, store: ObjectStore
) -> tuple[SourceArtifactRef, ...]:
    """Content-address each retrieved body into ``store``, under its declared key.

    Called the moment retrieval finishes -- before anything is validated against
    the store -- because a validator asked to check artifacts that have not been
    written yet can only report that they are missing. Idempotent: writing the
    same bytes twice is a no-op by construction, since the key is the digest of
    what is being written.
    """
    refs: list[SourceArtifactRef] = []
    for retrieved in result.retrieved:
        source = retrieved.source
        payload = {"source": source.model_dump(mode="json"), "content": retrieved.content}
        store.put_bytes(source.artifact_key, canonical_bytes(payload))
        refs.append(
            SourceArtifactRef(
                id=source.id,
                key=source.artifact_key,
                content_digest=source.content_digest,
            )
        )
    return tuple(refs)


def write_research_artifacts(
    workspace: Path,
    brief: ResearchBrief,
    result: ResearchResult,
    *,
    provider: str,
    store: ObjectStore,
) -> ResearchManifest:
    """Write ``<workspace>/research/*`` and content-address each body in ``store``.

    ``brief`` is the research stage's artifact as the pipeline holds it: its
    claims already carry the evidence links and derived statuses. The manifest
    records that relationship in its digests rather than re-stating the claims,
    so ``claims.json`` and ``brief.json`` can never drift into disagreeing.
    """
    root = workspace / "research"
    files: dict[str, str] = {}
    digests: dict[str, str] = {}

    files["request"] = "request.json"
    digests["request"] = _write_pretty(
        root / "request.json", result.request.model_dump(mode="json")
    )

    files["sources"] = "sources.json"
    digests["sources"] = _write_pretty(root / "sources.json", _records(result.sources))

    refs = store_source_artifacts(result, store)
    seen: set[str] = set()
    for retrieved in result.retrieved:
        source = retrieved.source
        if source.content_digest in seen:
            continue
        seen.add(source.content_digest)
        _write_pretty(
            root / f"sources/{source.content_digest}.json",
            {"source": source.model_dump(mode="json"), "content": retrieved.content},
        )

    files["evidence"] = "evidence.json"
    digests["evidence"] = _write_pretty(root / "evidence.json", _records(brief.evidence))

    files["claims"] = "claims.json"
    digests["claims"] = _write_pretty(root / "claims.json", _records(brief.claims))

    manifest = ResearchManifest(
        provider=provider,
        files={**files, "manifest": "manifest.json"},
        digests=digests,
        counts={
            "sources": len(result.retrieved),
            "evidence": len(brief.evidence),
            "claims": len(brief.claims),
            "links": sum(len(claim.evidence) for claim in brief.claims),
        },
        source_artifacts=tuple(refs),
    )
    # The manifest names itself but cannot carry its own digest -- that would be
    # self-referential. Callers hash the whole manifest into their run digests.
    _write_pretty(root / "manifest.json", manifest.model_dump(mode="json"))
    return manifest
