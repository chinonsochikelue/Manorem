"""Layout solvers: the table is complete, and every solver is total.

Two properties matter for P3 and nothing else here (composition quality is a Visual
QA concern, not a solver contract). First, **every** ``LayoutKind`` has a built-in
solver -- a kind added to the enum with no solver would raise ``KeyError`` deep in a
compile instead of failing loudly. Second, a solver must place **every** object it
is handed: a missing id becomes a mobject with no position three passes later.

Finiteness needs no test -- :class:`StagePoint` validates its own bounds, so a solver
cannot return a non-finite or off-stage centre without the model rejecting it.
"""

from __future__ import annotations

import pytest

from manorem_compiler.layout import BUILTIN_SOLVERS
from manorem_ir import LayoutKind, LayoutSlot, LayoutSpec
from manorem_ir.geometry import StageBounds, StageSize
from manorem_skills import LayoutRequest

_REGION = StageBounds(min_x=-1.0, min_y=-1.0, max_x=1.0, max_y=1.0)
_IDS = ("a", "b", "c")
_SIZES = {object_id: StageSize(width=0.3, height=0.2) for object_id in _IDS}


def _spec_for(kind: LayoutKind) -> LayoutSpec:
    if kind is LayoutKind.SPLIT:
        return LayoutSpec(kind=kind, slots=[LayoutSlot(name="left"), LayoutSlot(name="right")])
    return LayoutSpec(kind=kind)


def test_every_layout_kind_has_a_solver() -> None:
    assert set(BUILTIN_SOLVERS) == set(LayoutKind)


@pytest.mark.parametrize("kind", list(LayoutKind))
def test_solver_places_every_object(kind: LayoutKind) -> None:
    request = LayoutRequest(spec=_spec_for(kind), region=_REGION, object_ids=_IDS, sizes=_SIZES)
    placed = BUILTIN_SOLVERS[kind].solve(request)
    assert set(placed) == set(_IDS)


@pytest.mark.parametrize("kind", list(LayoutKind))
def test_solver_is_deterministic(kind: LayoutKind) -> None:
    request = LayoutRequest(spec=_spec_for(kind), region=_REGION, object_ids=_IDS, sizes=_SIZES)
    solver = BUILTIN_SOLVERS[kind]
    assert solver.solve(request) == solver.solve(request)
