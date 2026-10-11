"""Record the LLM cassettes that make ``manorem build --offline`` runnable.

``--offline`` pins the cassette LLM provider, which replays recorded responses
from ``tests/fixtures/cassettes/``. That directory ships empty -- recording needs
a live key -- so a fresh checkout cannot run a full offline build: the pipeline
dies at the first stage with ``no cassette for ResearchBrief``.

This script fills the gap. For each registered example it runs ``manorem build``
twice:

1. **record** -- against a real Gemini backend with ``MANOREM_AI_RECORD=1``, which
   writes one ``<hash>.json`` per LLM call into ``tests/fixtures/cassettes/``.
2. **verify** -- with ``--offline`` and the key removed, proving the recording
   replays with no network.

``--research`` records the content-intelligence run instead, whose prompts include
the ``EvidenceAssessment`` stage that a plain build never reaches. Research
*retrieval* stays on the offline fixture provider either way, so only the LLM is
live.

The cassette key is ``hash(prompt, schema, model)``, so a recording is valid only
for the exact idea, corpus and model recorded here. Change a prompt template or
the model (default ``gemini-3.8-flash``) and the fixtures must be refreshed by
re-running this script. Only Gemini is wired as the recording backend (see
:func:`manorem_cli._support.build_provider`), so Gemini credentials are required
even though replay later needs none -- each stage bills its own tool, the same
central resolver deciding which variable that is, so ``MANOREM_GEMINI_APIKEY``
in shared mode or the per-tool ``MANOREM_<TOOL>_GEMINI_APIKEY`` variables in
dedicated mode. Audio never calls the LLM,
so ``--no-audio`` here is enough: offline ``--audio --tts stub`` builds replay
from the same cassettes.

Usage::

    MANOREM_GEMINI_APIKEY=... uv run python scripts/record_cassettes.py
    MANOREM_GEMINI_APIKEY=... uv run python scripts/record_cassettes.py --no-verify
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from manorem_core import (
    PIPELINE_GEMINI_TOOLS,
    ConfigError,
    Settings,
    gemini_credentials,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
CASSETTE_DIR = REPO_ROOT / "tests" / "fixtures" / "cassettes"


@dataclass(frozen=True)
class Example:
    """One idea to record a complete cassette set for.

    ``corpus`` is an optional JSON array of retrieved documents (the same file the
    ``--corpus`` flag takes); ``extra_flags`` records build flags whose LLM calls
    should also be captured, and which the offline replay then has to reproduce
    (e.g. ``("--vqa",)`` so offline ``--vqa`` builds replay, or ``("--research",)``
    so the evidence stage has a cassette of its own).
    """

    idea: str
    corpus: Path | None = None
    extra_flags: tuple[str, ...] = ()


# The ideas whose offline builds we guarantee. Add a row (and commit the resulting
# cassettes) to make another idea runnable offline. The research run is a separate
# row on purpose: evidence assessment and a claim-aware story/script are calls a
# plain build never makes, so they need their own recording.
EXAMPLES: tuple[Example, ...] = (
    Example("How GPS determines your location."),
    Example("How GPS determines your location.", extra_flags=("--research",)),
)


def _manorem_cmd() -> list[str]:
    """Resolve the ``manorem`` entry point, or explain how to get one."""
    override = os.environ.get("MANOREM_BIN")
    if override:
        return [override]
    found = shutil.which("manorem")
    if found is None:
        sys.exit(
            "error: 'manorem' not on PATH -- run this through the project venv, "
            "e.g. `uv run python scripts/record_cassettes.py`, or set MANOREM_BIN."
        )
    return [found]


def _run(cmd: list[str], env: dict[str, str], label: str) -> None:
    """Run one build; abort the script with its exit code on failure."""
    print(f"\n==> {label}: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=REPO_ROOT, env=env, check=False)
    if result.returncode != 0:
        sys.exit(f"{label} failed with exit code {result.returncode}")


def record(example: Example, manorem: list[str]) -> None:
    """Record a full cassette set for one example against the live backend."""
    env = dict(os.environ)
    env["MANOREM_AI_RECORD"] = "1"
    env["MANOREM_LLM_PROVIDER"] = "cassette"  # force the record wrapper over any .env provider
    # Record greedily deterministic: a cassette is a frozen fixture, and temperature
    # 0 both steadies the output chain run-to-run (each stage's prompt embeds the
    # previous stage's output, so drift cascades into new cassette keys) and tends to
    # produce tighter patches that are less likely to hit the output ceiling.
    env["MANOREM_LLM_TEMPERATURE"] = "0"
    with tempfile.TemporaryDirectory() as tmp:
        args = ["build", example.idea, "--no-audio", "-o", str(Path(tmp) / "record")]
        if example.corpus is not None:
            args += ["--corpus", str(example.corpus)]
        args += list(example.extra_flags)
        _run(manorem + args, env, f"record {example.idea!r}")


def verify(example: Example, manorem: list[str]) -> None:
    """Replay the recorded set with ``--offline`` -- proof it needs no live backend.

    ``--offline`` pins the cassette provider and we force recording off, so
    ``build_provider`` constructs no inner provider: the run cannot reach the
    network by construction, whatever the ``.env`` names.
    """
    env = dict(os.environ)
    env["MANOREM_AI_RECORD"] = "false"
    with tempfile.TemporaryDirectory() as tmp:
        args = ["build", example.idea, "--no-audio", "--offline", "-o", str(Path(tmp) / "verify")]
        if example.corpus is not None:
            args += ["--corpus", str(example.corpus)]
        args += list(example.extra_flags)
        _run(manorem + args, env, f"verify (offline) {example.idea!r}")


def _count_cassettes() -> int:
    return len(list(CASSETTE_DIR.glob("*.json"))) if CASSETTE_DIR.exists() else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Record LLM cassettes for offline builds.")
    parser.add_argument(
        "--no-verify", action="store_true", help="Skip the offline replay check after recording."
    )
    args = parser.parse_args()

    # Recording bills every stage to its own tool, so validate the credentials
    # a run will actually spend -- and let the resolver name the variables for
    # whatever key mode is configured, instead of assuming a spelling.
    try:
        gemini_credentials(Settings()).validate(*PIPELINE_GEMINI_TOOLS)
    except ConfigError as exc:
        sys.exit(f"error: {exc}\nRecording calls Gemini live; replay afterwards needs no key.")

    manorem = _manorem_cmd()
    before = _count_cassettes()
    for example in EXAMPLES:
        record(example, manorem)
        if not args.no_verify:
            verify(example, manorem)
    after = _count_cassettes()

    print(f"\ncassettes in {CASSETTE_DIR.relative_to(REPO_ROOT)}: {before} -> {after}")
    print("commit the new *.json files to make the offline build runnable for everyone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
