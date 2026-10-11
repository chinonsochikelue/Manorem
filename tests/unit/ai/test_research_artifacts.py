"""Persisting research where it can actually be read.

Two properties are asserted. The run directory is laid out the way a reviewer
reads it -- request, sources, evidence, claims, manifest -- and the manifest's
digests are checked against the bytes on disk, so a stale or hand-edited artifact
cannot pass as current. And the source bodies are kept *out* of ``sources.json``:
that file is metadata, the body lives in its own content-addressed artifact, and
the difference is what keeps a webpage's worth of text out of every downstream
hash.
"""

from __future__ import annotations

import json
from pathlib import Path

from manorem_ai.research import (
    Claim,
    ResearchBrief,
    ResearchRequest,
    ResearchResult,
    SourceRef,
    extract_evidence,
    store_source_artifacts,
    write_research_artifacts,
)
from manorem_core import DiagnosticBag, LocalFSStore, sha256_of
from tests.support.ai_builders import GPS_SNIPPET, GPS_URL, gps_retrieved

IDEA = "How GPS determines your location."
QUOTE = "trilaterates its position"


def result() -> ResearchResult:
    return ResearchResult(request=ResearchRequest(topic=IDEA), retrieved=(gps_retrieved(),))


def evidenced_brief() -> ResearchBrief:
    base = ResearchBrief(
        idea=IDEA,
        claims=(
            Claim(
                id="gps_trilaterates",
                text="GPS trilaterates position from satellite timing.",
                sources=(SourceRef(url=GPS_URL, quote=QUOTE),),
            ),
        ),
    )
    return base.model_copy(update={"evidence": extract_evidence(base, result(), DiagnosticBag())})


def test_the_run_directory_is_laid_out_for_a_human(tmp_path: Path) -> None:
    store = LocalFSStore(tmp_path / "store")
    write_research_artifacts(tmp_path, evidenced_brief(), result(), provider="fixture", store=store)

    research = tmp_path / "research"
    for name in ("request.json", "sources.json", "evidence.json", "claims.json", "manifest.json"):
        assert (research / name).is_file(), f"{name} missing from the run directory"
    digest = result().sources[0].content_digest
    assert (research / "sources" / f"{digest}.json").is_file()


def test_a_source_body_is_addressed_by_its_content_not_its_url(tmp_path: Path) -> None:
    store = LocalFSStore(tmp_path / "store")
    refs = store_source_artifacts(result(), store)

    source = result().sources[0]
    assert source.artifact_key == f"research/sources/{source.content_digest}.json"
    assert [ref.key for ref in refs] == [source.artifact_key]
    # Written twice, byte for byte: the key *is* the digest of the payload.
    store_source_artifacts(result(), store)
    payload = json.loads(store.get_text(source.artifact_key))
    assert payload["content"] == GPS_SNIPPET
    assert sha256_of(payload["content"]) == source.content_digest


def test_sources_json_carries_metadata_and_never_the_body(tmp_path: Path) -> None:
    store = LocalFSStore(tmp_path / "store")
    write_research_artifacts(tmp_path, evidenced_brief(), result(), provider="fixture", store=store)

    listed = json.loads((tmp_path / "research" / "sources.json").read_text("utf-8"))
    assert [entry["url"] for entry in listed] == [GPS_URL]
    assert GPS_SNIPPET not in (tmp_path / "research" / "sources.json").read_text("utf-8")
    assert "artifact_key" in listed[0] and "content_digest" in listed[0]


def test_the_manifest_indexes_everything_it_wrote(tmp_path: Path) -> None:
    store = LocalFSStore(tmp_path / "store")
    manifest = write_research_artifacts(
        tmp_path, evidenced_brief(), result(), provider="fixture", store=store
    )

    assert manifest.provider == "fixture"  # a name, never a credential
    assert manifest.counts == {"sources": 1, "evidence": 1, "claims": 1, "links": 0}
    assert set(manifest.files) == {"request", "sources", "evidence", "claims", "manifest"}
    # Each digest is the content address of the file it names -- a reader can
    # tell whether an artifact still matches what the run produced.
    for name, relative in manifest.files.items():
        if name == "manifest":
            continue
        written = json.loads((tmp_path / "research" / relative).read_text("utf-8"))
        assert manifest.digests[name] == sha256_of(written)
    assert [ref.content_digest for ref in manifest.source_artifacts] == [
        result().sources[0].content_digest
    ]


def test_the_evidence_file_records_where_the_span_came_from(tmp_path: Path) -> None:
    store = LocalFSStore(tmp_path / "store")
    write_research_artifacts(tmp_path, evidenced_brief(), result(), provider="fixture", store=store)

    evidence = json.loads((tmp_path / "research" / "evidence.json").read_text("utf-8"))
    assert len(evidence) == 1
    assert evidence[0]["source_id"] == result().sources[0].id
    assert evidence[0]["text"] in GPS_SNIPPET
    assert evidence[0]["content_digest"] == result().sources[0].content_digest
