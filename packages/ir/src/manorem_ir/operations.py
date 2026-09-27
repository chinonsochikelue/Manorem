"""Declarative signatures for semantic operations.

Validation is table-driven: adding an operation means adding a declaration, not
another branch in a growing if/elif. A skill *claims* operations from this table --
and may narrow one for its domain -- but never adds a new one: ``SemanticOp`` is a
closed enum because the exported JSON Schema enumerates it and CI gates on the
schema digest, so a vocabulary that grew at import time would make the schema a
function of which skills happened to be loaded. The IR-generation prompt is built
from these same declarations, so the model's menu and the validator's rules can
never drift apart.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from manorem_ir.enums import ObjectKind, SemanticOp

#: Sentinel meaning "any object kind is acceptable as a target".
ANY_KIND: frozenset[ObjectKind] = frozenset(ObjectKind)

_POINTLIKE = frozenset(
    {ObjectKind.DOT, ObjectKind.CIRCLE, ObjectKind.ICON, ObjectKind.IMAGE, ObjectKind.SVG}
)
_CONNECTABLE = frozenset(
    {
        ObjectKind.DOT,
        ObjectKind.CIRCLE,
        ObjectKind.RECTANGLE,
        ObjectKind.ICON,
        ObjectKind.TEXT,
        ObjectKind.IMAGE,
        ObjectKind.NETWORK,
        ObjectKind.GRAPH,
        ObjectKind.GROUP,
        ObjectKind.SVG,
        ObjectKind.POLYGON,
    }
)


class ParamDecl(BaseModel):
    """One parameter accepted by an operation."""

    model_config = ConfigDict(frozen=True)

    name: str
    type: str = Field(description="One of: number, string, bool, object_ref, point, enum")
    required: bool = False
    description: str = ""
    choices: tuple[str, ...] = ()
    default: float | str | bool | None = None


class OperationDecl(BaseModel):
    """The complete contract for a semantic operation."""

    model_config = ConfigDict(frozen=True)

    op: SemanticOp
    summary: str
    allowed_kinds: frozenset[ObjectKind] = ANY_KIND
    min_targets: int = Field(default=1, ge=0)
    max_targets: int = Field(default=1, ge=0)
    params: tuple[ParamDecl, ...] = ()
    default_duration: float = Field(default=1.0, gt=0.0)
    is_camera: bool = False
    #: True when the operation makes its targets visible. The "use before show"
    #: check depends on knowing which ops introduce an object.
    introduces: bool = False
    #: True when the operation removes its targets from the stage.
    removes: bool = False

    def required_params(self) -> tuple[str, ...]:
        return tuple(p.name for p in self.params if p.required)

    def param(self, name: str) -> ParamDecl | None:
        return next((p for p in self.params if p.name == name), None)


def _p(
    name: str,
    type_: str,
    *,
    required: bool = False,
    description: str = "",
    choices: tuple[str, ...] = (),
    default: float | str | bool | None = None,
) -> ParamDecl:
    return ParamDecl(
        name=name,
        type=type_,
        required=required,
        description=description,
        choices=choices,
        default=default,
    )


CORE_OPERATIONS: tuple[OperationDecl, ...] = (
    OperationDecl(
        op=SemanticOp.SHOW,
        summary="Bring one or more objects onto the stage.",
        min_targets=1,
        max_targets=50,
        params=(
            _p(
                "style",
                "enum",
                description="How the object appears",
                choices=("create", "write", "fade", "grow", "draw"),
                default="create",
            ),
        ),
        default_duration=1.0,
        introduces=True,
    ),
    OperationDecl(
        op=SemanticOp.HIDE,
        summary="Remove one or more objects from the stage.",
        min_targets=1,
        max_targets=50,
        params=(_p("style", "enum", choices=("fade", "shrink", "uncreate"), default="fade"),),
        default_duration=0.6,
        removes=True,
    ),
    OperationDecl(
        op=SemanticOp.CONNECT,
        summary="Draw a connection between two objects.",
        allowed_kinds=_CONNECTABLE,
        min_targets=2,
        max_targets=2,
        params=(
            _p("directed", "bool", default=False),
            _p("curved", "bool", default=False),
            _p("label", "string"),
        ),
        default_duration=0.8,
        introduces=True,
    ),
    OperationDecl(
        op=SemanticOp.DISCONNECT,
        summary="Remove the connection between two objects.",
        allowed_kinds=_CONNECTABLE,
        min_targets=2,
        max_targets=2,
        default_duration=0.6,
        removes=True,
    ),
    OperationDecl(
        op=SemanticOp.FLOW,
        summary="Show something travelling from the first target to the second.",
        allowed_kinds=_CONNECTABLE,
        min_targets=2,
        max_targets=2,
        params=(
            _p("count", "number", description="Number of travelling particles", default=3),
            _p("stagger", "number", description="Seconds between particles", default=0.2),
            _p("curved", "bool", default=False),
            _p("color", "string"),
        ),
        default_duration=1.5,
    ),
    OperationDecl(
        op=SemanticOp.COMPARE,
        summary="Place two or more objects side by side for comparison.",
        min_targets=2,
        max_targets=6,
        params=(_p("axis", "enum", choices=("horizontal", "vertical"), default="horizontal"),),
        default_duration=1.2,
    ),
    OperationDecl(
        op=SemanticOp.TRANSFORM,
        summary="Turn the first target into the second.",
        min_targets=2,
        max_targets=2,
        params=(_p("replace", "bool", description="Retire the source object", default=True),),
        default_duration=1.2,
    ),
    OperationDecl(
        op=SemanticOp.MORPH,
        summary="Smoothly reshape one object into another form.",
        min_targets=2,
        max_targets=2,
        default_duration=1.5,
    ),
    OperationDecl(
        op=SemanticOp.REVEAL,
        summary="Progressively uncover an object.",
        min_targets=1,
        max_targets=10,
        params=(_p("direction", "enum", choices=("left", "right", "up", "down"), default="left"),),
        default_duration=1.2,
        introduces=True,
    ),
    OperationDecl(
        op=SemanticOp.HIGHLIGHT,
        summary="Draw attention to an object without moving the camera.",
        min_targets=1,
        max_targets=20,
        params=(
            _p("style", "enum", choices=("pulse", "flash", "circle", "color"), default="pulse"),
            _p("color", "string"),
        ),
        default_duration=0.8,
    ),
    OperationDecl(
        op=SemanticOp.TRACE,
        summary="Draw a path, optionally following an object's motion.",
        # Includes map and globe so a route across geography is the same operation
        # as a trail behind a moving dot. Which kinds a scene may actually use is
        # gated separately, by the enabled skills' primitives (IR215) -- keeping
        # the two checks orthogonal means two packs can offer ``trace`` unchanged
        # instead of each narrowing it a different way.
        allowed_kinds=_POINTLIKE
        | {ObjectKind.LINE, ObjectKind.POLYGON, ObjectKind.MAP, ObjectKind.GLOBE},
        min_targets=1,
        max_targets=2,
        params=(_p("fade_trail", "bool", default=False),),
        default_duration=1.5,
    ),
    OperationDecl(
        op=SemanticOp.SIMULATE,
        summary="Run a domain-specific simulation supplied by a skill.",
        min_targets=1,
        max_targets=20,
        params=(_p("behaviour", "string", required=True, description="Skill-defined behaviour"),),
        default_duration=2.0,
    ),
    OperationDecl(
        op=SemanticOp.SPLIT,
        summary="Divide one object into several.",
        min_targets=2,
        max_targets=10,
        default_duration=1.2,
    ),
    OperationDecl(
        op=SemanticOp.MERGE,
        summary="Combine several objects into one.",
        min_targets=2,
        max_targets=10,
        default_duration=1.2,
    ),
    OperationDecl(
        op=SemanticOp.ACCUMULATE,
        summary="Build a quantity up over time (bars growing, values counting).",
        allowed_kinds=frozenset(
            {ObjectKind.CHART, ObjectKind.AXES, ObjectKind.TEXT, ObjectKind.MATH}
        ),
        min_targets=1,
        max_targets=4,
        params=(
            _p("to", "number", required=True, description="Final value or series index"),
            _p("from", "number", default=0),
        ),
        default_duration=2.0,
    ),
    OperationDecl(
        op=SemanticOp.PROPAGATE,
        summary="Spread an effect outward through a network or from a source.",
        allowed_kinds=_CONNECTABLE,
        min_targets=1,
        max_targets=20,
        params=(
            _p("hops", "number", description="How many steps to propagate", default=2),
            _p("color", "string"),
        ),
        default_duration=2.0,
    ),
    # --- camera operations --------------------------------------------------
    OperationDecl(
        op=SemanticOp.ZOOM_TO,
        summary="Move the camera to frame the targets.",
        min_targets=1,
        max_targets=20,
        params=(_p("padding", "number", description="Extra margin in stage units", default=0.3),),
        default_duration=1.5,
        is_camera=True,
    ),
    OperationDecl(
        op=SemanticOp.PAN_TO,
        summary="Move the camera centre without changing zoom.",
        min_targets=1,
        max_targets=20,
        default_duration=1.5,
        is_camera=True,
    ),
    OperationDecl(
        op=SemanticOp.FOCUS,
        summary="Frame the targets and de-emphasise everything else.",
        min_targets=1,
        max_targets=20,
        params=(
            _p("padding", "number", default=0.4),
            _p("dim_others", "bool", default=True),
        ),
        default_duration=1.2,
        is_camera=True,
    ),
)


class OperationRegistry:
    """Lookup table for operation declarations, composed per scene by the skill layer."""

    def __init__(self, declarations: tuple[OperationDecl, ...] = CORE_OPERATIONS) -> None:
        self._by_op: dict[SemanticOp, OperationDecl] = {d.op: d for d in declarations}

    def get(self, op: SemanticOp) -> OperationDecl | None:
        return self._by_op.get(op)

    def require(self, op: SemanticOp) -> OperationDecl:
        decl = self._by_op.get(op)
        if decl is None:
            raise KeyError(f"no declaration registered for operation {op.value!r}")
        return decl

    def register(self, decl: OperationDecl) -> None:
        """Add or replace a declaration.

        Last write wins, which is only safe because the skill layer builds a fresh
        registry per scene in a fixed order rather than mutating a shared one.
        """
        self._by_op[decl.op] = decl

    def known_ops(self) -> frozenset[SemanticOp]:
        return frozenset(self._by_op)

    def __contains__(self, op: SemanticOp) -> bool:
        return op in self._by_op


#: Default registry. Skills layer on top of this rather than replacing it.
DEFAULT_REGISTRY = OperationRegistry()
