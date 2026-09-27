"""Per-kind object properties.

Each object kind gets a typed props model rather than a free-form dict. The
payoff is that "a chart with no series" or "an arrow with one endpoint" is a
schema error caught before the compiler runs, not a renderer crash.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from manorem_core import Slug
from manorem_ir.geometry import StagePoint


class _Props(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TextProps(_Props):
    kind: Literal["text"] = "text"
    content: str = Field(min_length=1, max_length=500)
    role: Literal["title", "heading", "body", "caption"] = "body"
    align: Literal["left", "center", "right"] = "center"


class MathProps(_Props):
    """LaTeX math. ``latex`` is passed to Manim's ``MathTex``, which shells out to
    a TeX distribution -- the renderer length-limits it and rejects control
    sequences that could read the filesystem."""

    kind: Literal["math"] = "math"
    latex: str = Field(min_length=1, max_length=500)
    role: Literal["title", "heading", "body", "caption"] = "body"


class CircleProps(_Props):
    kind: Literal["circle"] = "circle"
    radius: float = Field(gt=0.0, le=4.0)
    filled: bool = False


class RectangleProps(_Props):
    kind: Literal["rectangle"] = "rectangle"
    width: float = Field(gt=0.0, le=4.0)
    height: float = Field(gt=0.0, le=4.0)
    corner_radius: float = Field(default=0.0, ge=0.0, le=1.0)
    filled: bool = False


class LineProps(_Props):
    kind: Literal["line"] = "line"
    start: StagePoint
    end: StagePoint
    dashed: bool = False


class ArrowProps(_Props):
    """Endpoints may be literal points or references to other objects, so an
    arrow can follow whatever the layout engine decided."""

    kind: Literal["arrow"] = "arrow"
    start: StagePoint | Slug
    end: StagePoint | Slug
    curved: bool = False
    double_headed: bool = False


class DotProps(_Props):
    kind: Literal["dot"] = "dot"
    radius: float = Field(default=0.04, gt=0.0, le=0.5)


class PolygonProps(_Props):
    kind: Literal["polygon"] = "polygon"
    points: list[StagePoint] = Field(min_length=3, max_length=64)
    filled: bool = False


class GraphNode(_Props):
    id: Slug
    label: str | None = Field(default=None, max_length=80)


class GraphEdge(_Props):
    source: Slug
    target: Slug
    label: str | None = Field(default=None, max_length=40)
    directed: bool = False


class GraphProps(_Props):
    kind: Literal["graph"] = "graph"
    nodes: list[GraphNode] = Field(min_length=1, max_length=64)
    edges: list[GraphEdge] = Field(default_factory=list, max_length=256)


class ChartSeries(_Props):
    label: str = Field(max_length=40)
    values: list[float] = Field(min_length=1, max_length=200)


class ChartProps(_Props):
    kind: Literal["chart"] = "chart"
    chart_type: Literal["bar", "line", "scatter", "area"] = "bar"
    series: list[ChartSeries] = Field(min_length=1, max_length=8)
    categories: list[str] = Field(default_factory=list, max_length=200)
    x_label: str | None = Field(default=None, max_length=40)
    y_label: str | None = Field(default=None, max_length=40)


class AxesProps(_Props):
    kind: Literal["axes"] = "axes"
    x_range: tuple[float, float, float] = (0.0, 10.0, 1.0)
    y_range: tuple[float, float, float] = (0.0, 10.0, 1.0)
    x_label: str | None = Field(default=None, max_length=40)
    y_label: str | None = Field(default=None, max_length=40)
    show_grid: bool = False


class ImageProps(_Props):
    """``asset`` is a storage key resolved through the object store, never a
    filesystem path -- the renderer refuses anything that escapes the workspace."""

    kind: Literal["image"] = "image"
    asset: str = Field(min_length=1, max_length=512)
    width: float | None = Field(default=None, gt=0.0, le=4.0)


class IconProps(_Props):
    kind: Literal["icon"] = "icon"
    name: str = Field(min_length=1, max_length=64)
    size: float = Field(default=0.2, gt=0.0, le=2.0)


class SvgProps(_Props):
    kind: Literal["svg"] = "svg"
    asset: str = Field(min_length=1, max_length=512)
    width: float | None = Field(default=None, gt=0.0, le=4.0)


class MapProps(_Props):
    kind: Literal["map"] = "map"
    region: str = Field(min_length=1, max_length=64)
    projection: Literal["equirectangular", "mercator", "orthographic"] = "equirectangular"
    show_borders: bool = True


class GlobeProps(_Props):
    kind: Literal["globe"] = "globe"
    radius: float = Field(default=1.0, gt=0.0, le=4.0)
    latitude: float = Field(default=0.0, ge=-90.0, le=90.0)
    longitude: float = Field(default=0.0, ge=-180.0, le=180.0)
    show_meridians: bool = True


class TimelineEntry(_Props):
    label: str = Field(max_length=80)
    position: float = Field(ge=0.0, le=1.0, description="Normalized position along the axis")


class TimelineProps(_Props):
    kind: Literal["timeline"] = "timeline"
    entries: list[TimelineEntry] = Field(min_length=1, max_length=40)
    orientation: Literal["horizontal", "vertical"] = "horizontal"


class DiagramProps(_Props):
    kind: Literal["diagram"] = "diagram"
    boxes: list[str] = Field(min_length=1, max_length=32)
    style: Literal["flow", "block", "layered"] = "flow"


class NetworkProps(_Props):
    """A network is a graph with routing semantics: the ``networks`` skill can
    validate that a ``flow`` follows an actual edge."""

    kind: Literal["network"] = "network"
    nodes: list[GraphNode] = Field(min_length=1, max_length=64)
    edges: list[GraphEdge] = Field(default_factory=list, max_length=256)
    topology: Literal["mesh", "star", "ring", "tree", "explicit"] = "explicit"


class ParticlesProps(_Props):
    kind: Literal["particles"] = "particles"
    count: int = Field(default=12, ge=1, le=500)
    spread: float = Field(default=0.3, gt=0.0, le=2.0)
    particle_radius: float = Field(default=0.03, gt=0.0, le=0.5)


class GroupProps(_Props):
    """A group has no geometry of its own; members supply it."""

    kind: Literal["group"] = "group"
    members: list[Slug] = Field(min_length=1, max_length=200)


ObjectProps = (
    TextProps
    | MathProps
    | CircleProps
    | RectangleProps
    | LineProps
    | ArrowProps
    | DotProps
    | PolygonProps
    | GraphProps
    | ChartProps
    | AxesProps
    | ImageProps
    | IconProps
    | SvgProps
    | MapProps
    | GlobeProps
    | TimelineProps
    | DiagramProps
    | NetworkProps
    | ParticlesProps
    | GroupProps
)
