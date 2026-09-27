"""The controlled visual vocabulary.

Every enum here is a closed set. That is the point: the AI chooses from a menu the
compiler is guaranteed to understand, rather than inventing terms the renderer
would have to guess at. Widening a vocabulary is a deliberate act -- add the
member, add its compiler handling, add its test.
"""

from __future__ import annotations

from enum import StrEnum


class ObjectKind(StrEnum):
    """What a thing *is*, semantically -- never which Manim class renders it."""

    TEXT = "text"
    MATH = "math"
    CIRCLE = "circle"
    RECTANGLE = "rectangle"
    LINE = "line"
    ARROW = "arrow"
    DOT = "dot"
    POLYGON = "polygon"
    GRAPH = "graph"
    CHART = "chart"
    IMAGE = "image"
    ICON = "icon"
    MAP = "map"
    GLOBE = "globe"
    TIMELINE = "timeline"
    DIAGRAM = "diagram"
    NETWORK = "network"
    PARTICLES = "particles"
    AXES = "axes"
    SVG = "svg"
    GROUP = "group"


class SemanticOp(StrEnum):
    """What should *happen*, at the level a director thinks in.

    ``flow`` means "show data moving from A to B"; the compiler decides that this
    becomes dots on a bezier path. The author never says ``MoveAlongPath``.
    """

    SHOW = "show"
    HIDE = "hide"
    CONNECT = "connect"
    DISCONNECT = "disconnect"
    FLOW = "flow"
    COMPARE = "compare"
    TRANSFORM = "transform"
    REVEAL = "reveal"
    FOCUS = "focus"
    ZOOM_TO = "zoom_to"
    PAN_TO = "pan_to"
    HIGHLIGHT = "highlight"
    TRACE = "trace"
    SIMULATE = "simulate"
    MORPH = "morph"
    SPLIT = "split"
    MERGE = "merge"
    ACCUMULATE = "accumulate"
    PROPAGATE = "propagate"


#: Operations that move the camera rather than a mobject. They lower to the
#: dedicated camera track, but live in the same timeline so ordering is explicit.
CAMERA_OPS: frozenset[SemanticOp] = frozenset(
    {SemanticOp.ZOOM_TO, SemanticOp.PAN_TO, SemanticOp.FOCUS}
)


class RelationKind(StrEnum):
    """Semantic *and* structural: layout solvers read these as graph edges, and
    some materialize geometry (``points_to`` becomes an arrow)."""

    CONNECTED_TO = "connected_to"
    PARENT_OF = "parent_of"
    FOLLOWS = "follows"
    POINTS_TO = "points_to"
    CONTAINS = "contains"
    REPRESENTS = "represents"
    DERIVED_FROM = "derived_from"


class LayoutKind(StrEnum):
    """Semantic layouts. The engine computes positions; the author states intent."""

    CENTERED = "centered"
    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"
    GRID = "grid"
    RADIAL = "radial"
    TREE = "tree"
    GRAPH = "graph"
    TIMELINE = "timeline"
    MAP = "map"
    SPLIT = "split"
    STACK = "stack"
    FLOW = "flow"
    FREEFORM = "freeform"


class Side(StrEnum):
    """Anchor direction for relative placement."""

    LEFT = "left"
    RIGHT = "right"
    ABOVE = "above"
    BELOW = "below"
    CENTER = "center"


class TransitionKind(StrEnum):
    CUT = "cut"
    FADE = "fade"
    CROSSFADE = "crossfade"
    SLIDE = "slide"


class NarrationRole(StrEnum):
    """Story beat roles. A video need not use all of them, or use them in order --
    forcing one template on every subject produces identical, boring videos."""

    HOOK = "hook"
    QUESTION = "question"
    CONTEXT = "context"
    MENTAL_MODEL = "mental_model"
    COMPLICATION = "complication"
    REVELATION = "revelation"
    PAYOFF = "payoff"
    CONCLUSION = "conclusion"


class Easing(StrEnum):
    """Named rate functions. Values match Manim's ``rate_functions`` members, but
    the mapping is made explicit in the renderer rather than assumed here."""

    LINEAR = "linear"
    SMOOTH = "smooth"
    EASE_IN = "ease_in_sine"
    EASE_OUT = "ease_out_sine"
    EASE_IN_OUT = "ease_in_out_sine"
    EASE_IN_QUAD = "ease_in_quad"
    EASE_OUT_QUAD = "ease_out_quad"
    EASE_IN_OUT_CUBIC = "ease_in_out_cubic"
    EASE_OUT_BOUNCE = "ease_out_bounce"
    EASE_OUT_ELASTIC = "ease_out_elastic"
    RUSH_INTO = "rush_into"
    RUSH_FROM = "rush_from"
    THERE_AND_BACK = "there_and_back"


class Aspect(StrEnum):
    """Target aspect ratios. Layout is authored aspect-independently and mapped
    at compile time, so one IR serves all three."""

    WIDESCREEN = "16:9"
    VERTICAL = "9:16"
    SQUARE = "1:1"

    @property
    def ratio(self) -> float:
        w, h = self.value.split(":")
        return float(w) / float(h)


class ClaimKind(StrEnum):
    """How much epistemic weight a research claim carries.

    These are *model-asserted*, not verified. Provenance validation proves a cited
    URL was retrieved; it does not prove the source supports the claim.
    """

    FACT = "fact"
    INFERENCE = "inference"
    ESTIMATE = "estimate"
    CONTESTED = "contested"
