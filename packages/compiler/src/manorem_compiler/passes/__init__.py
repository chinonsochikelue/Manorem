"""The pass pipeline: nine stages in one fixed order.

A :class:`Pass` is just a name paired with a ``run(ctx)`` function -- the name is
what the driver records in :attr:`~manorem_compiler.context.CompileContext.completed`
and what a failure report shows to say how far the compile got. Keeping the order in
one tuple here, rather than spelled out in the driver, means the sequence is a single
reviewable fact and a test can assert it covers P0 through P8 with nothing skipped.

The numbering is historical and deliberately preserved: the passes were designed as
P0-P8 and the labels are load-bearing in diagnostics and docs, so a reordering would
show up as a renamed stage rather than a silent behaviour change.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from manorem_compiler.context import CompileContext
from manorem_compiler.passes import (
    camera,
    expand,
    frame,
    layout,
    lower,
    normalize,
    resolve,
    schedule,
    verify,
)

__all__ = ["PASSES", "Pass"]


@dataclass(frozen=True, slots=True)
class Pass:
    """One stage of lowering: a label and the function that advances the context."""

    name: str
    run: Callable[[CompileContext], None]


#: The pipeline, in execution order. The driver runs these and halts at the first
#: stage after which the context holds an error.
PASSES: tuple[Pass, ...] = (
    Pass("P0 Normalize", normalize.run),
    Pass("P1 Resolve", resolve.run),
    Pass("P2 Expand", expand.run),
    Pass("P3 Layout", layout.run),
    Pass("P4 Schedule", schedule.run),
    Pass("P5 Camera", camera.run),
    Pass("P6 Frame", frame.run),
    Pass("P7 Lower", lower.run),
    Pass("P8 Verify", verify.run),
)
