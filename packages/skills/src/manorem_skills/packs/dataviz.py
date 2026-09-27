"""The ``dataviz`` pack: quantities, and watching them change.

Four kinds and one operation. The kinds are the frames a number gets shown in --
``axes`` for the coordinate system, ``chart`` for the marks drawn against it,
``timeline`` when the axis is time, ``diagram`` when the structure matters more
than the scale. The operation is ``accumulate``: a value building up rather than
appearing at its final size, which is the difference between a chart that explains
and a chart that is merely displayed.

The constraint below exists because ``accumulate`` is the one operation whose
parameters can be individually valid and jointly pointless.
"""

from __future__ import annotations

from dataclasses import dataclass

from manorem_core import Code, DiagnosticBag
from manorem_ir import ObjectKind, ParamValue, Scene, SemanticOp
from manorem_skills.pack import SkillPack, kinds, provide
from manorem_skills.protocol import PrimitiveDecl


def _as_number(value: ParamValue) -> float | None:
    """Read a param as a number, or ``None`` when it is some other type.

    ``bool`` is excluded before the ``int`` test on purpose: ``True`` is an ``int``
    in Python, and ``accumulate(to=True)`` is a mistake, not a request to grow to 1.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


@dataclass(frozen=True, slots=True)
class AccumulationGoesSomewhere:
    """``IR209``: an accumulation must have a numeric destination it actually moves to.

    Two failures, both of which pass every other check. A non-numeric ``to`` is a
    valid ``ParamValue`` and satisfies ``IR211``'s presence test -- nothing in the
    IR package compares a param against its ``ParamDecl.type`` yet, so without this
    the cue would reach the compiler with ``to="twelve"``. And a ``to`` equal to
    ``from`` is individually valid in every field while rendering as a bar sitting
    motionless for two seconds: almost always the value copied into both fields, or
    ``from`` left at its default when the series starts elsewhere.
    """

    @property
    def id(self) -> str:
        return "dataviz.accumulation_goes_somewhere"

    def check(self, scene: Scene, bag: DiagnosticBag, base: str) -> None:
        for index, cue in enumerate(scene.timeline):
            if cue.op is not SemanticOp.ACCUMULATE:
                continue
            pointer = f"{base}/timeline/{index}/params"
            if "to" not in cue.params:
                continue  # IR211's finding; one defect, one diagnostic.
            target = _as_number(cue.params["to"])
            if target is None:
                bag.add(
                    Code.IR209_UNSATISFIED_SKILL_CONSTRAINT,
                    f"cue {cue.id!r}: accumulate needs a numeric 'to', got {cue.params['to']!r}",
                    pointer=pointer,
                    scene_id=scene.id,
                    hint="Give 'to' the final value as a number.",
                )
                continue
            raw_start = cue.params.get("from")
            start = 0.0 if raw_start is None else _as_number(raw_start)
            if start is None:
                bag.add(
                    Code.IR209_UNSATISFIED_SKILL_CONSTRAINT,
                    f"cue {cue.id!r}: accumulate needs a numeric 'from', got {raw_start!r}",
                    pointer=pointer,
                    scene_id=scene.id,
                    hint="Give 'from' the starting value as a number, or omit it to start at 0.",
                )
                continue
            if target == start:
                bag.add(
                    Code.IR209_UNSATISFIED_SKILL_CONSTRAINT,
                    f"cue {cue.id!r}: accumulate from {start} to {target} does not move",
                    pointer=pointer,
                    scene_id=scene.id,
                    hint=(
                        "Set 'to' to the value being built up to, or drop the cue and "
                        "show the object at its final value instead."
                    ),
                )


_PROMPT = """\
The `dataviz` vocabulary shows quantities.

Objects: `axes` for the coordinate system, `chart` for bars/lines/points drawn
against it, `timeline` when the axis is time, `diagram` when structure matters
more than scale.

Operations: `accumulate` to build a value up over time -- give it `to` (the final
value) and optionally `from` (the starting value, default 0).

Use `accumulate` when the growth is the point; use `show` when the finished chart
is the point. An `accumulate` whose `to` equals its `from` is rejected: it would
render as a motionless bar.
"""

DATAVIZ = SkillPack(
    id="dataviz",
    version="1.0",
    summary="Axes, charts, timelines, and quantities that build up.",
    primitives=kinds(
        PrimitiveDecl(
            kind=ObjectKind.AXES,
            summary="A coordinate system with labelled ranges.",
            prompt_hint="Declare the ranges; the chart references this object.",
        ),
        PrimitiveDecl(
            kind=ObjectKind.CHART,
            summary="Marks drawn against axes: bars, lines, points.",
        ),
        PrimitiveDecl(
            kind=ObjectKind.TIMELINE,
            summary="A sequence of events along a time axis.",
            prompt_hint="Use when the ordering is the point; use `axes` when the values are.",
        ),
        PrimitiveDecl(
            kind=ObjectKind.DIAGRAM,
            summary="A labelled structural figure: boxes, layers, flows.",
        ),
    ),
    operations=provide(SemanticOp.ACCUMULATE),
    constraints=(AccumulationGoesSomewhere(),),
    prompt_fragment=_PROMPT,
)
