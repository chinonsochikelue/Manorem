"""Reading cue parameters without trusting them.

``Cue.params`` is an open bag: the parameter tables live in ``OperationDecl``, a
skill may narrow them, and — until ``_check_cue_signature`` in the IR validator
checks *types* as well as presence — nothing has established that ``count`` is a
number rather than the string ``"three"``. Every pass that reads a param therefore
needs the same discipline, and this module is that discipline written once.

Each reader is **total**: it returns the declared default rather than raising when a
value is missing or of the wrong type. A lowering pass cannot usefully abort halfway
through building a plan, and a wrong-typed param is a validation defect to report at
the source, not a compiler crash three passes later. The consequence to be honest
about is that a mistyped param is currently *silent* here — it takes the default and
the plan renders. Closing that gap belongs in the validator, where the declaration
that says what the type should be already lives.
"""

from __future__ import annotations

from collections.abc import Mapping

from manorem_ir import ParamValue

__all__ = ["choice", "count", "flag", "number", "text"]

#: What a numeric param may arrive as. ``bool`` is included because it is an ``int``
#: in Python and excluding it would make ``True`` fall back to the default instead of
#: reading as 1 -- surprising for anyone who wrote ``{"from": true}`` by mistake, but
#: at least consistent with what the value actually is.
_Numeric = bool | int | float


def number(params: Mapping[str, ParamValue], name: str, default: float) -> float:
    """A float param, or ``default`` when absent or not a number."""
    value = params.get(name, default)
    return float(value) if isinstance(value, _Numeric) else default


def count(params: Mapping[str, ParamValue], name: str, default: int) -> int:
    """An integer param, truncated toward zero, for counts and indices."""
    return int(number(params, name, float(default)))


def flag(params: Mapping[str, ParamValue], name: str, *, default: bool) -> bool:
    """A boolean param. Keyword-only default, so a call site reads as a sentence."""
    value = params.get(name, default)
    return bool(value) if isinstance(value, _Numeric) else default


def text(params: Mapping[str, ParamValue], name: str) -> str | None:
    """A string param, or ``None`` -- which is how an optional one is expressed."""
    value = params.get(name)
    return value if isinstance(value, str) else None


def choice(
    params: Mapping[str, ParamValue], name: str, allowed: tuple[str, ...], default: str
) -> str:
    """An enum param, checked against the operation's own ``choices``.

    A value outside the declared set takes the default rather than reaching the
    renderer's factory tables, where an unknown style string would be a ``KeyError``
    at render time instead of a mildly wrong animation at compile time.
    """
    value = text(params, name)
    return value if value is not None and value in allowed else default
