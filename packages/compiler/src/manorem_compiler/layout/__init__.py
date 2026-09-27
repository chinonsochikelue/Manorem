"""Stage-space layout: how big things are, and where they go.

Two halves, deliberately separate. :mod:`~manorem_compiler.layout.measure` answers
"how big is this?" without rendering anything, and
:mod:`~manorem_compiler.layout.solvers` answers "where does it go?" without knowing
what a frame is. Pass P3 puts them together; pass P6 is the only code that turns the
result into world units.
"""

from __future__ import annotations

from manorem_compiler.layout.measure import estimate_props_size, estimate_size, estimate_sizes
from manorem_compiler.layout.solvers import (
    BUILTIN_SOLVERS,
    DEGRADED_KINDS,
    GRID_EPS,
    LayoutRule,
    content_region,
    dispatch,
    point,
    quantize,
    slot_regions,
    solver_for,
    sub_request,
)

__all__ = [
    "BUILTIN_SOLVERS",
    "DEGRADED_KINDS",
    "GRID_EPS",
    "LayoutRule",
    "content_region",
    "dispatch",
    "estimate_props_size",
    "estimate_size",
    "estimate_sizes",
    "point",
    "quantize",
    "slot_regions",
    "solver_for",
    "sub_request",
]
