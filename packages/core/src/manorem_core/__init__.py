"""Cross-cutting primitives shared by every Manorem package.

Nothing here knows about Manim, LLM providers, or the Visual IR -- that direction
of dependency is what keeps the package graph acyclic.
"""

from __future__ import annotations

from manorem_core.diagnostics import (
    SEMANTIC_ERROR_CODES,
    Code,
    Diagnostic,
    DiagnosticBag,
    Severity,
    pointer,
)
from manorem_core.errors import (
    CompileError,
    ConfigError,
    DiagnosticError,
    IRValidationError,
    ManoremError,
    RenderError,
    UnsafePathError,
)
from manorem_core.hashing import canonical_bytes, canonical_json, sha256_of, short_digest
from manorem_core.ids import Slug, is_valid_slug, new_run_id, slugify, validate_slug
from manorem_core.logging import bind_context, clear_context, configure_logging, get_logger
from manorem_core.settings import (
    LLMProviderName,
    RenderQuality,
    Settings,
    get_settings,
)
from manorem_core.storage import LocalFSStore, ObjectStore, validate_key

__all__ = [
    "SEMANTIC_ERROR_CODES",
    "Code",
    "CompileError",
    "ConfigError",
    "Diagnostic",
    "DiagnosticBag",
    "DiagnosticError",
    "IRValidationError",
    "LLMProviderName",
    "LocalFSStore",
    "ManoremError",
    "ObjectStore",
    "RenderError",
    "RenderQuality",
    "Settings",
    "Severity",
    "Slug",
    "UnsafePathError",
    "bind_context",
    "canonical_bytes",
    "canonical_json",
    "clear_context",
    "configure_logging",
    "get_logger",
    "get_settings",
    "is_valid_slug",
    "new_run_id",
    "pointer",
    "sha256_of",
    "short_digest",
    "slugify",
    "validate_key",
    "validate_slug",
]
