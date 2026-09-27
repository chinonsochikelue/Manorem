"""Concrete skill packs, and the helpers that keep them thin.

A pack is data. ``SkillPack`` is a frozen dataclass satisfying
:class:`~manorem_skills.protocol.VisualSkill` structurally, so a pack module reads
as declarations rather than as a class hierarchy.

The operation declarations live in :mod:`manorem_ir` next to the enum they range
over, and a pack references them through :func:`provide` or narrows them through
:func:`refine`. That keeps one table: a pack cannot drift from the base contract
because it never restates it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from manorem_ir import (
    DEFAULT_REGISTRY,
    LayoutKind,
    ObjectKind,
    OperationDecl,
    SceneConstraint,
    SemanticOp,
)
from manorem_skills.protocol import ExpansionRule, LayoutSolver, PrimitiveDecl

__all__ = ["SkillPack", "kinds", "provide", "refine"]


@dataclass(frozen=True, slots=True)
class SkillPack:
    """A skill expressed as declarations. Satisfies ``VisualSkill``."""

    id: str
    version: str
    summary: str
    primitives: Mapping[ObjectKind, PrimitiveDecl] = field(default_factory=dict)
    operations: Mapping[SemanticOp, OperationDecl] = field(default_factory=dict)
    constraints: Sequence[SceneConstraint] = ()
    layouts: Mapping[LayoutKind, LayoutSolver] = field(default_factory=dict)
    expansions: Mapping[SemanticOp, ExpansionRule] = field(default_factory=dict)
    prompt_fragment: str = ""
    examples: Sequence[Path] = ()


def provide(*ops: SemanticOp) -> dict[SemanticOp, OperationDecl]:
    """Offer operations exactly as the base table declares them.

    The common case: a pack claims responsibility for an operation without
    changing its contract.
    """
    return {op: DEFAULT_REGISTRY.require(op) for op in ops}


def refine(op: SemanticOp, **changes: Any) -> OperationDecl:
    """Narrow one operation's declaration for a domain.

    Re-validated rather than ``model_copy``-ed: an override is authored by hand,
    and a typo'd ``default_duration=-1`` must fail at import rather than surface
    as a negative ``run_time`` deep inside pass P4.
    """
    return OperationDecl.model_validate(DEFAULT_REGISTRY.require(op).model_dump() | changes)


def kinds(*declarations: PrimitiveDecl) -> dict[ObjectKind, PrimitiveDecl]:
    """Index primitive declarations by the kind they describe."""
    return {decl.kind: decl for decl in declarations}
