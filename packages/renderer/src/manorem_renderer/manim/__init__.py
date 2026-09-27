"""The fixed module a Manim subprocess executes -- and the only executable code
on the render path.

:mod:`~manorem_renderer.manim.plan_scene` holds :class:`PlanScene`, the
interpreter that reads a :class:`~manorem_compiler.RenderPlan` and plays it. There
is intentionally nothing else here: no code generation, no ``exec``, no plan-built
strings. The renderer names this module by dotted path when it invokes ``manim``,
so keeping the package thin keeps the attack surface a single, reviewable file.
"""

from __future__ import annotations

from manorem_renderer.manim.plan_scene import (
    MOBJECT_FACTORIES,
    PlanScene,
    build_animation,
    build_mobject,
    load_plan,
)

__all__ = ["MOBJECT_FACTORIES", "PlanScene", "build_animation", "build_mobject", "load_plan"]
