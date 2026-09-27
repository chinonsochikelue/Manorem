"""Helpers for asserting on diagnostics.

Tests assert on **codes and pointers**, never on message wording: the message is
for humans and may be reworded freely, while the code and the JSON Pointer are
the machine contract that the repair agent and the inspector depend on.

:func:`error_codes` and :func:`warning_codes` exist so a test can be exact about
its own tier without becoming hostage to another one. A semantic test asserts the
error set exactly; an incidental pacing *warning* on the same fixture is not that
test's business.
"""

from __future__ import annotations

from manorem_core import Code, Diagnostic, DiagnosticBag


def error_codes(bag: DiagnosticBag) -> set[Code]:
    return {d.code for d in bag.errors}


def warning_codes(bag: DiagnosticBag) -> set[Code]:
    return {d.code for d in bag.warnings}


def rendered(bag: DiagnosticBag) -> list[str]:
    """Diagnostics as strings, so a failed assertion shows what fired, not a count."""
    return [str(d) for d in bag]


def find(bag: DiagnosticBag, code: Code) -> list[Diagnostic]:
    return [d for d in bag if d.code is code]


def only(bag: DiagnosticBag, code: Code) -> Diagnostic:
    """The single diagnostic carrying ``code``.

    Fails if there is not exactly one: a check that fires twice for one fault is
    a defect in the check, and duplicate findings would spam the repair loop.
    """
    matches = find(bag, code)
    assert len(matches) == 1, f"expected exactly one {code.value}, got {[str(d) for d in bag]}"
    return matches[0]
