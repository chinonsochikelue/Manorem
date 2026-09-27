"""The Visual QA seam: designed in from day one, unimplemented in M1.

"The render succeeded" and "the render looks good" are different outcomes, and the
type system already keeps them apart: :class:`~manorem_renderer.RenderResult`
carries ``status`` (did it run) and ``quality`` (a
:class:`~manorem_renderer.QualityReport` or ``None`` for *not assessed*). This
module is the stage that would fill in ``quality``.

M1 ships the protocol and a no-op, nothing more. :class:`NoopVisualQA` returns
``None`` -- explicitly *not assessed*, never *assessed and fine* -- so nothing in
the pipeline can mistake an unchecked render for a verified one. The real checks
(overlap, unreadable text, density, composition, framing, hierarchy,
narration/visual mismatch, continuity) are ``VQA6xx`` diagnostics computed from the
manifest and frame samples the renderer already emits; they drop in behind this
seam without touching the pipeline's shape.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from manorem_compiler import RenderPlan
from manorem_renderer import QualityReport, RenderResult

__all__ = ["NoopVisualQA", "VisualQA"]


@runtime_checkable
class VisualQA(Protocol):
    """Assess a rendered result against its plan, or decline to.

    A real implementation returns a :class:`QualityReport` of ``VQA6xx`` findings.
    Returning ``None`` means *not assessed* -- a caller must treat that as an open
    question, exactly as it treats ``RenderResult.quality is None``.
    """

    name: str

    def assess(self, plan: RenderPlan, result: RenderResult) -> QualityReport | None: ...


class NoopVisualQA:
    """The M1 default: assess nothing, and say so by returning ``None``.

    This is the honest placeholder. It does not return an empty passing report,
    because that would claim the render was looked at and found fine. It returns
    ``None``, which every downstream reader already handles as *not assessed*.
    """

    name = "noop"

    def assess(self, plan: RenderPlan, result: RenderResult) -> QualityReport | None:  # noqa: ARG002
        return None
