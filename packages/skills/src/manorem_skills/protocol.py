"""What a Visual Skill contributes, and the shapes its contributions take.

A skill is not a plugin that can do anything. ``ObjectKind`` and ``SemanticOp``
are closed enums in :mod:`manorem_ir`, and they stay closed: the JSON Schema
export enumerates them, CI gates on ``schema_digest``, and the renderer's factory
tables are keyed by them. A vocabulary that grew at import time would make the
exported schema a function of which skills happened to be loaded -- so a skill
**claims and specializes** part of the fixed vocabulary rather than extending it.

That is not a limitation worked around; it is the design. When a planner wants
something the vocabulary cannot express, the answer is a ``CMP402`` unsupported
intent diagnostic -- a product signal naming the gap -- not a silently invented
operation that no renderer can execute.

Five things a skill contributes:

* ``primitives`` -- which object kinds it provides, feeding the ``IR215`` check;
* ``operations`` -- the declarations for the ops it offers, read by the validator,
  by duration resolution, and by the IR-generation prompt, so the model's menu
  and the validator's rules cannot drift apart;
* ``constraints`` -- ``IR209`` predicates encoding domain rules the IR package
  cannot know ("a flow must follow an existing connection");
* ``layouts`` -- solvers for the layout kinds it understands, called by pass P3;
* ``expansions`` -- P2 macros lowering one semantic cue into primitive steps.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from manorem_ir import (
    Cue,
    LayoutKind,
    LayoutSpec,
    ObjectKind,
    ObjectProps,
    OperationDecl,
    ParamValue,
    Relationship,
    Scene,
    SceneConstraint,
    SemanticOp,
    StageBounds,
    StagePoint,
    StageSize,
)

__all__ = [
    "ExpandedStep",
    "Expansion",
    "ExpansionRule",
    "LayoutRequest",
    "LayoutSolver",
    "PrimitiveDecl",
    "SyntheticObject",
    "VisualSkill",
]


@dataclass(frozen=True, slots=True)
class PrimitiveDecl:
    """One object kind a skill provides, with the prose the prompt needs.

    The declaration exists so a kind is never merely *allowed*: whoever enabled
    the skill can see what it is for, and the IR-generation prompt describes it
    in the same words the validator will enforce.
    """

    kind: ObjectKind
    summary: str
    prompt_hint: str = ""


@dataclass(frozen=True, slots=True)
class LayoutRequest:
    """Everything a layout solver is given, and nothing it must measure itself.

    ``sizes`` arrives already resolved because measuring a text mobject means
    asking the renderer -- a skill solver must stay a pure function of numbers so
    pass P3 remains deterministic and snapshot-testable.
    """

    spec: LayoutSpec
    region: StageBounds
    object_ids: tuple[str, ...]
    sizes: Mapping[str, StageSize]
    #: Tree and graph solvers read edges to decide structure rather than order.
    relationships: tuple[Relationship, ...] = ()
    #: Any solver needing randomness takes it from here, never from the clock.
    seed: int = 0


@runtime_checkable
class LayoutSolver(Protocol):
    """Places objects inside a region. Called by pass P3, once per scene."""

    @property
    def kind(self) -> LayoutKind:
        """The layout kind this solver answers for."""
        ...

    def solve(self, request: LayoutRequest) -> Mapping[str, StagePoint]:
        """Return a stage-space centre per object id.

        Must be total over ``request.object_ids`` and deterministic: the same
        request always yields the same positions, or committed RenderPlan goldens
        stop being a regression gate.
        """
        ...


@dataclass(frozen=True, slots=True)
class SyntheticObject:
    """An object an expansion invents -- a travelling packet, a trail segment.

    Not authored, so it carries no placement: pass P2 emits it already positioned
    by the expansion, or positioned by the step that moves it.
    """

    id: str
    kind: ObjectKind
    props: ObjectProps
    at: StagePoint | None = None


@dataclass(frozen=True, slots=True)
class ExpandedStep:
    """One primitive step, timed relative to the cue that produced it.

    ``offset`` and ``duration`` are **fractions of the cue's own window**, in
    ``[0, 1]``: ``offset=0.0, duration=1.0`` fills the cue exactly. A rule cannot
    work in seconds because a cue's length may come from a narration segment,
    which is resolved in pass P1 -- after the vocabulary a rule is written against
    but before the rule runs. Pass P2 multiplies by the resolved duration and
    quantizes; nothing downstream sees a fraction.

    Offsets are explicit rather than implied by a ``lag_ratio``, because anything
    time-addressable has to survive frame quantization -- an animation with
    internal non-linear timing cannot be scheduled against narration.
    """

    target_id: str
    op: SemanticOp
    offset: float
    duration: float
    params: Mapping[str, ParamValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Expansion:
    """The result of lowering one semantic cue into primitive steps."""

    objects: tuple[SyntheticObject, ...] = ()
    steps: tuple[ExpandedStep, ...] = ()


@runtime_checkable
class ExpansionRule(Protocol):
    """Lowers one semantic operation into primitive steps during pass P2."""

    @property
    def op(self) -> SemanticOp:
        """The operation this rule expands."""
        ...

    def expand(self, cue: Cue, scene: Scene) -> Expansion:
        """Return the steps and synthetic objects realizing ``cue``.

        Pure: no I/O, no clock, no randomness outside the scene's own seed.
        """
        ...


@runtime_checkable
class VisualSkill(Protocol):
    """A domain vocabulary, its rules, and the prose that teaches a model to use it."""

    @property
    def id(self) -> str:
        """Stable identifier, as written in ``Scene.skills``."""
        ...

    @property
    def version(self) -> str: ...

    @property
    def summary(self) -> str: ...

    @property
    def primitives(self) -> Mapping[ObjectKind, PrimitiveDecl]:
        """Object kinds this skill provides."""
        ...

    @property
    def operations(self) -> Mapping[SemanticOp, OperationDecl]:
        """Every operation this skill offers, with the declaration to enforce."""
        ...

    @property
    def constraints(self) -> Sequence[SceneConstraint]:
        """``IR209`` predicates for rules only this domain knows."""
        ...

    @property
    def layouts(self) -> Mapping[LayoutKind, LayoutSolver]: ...

    @property
    def expansions(self) -> Mapping[SemanticOp, ExpansionRule]: ...

    @property
    def prompt_fragment(self) -> str:
        """Instructions injected into the IR-generation prompt."""
        ...

    @property
    def examples(self) -> Sequence[Path]:
        """Authored IR used both as few-shot examples and as a test corpus."""
        ...
