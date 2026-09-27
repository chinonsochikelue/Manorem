"""P7 Lower: symbolic intent becomes a concrete, finished scene plan.

The compiler's last semantic decision. Everything upstream is still symbolic in one
way or another -- a ``show`` that has not chosen between ``Create`` and ``Write``, a
``flow`` still naming its endpoints, a position in stage space. This pass spends all
of that: :func:`~manorem_compiler.lower.build_scene_plan` lowers every object to a
drawable, every step to an animation, and writes the result onto
:attr:`~manorem_compiler.context.SceneWork.plan_`.

The work itself lives in :mod:`manorem_compiler.lower`; this module is only the pass
adapter, so the lowering is unit-testable a scene at a time without a whole compile.
"""

from __future__ import annotations

from manorem_compiler.context import CompileContext
from manorem_compiler.lower import build_scene_plan

__all__ = ["run"]


def run(ctx: CompileContext) -> None:
    for work in ctx.scenes:
        work.plan_ = build_scene_plan(ctx, work)
