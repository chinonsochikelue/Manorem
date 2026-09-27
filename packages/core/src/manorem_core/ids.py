"""Identifier rules.

IR ids are author-visible and appear in diagnostics, JSON Pointers, log lines and
filenames, so they are constrained to a conservative slug shape rather than
accepting arbitrary strings.
"""

from __future__ import annotations

import re
import secrets
from typing import Annotated

from pydantic import AfterValidator

SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,62}$")

_SLUGIFY_STRIP = re.compile(r"[^a-z0-9_]+")
_SLUGIFY_COLLAPSE = re.compile(r"_{2,}")


def is_valid_slug(value: str) -> bool:
    return SLUG_PATTERN.match(value) is not None


def validate_slug(value: str) -> str:
    if not is_valid_slug(value):
        raise ValueError(
            f"invalid id {value!r}: must match {SLUG_PATTERN.pattern} "
            "(lowercase letter, then lowercase letters/digits/underscores, max 63 chars)"
        )
    return value


#: Use for every author-supplied id field in the IR.
Slug = Annotated[str, AfterValidator(validate_slug)]


def slugify(text: str) -> str:
    """Best-effort conversion of free text to a valid slug.

    Used only for normalization of machine-generated names -- never to silently
    repair an author-supplied id, which is a semantic error the author must see.
    """
    lowered = _SLUGIFY_STRIP.sub("_", text.strip().lower())
    collapsed = _SLUGIFY_COLLAPSE.sub("_", lowered).strip("_")
    if not collapsed:
        collapsed = "item"
    if not collapsed[0].isalpha():
        collapsed = f"x_{collapsed}"
    return collapsed[:63]


def new_run_id(prefix: str = "run") -> str:
    """Opaque, sortable-enough identifier for a pipeline run or job."""
    return f"{prefix}_{secrets.token_hex(6)}"
