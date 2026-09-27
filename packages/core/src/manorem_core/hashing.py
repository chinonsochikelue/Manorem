"""Canonical JSON serialization and content addressing.

Every pipeline artifact is keyed by the sha256 of its canonical form. That gives
free deduplication, cheap versioning (an unchanged script points at the same
digest) and a byte-exact determinism check for snapshot tests.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel


def canonical_json(value: Any) -> str:
    """Serialize deterministically: sorted keys, no incidental whitespace.

    Two structurally equal documents must produce identical bytes, or content
    addressing silently stops deduplicating.
    """
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_bytes(value: Any) -> bytes:
    return canonical_json(value).encode("utf-8")


def sha256_of(value: Any) -> str:
    """Content address of a JSON-serializable value or Pydantic model."""
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def short_digest(digest: str, length: int = 12) -> str:
    """Truncated digest for log lines and filenames (never for identity)."""
    return digest[:length]
