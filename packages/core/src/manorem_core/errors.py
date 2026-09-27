"""Exception hierarchy. Failures carry diagnostics, never bare strings."""

from __future__ import annotations

from manorem_core.diagnostics import Diagnostic, Severity


class ManoremError(Exception):
    """Base class for every error raised by this system."""


class ConfigError(ManoremError):
    """Settings are missing or inconsistent."""


class DiagnosticError(ManoremError):
    """A failure that carries structured, machine-actionable findings.

    The repair loop reads ``diagnostics``; the message exists for humans.
    """

    def __init__(self, message: str, diagnostics: list[Diagnostic]) -> None:
        self.diagnostics = diagnostics
        errors = [d for d in diagnostics if d.severity is Severity.ERROR]
        detail = "\n".join(f"  {d}" for d in errors[:10])
        suffix = f"\n  ... and {len(errors) - 10} more" if len(errors) > 10 else ""
        super().__init__(f"{message} ({len(errors)} error(s))\n{detail}{suffix}")


class IRValidationError(DiagnosticError):
    """Visual IR did not survive validation. It must not reach the compiler.

    Named ``IRValidationError`` rather than ``ValidationError`` so it never gets
    confused with pydantic's, which signals a different (structural) failure.
    """


class CompileError(DiagnosticError):
    """A compiler pass could not produce a valid RenderPlan."""


class RenderError(DiagnosticError):
    """The renderer subprocess failed, timed out, or rejected the plan."""


class UnsafePathError(ManoremError):
    """A path escaped its permitted root. Always a hard failure, never clamped."""
