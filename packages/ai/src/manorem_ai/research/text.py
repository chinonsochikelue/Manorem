"""Deterministic text geometry: the shared answer to "where is this span?".

Both the locator's validator and the evidence extractor need to split a document
into headings and paragraphs and ask which one contains an offset. Two
implementations of that arithmetic would eventually disagree -- and a locator
that resolves one way where it was extracted another way is precisely the
``RES803`` the validator is supposed to catch -- so there is one, here.

Everything is a pure function of the string. No locale, no clock, no network:
the same bytes always produce the same splits, which is what makes an offline
replay reproduce the same locator.
"""

from __future__ import annotations

import re

__all__ = [
    "heading_at",
    "heading_starts",
    "next_heading_start",
    "paragraph_spans",
]

_HEADING_RE = re.compile(r"(?m)^(#{1,6})[ \t]+(.*?)[ \t]*$")
_BLOCK_SPLIT_RE = re.compile(r"\n[ \t]*\n")


def heading_starts(content: str) -> list[tuple[int, str]]:
    """Offsets and titles of every markdown ATX heading in ``content``."""
    return [(match.start(), match.group(2)) for match in _HEADING_RE.finditer(content)]


def heading_at(content: str, offset: int) -> tuple[int, str] | None:
    """The last heading at or before ``offset`` -- the one a span sits under."""
    prior = [heading for heading in heading_starts(content) if heading[0] <= offset]
    return prior[-1] if prior else None


def next_heading_start(content: str, offset: int) -> int:
    """Where the section containing ``offset`` ends: the next heading, or EOF."""
    following = [start for start, _ in heading_starts(content) if start > offset]
    return following[0] if following else len(content)


def paragraph_spans(content: str) -> list[tuple[int, int]]:
    """Half-open spans of each blank-line-delimited block, trimmed of padding.

    Empty blocks are dropped: a span of nothing cannot contain evidence, and
    keeping them would make every paragraph index shift whenever the document
    gained a stray blank line.
    """
    spans: list[tuple[int, int]] = []
    cursor = 0
    for match in _BLOCK_SPLIT_RE.finditer(content):
        spans.append((cursor, match.start()))
        cursor = match.end()
    spans.append((cursor, len(content)))

    trimmed: list[tuple[int, int]] = []
    for first, last in spans:
        block = content[first:last]
        left = len(block) - len(block.lstrip())
        right = len(block) - len(block.rstrip())
        if last - first - left - right > 0:
            trimmed.append((first + left, last - right))
    return trimmed
