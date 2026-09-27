"""Built-in expansions: one semantic cue becomes several primitive steps.

A skill may supply an :class:`~manorem_skills.ExpansionRule` for any operation, and
pass P2 prefers it. None of the shipped packs do, because these rules are not
domain knowledge -- "a flow is some dots travelling along a path" is true of a
network, a supply chain and a nerve fibre alike. So they live here, in the
compiler, and a pack overrides one only when its domain really does disagree.

Two invariants hold for every rule in this module, and the whole design of P2
depends on them.

**No geometry.** An expansion runs *before* layout, so it cannot know where
anything is. A travelling particle's path is recorded symbolically -- ``{"from":
"phone", "to": "satellite"}`` -- and pass P7 turns that into world coordinates
once P3 and P6 have decided what they mean. A rule that computed a midpoint here
would be computing it from positions that do not exist yet.

**No overlapping steps on one target.** Two events on the same target in the same
lane become ``Succession(Wait(gap), ...)`` in the renderer, and a negative gap
silently shifts everything after it. Every rule below emits sequential steps per
target; P7 splits genuinely-concurrent events across lanes, but a rule that can
avoid needing that should.

One operation that looks like it belongs here does not: ``focus`` dims everything
it is not focusing on, and *which* objects those are depends on what is on stage
when the cue fires. A rule sees one cue and its scene, never the running state, so
that part of ``focus`` is P2's own work and the camera part is P5's.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from manorem_compiler.params import choice, count, flag, number, text
from manorem_ir import (
    ORIGIN,
    ArrowProps,
    Cue,
    DotProps,
    LineProps,
    ObjectKind,
    ParamValue,
    RelationKind,
    Scene,
    SemanticOp,
)
from manorem_skills import ExpandedStep, Expansion, ExpansionRule, SyntheticObject

__all__ = [
    "BUILTIN_EXPANSIONS",
    "NEEDS_SKILL",
    "ExpandFn",
    "adjacency",
    "connection_id",
    "expansion_for",
    "flow_steps",
]

#: Fraction of a flow's duration one particle spends in flight. The remainder is
#: spread over the stagger, so the last particle still lands before the cue ends.
_FLIGHT = 0.7

#: Seconds a particle spends appearing and disappearing. Short enough to read as
#: "it was already moving", long enough not to pop.
_PARTICLE_FADE = 0.12


def connection_id(source: str, target: str) -> str:
    """Deterministic id for the link object a ``connect`` cue invents.

    Derived from the pair rather than the cue, and order-independent, so a later
    ``disconnect`` between the same two objects finds the same link without the
    author having to name it -- and two ``connect`` cues for one pair cannot
    produce two overlapping lines.

    The double underscore keeps it outside the ``Slug`` grammar, so a synthetic id
    can never collide with an authored one.
    """
    first, second = sorted((source, target))
    return f"link__{first}__{second}"


#: What every rule in this module is: a pure function of a cue and its scene.
ExpandFn = Callable[[Cue, Scene], Expansion]

#: What :func:`_link_props` decides: the kind of a connection and the props to match.
_LinkParts = tuple[ObjectKind, ArrowProps | LineProps]


class _Rule:
    """Adapter turning a plain function into an :class:`ExpansionRule`.

    Same reasoning as ``LayoutRule`` in the layout package: a one-method class per
    operation would bury a dozen short functions in ceremony.
    """

    __slots__ = ("_expand", "_op")

    def __init__(self, op: SemanticOp, expand: ExpandFn) -> None:
        self._op = op
        self._expand = expand

    @property
    def op(self) -> SemanticOp:
        return self._op

    def expand(self, cue: Cue, scene: Scene) -> Expansion:
        return self._expand(cue, scene)


# ---------------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------------


def _link_props(source: str, target: str, *, directed: bool, curved: bool) -> _LinkParts:
    """Kind and props for a connection between two objects.

    A directed link is an ``arrow``, whose props may hold object references
    directly, so its geometry is self-describing. An undirected one is a ``line``,
    whose props demand literal points -- the origin stands in, and the endpoint
    references travel in the step's ``from``/``to`` params, which is where P7 looks
    for a flow's endpoints as well. One resolution path, not two.
    """
    if directed:
        return ObjectKind.ARROW, ArrowProps(start=source, end=target, curved=curved)
    return ObjectKind.LINE, LineProps(start=ORIGIN, end=ORIGIN)


def _expand_connect(cue: Cue, _scene: Scene) -> Expansion:
    """A link object, plus the ``show`` that draws it."""
    source, target = cue.targets[0], cue.targets[1]
    link = connection_id(source, target)
    directed = flag(cue.params, "directed", default=False)
    curved = flag(cue.params, "curved", default=False)
    kind, props = _link_props(source, target, directed=directed, curved=curved)
    params: dict[str, ParamValue] = {
        "style": "create",
        "from": source,
        "to": target,
        "curved": curved,
    }
    label = text(cue.params, "label")
    if label is not None:
        params["label"] = label
    return Expansion(
        objects=(SyntheticObject(id=link, kind=kind, props=props),),
        steps=(
            ExpandedStep(
                target_id=link, op=SemanticOp.SHOW, offset=0.0, duration=1.0, params=params
            ),
        ),
    )


def _expand_disconnect(cue: Cue, _scene: Scene) -> Expansion:
    """Un-draw the link ``connect`` invented -- and invent nothing if there is none.

    A ``disconnect`` naming a pair that was never connected produces no steps here.
    Pass P2 turns that into ``CMP402``: the author asked for something the scene
    cannot express, and inventing a line to remove would hide it.
    """
    link = connection_id(cue.targets[0], cue.targets[1])
    return Expansion(
        steps=(
            ExpandedStep(
                target_id=link,
                op=SemanticOp.HIDE,
                offset=0.0,
                duration=1.0,
                params={"style": "uncreate"},
            ),
        )
    )


# ---------------------------------------------------------------------------
# Things that travel
# ---------------------------------------------------------------------------

#: Most particles a single flow may emit. A cue asking for hundreds would put
#: hundreds of mobjects and three times as many events into the plan; the cap is
#: enforced rather than reported because ``count`` is already bounded in spirit by
#: the operation's own declaration and clamping it changes nothing an author can see.
_MAX_PARTICLES = 24


def flow_steps(
    source: str, target: str, particle: str, *, lead: float, curved: bool, color: str | None
) -> tuple[ExpandedStep, ...]:
    """One particle's whole life: appear, travel, vanish -- in that order.

    Sequential rather than overlapping, and that is the point. A lane is played as
    ``Succession(Wait(gap), anim, ...)``, so two events on one target that overlap
    in time would need a negative gap and the renderer would silently shift
    everything after them. Staggering happens *between* particles, each of which
    owns its own target id, so nothing here ever collides with itself.

    ``lead`` is where in the cue's window this particle starts, as a fraction. The
    caller decides it: a flow spreads its particles evenly, a propagation spreads
    them by hop depth.
    """
    fade = min(_PARTICLE_FADE, _FLIGHT / 4.0)
    path: dict[str, ParamValue] = {"from": source, "to": target, "curved": curved}
    if color is not None:
        path["color"] = color
    return (
        ExpandedStep(
            target_id=particle,
            op=SemanticOp.SHOW,
            offset=lead,
            duration=fade,
            params={"style": "fade", **path},
        ),
        ExpandedStep(
            target_id=particle,
            op=SemanticOp.FLOW,
            offset=lead + fade,
            duration=_FLIGHT - 2.0 * fade,
            params=path,
        ),
        ExpandedStep(
            target_id=particle,
            op=SemanticOp.HIDE,
            offset=lead + _FLIGHT - fade,
            duration=fade,
            params={"style": "fade", **path},
        ),
    )


def _particles(cue_id: str, source: str, target: str, count: int) -> list[str]:
    """Ids for one flow's particles. Derived from the cue, so a second flow along
    the same edge gets its own dots rather than re-animating the first flow's."""
    return [f"particle__{cue_id}__{source}__{target}__{n}" for n in range(count)]


def _expand_flow(cue: Cue, _scene: Scene) -> Expansion:
    """Dots travelling from the first target to the second.

    The path stays symbolic. Where these dots go depends on where their endpoints
    ended up, which is P3's answer, expressed in world units by P6 -- so the step
    carries ``{"from": ..., "to": ...}`` and P7 resolves it. An expansion that
    computed a midpoint here would be reading positions that do not exist yet.
    """
    source, target = cue.targets[0], cue.targets[1]
    particles = max(1, min(count(cue.params, "count", 3), _MAX_PARTICLES))
    curved = flag(cue.params, "curved", default=False)
    color = text(cue.params, "color")
    radius = number(cue.params, "radius", 0.035)
    objects: list[SyntheticObject] = []
    steps: list[ExpandedStep] = []
    for index, particle in enumerate(_particles(cue.id, source, target, particles)):
        objects.append(
            SyntheticObject(id=particle, kind=ObjectKind.DOT, props=DotProps(radius=radius))
        )
        steps.extend(
            flow_steps(
                source,
                target,
                particle,
                lead=(index / particles) * (1.0 - _FLIGHT),
                curved=curved,
                color=color,
            )
        )
    return Expansion(objects=tuple(objects), steps=tuple(steps))


#: Relationship kinds a propagation may travel along. ``parent_of`` is excluded on
#: purpose: a hierarchy is not a route, and spreading down one would make
#: ``propagate`` mean something different in a tree than in a network.
_ROUTES = frozenset({RelationKind.CONNECTED_TO, RelationKind.POINTS_TO})


def adjacency(scene: Scene) -> dict[str, tuple[str, ...]]:
    """Who can reach whom, from relationships and from ``connect`` cues alike.

    A connection an author drew with a cue is as real as one they declared as a
    relationship -- the timeline is where "these two are linked" most naturally
    gets said. Order follows declaration order so a propagation's shape never
    depends on dict iteration.
    """
    out: dict[str, list[str]] = {}

    def link(source: str, target: str, *, both: bool) -> None:
        out.setdefault(source, []).append(target)
        if both:
            out.setdefault(target, []).append(source)

    for rel in scene.relationships:
        if rel.kind in _ROUTES:
            link(rel.source, rel.target, both=rel.kind is RelationKind.CONNECTED_TO)
    for cue in scene.timeline:
        if cue.op is SemanticOp.CONNECT and len(cue.targets) >= 2:
            link(
                cue.targets[0],
                cue.targets[1],
                both=not flag(cue.params, "directed", default=False),
            )
    return {node: tuple(dict.fromkeys(edges)) for node, edges in out.items()}


def _wavefront(scene: Scene, origins: Sequence[str], hops: int) -> list[list[tuple[str, str]]]:
    """Edges reached at each hop, breadth-first, each node entered only once."""
    edges = adjacency(scene)
    seen = set(origins)
    frontier = list(origins)
    waves: list[list[tuple[str, str]]] = []
    for _ in range(hops):
        wave: list[tuple[str, str]] = []
        following: list[str] = []
        for node in frontier:
            for neighbour in edges.get(node, ()):
                if neighbour in seen:
                    continue
                seen.add(neighbour)
                wave.append((node, neighbour))
                following.append(neighbour)
        if not wave:
            break
        waves.append(wave)
        frontier = following
    return waves


def _expand_propagate(cue: Cue, scene: Scene) -> Expansion:
    """A wave of particles spreading outward, one hop at a time.

    Built from the same particle machinery as ``flow`` because it *is* a flow --
    several, staggered by depth. Reaching nowhere yields no steps, which P2 reports
    as ``CMP402``: a propagation from an isolated object is a real authoring defect,
    and the ``networks`` skill already refuses it as ``IR209`` when that pack is on.
    """
    color = text(cue.params, "color")
    hops = max(1, count(cue.params, "hops", 2))
    waves = _wavefront(scene, cue.targets, hops)
    objects: list[SyntheticObject] = []
    steps: list[ExpandedStep] = []
    for depth, wave in enumerate(waves):
        lead = (depth / len(waves)) * (1.0 - _FLIGHT)
        for source, target in wave:
            particle = f"pulse__{cue.id}__{source}__{target}"
            objects.append(
                SyntheticObject(id=particle, kind=ObjectKind.DOT, props=DotProps(radius=0.035))
            )
            steps.extend(flow_steps(source, target, particle, lead=lead, curved=False, color=color))
    return Expansion(objects=tuple(objects), steps=tuple(steps))


# ---------------------------------------------------------------------------
# Rearrangements
# ---------------------------------------------------------------------------


def _expand_compare(cue: Cue, _scene: Scene) -> Expansion:
    """Bring the targets into a row, or a column, in the order they were named.

    Each step says only *which* of *how many* it is; the destination is arithmetic
    over the targets' resolved bounds, which is P7's to do. Two objects already
    side by side still move -- to evenly spaced positions -- because "compare"
    means the comparison should read, not that nothing should happen.
    """
    axis = choice(cue.params, "axis", ("horizontal", "vertical"), "horizontal")
    total = len(cue.targets)
    return Expansion(
        steps=tuple(
            ExpandedStep(
                target_id=target,
                op=SemanticOp.COMPARE,
                offset=0.0,
                duration=1.0,
                params={"axis": axis, "index": index, "count": total},
            )
            for index, target in enumerate(cue.targets)
        )
    )


def _expand_transform(cue: Cue, _scene: Scene) -> Expansion:
    """The first target becomes the second.

    A rule rather than the default one-step-per-target path, because the second
    target is the *destination*: lowering it to a step of its own would animate
    the thing being turned into as though it were also being turned.
    """
    return Expansion(
        steps=(
            ExpandedStep(
                target_id=cue.targets[0],
                op=SemanticOp.TRANSFORM,
                offset=0.0,
                duration=1.0,
                params={
                    "into": cue.targets[1],
                    "replace": flag(cue.params, "replace", default=True),
                },
            ),
        )
    )


def _expand_morph(cue: Cue, _scene: Scene) -> Expansion:
    """Reshape the first target into the second, keeping both objects alive.

    The difference from ``transform`` is only that the source is not retired, which
    is why it carries no ``replace``: a morph is a change of form, and P7 chooses a
    non-replacing transform for it.
    """
    return Expansion(
        steps=(
            ExpandedStep(
                target_id=cue.targets[0],
                op=SemanticOp.MORPH,
                offset=0.0,
                duration=1.0,
                params={"into": cue.targets[1]},
            ),
        )
    )


def _expand_split(cue: Cue, _scene: Scene) -> Expansion:
    """The first target becomes the second; any further targets arrive after it.

    The source is retired by the transform, which is why the remaining pieces grow
    in rather than transform: there is only one source and it has already been
    spent on the first piece.
    """
    source, first, rest = cue.targets[0], cue.targets[1], cue.targets[2:]
    steps = [
        ExpandedStep(
            target_id=source,
            op=SemanticOp.TRANSFORM,
            offset=0.0,
            duration=0.6,
            params={"into": first, "replace": True},
        )
    ]
    share = 0.4 / max(len(rest), 1)
    for index, piece in enumerate(rest):
        steps.append(
            ExpandedStep(
                target_id=piece,
                op=SemanticOp.SHOW,
                offset=0.6 + index * share,
                duration=share,
                params={"style": "grow"},
            )
        )
    return Expansion(steps=tuple(steps))


def _expand_merge(cue: Cue, _scene: Scene) -> Expansion:
    """Every target but the last becomes the last one, all at once."""
    *sources, destination = cue.targets
    return Expansion(
        steps=tuple(
            ExpandedStep(
                target_id=source,
                op=SemanticOp.TRANSFORM,
                offset=0.0,
                duration=1.0,
                params={"into": destination, "replace": True},
            )
            for source in sources
        )
    )


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def _expand_trace(cue: Cue, _scene: Scene) -> Expansion:
    """Draw a path. A second target names the object whose motion it follows.

    Only the path is animated, so the follower must not get a step of its own --
    it is already moving under some other cue, and drawing *it* is not what
    ``trace`` was asked for. The reference travels in the params instead, where P7
    reads it alongside the flow endpoints.
    """
    params: dict[str, ParamValue] = {"fade_trail": flag(cue.params, "fade_trail", default=False)}
    if len(cue.targets) > 1:
        params["follows"] = cue.targets[1]
    return Expansion(
        steps=(
            ExpandedStep(
                target_id=cue.targets[0],
                op=SemanticOp.TRACE,
                offset=0.0,
                duration=1.0,
                params=params,
            ),
        )
    )


# ---------------------------------------------------------------------------
# The table
# ---------------------------------------------------------------------------

#: Operations with a built-in macro. Everything absent from this table lowers to one
#: step per target -- which is not a fallback but the common case: ``show`` on three
#: objects is three ``show`` steps and nothing more.
BUILTIN_EXPANSIONS: Mapping[SemanticOp, ExpansionRule] = {
    op: _Rule(op, fn)
    for op, fn in (
        (SemanticOp.CONNECT, _expand_connect),
        (SemanticOp.DISCONNECT, _expand_disconnect),
        (SemanticOp.FLOW, _expand_flow),
        (SemanticOp.PROPAGATE, _expand_propagate),
        (SemanticOp.COMPARE, _expand_compare),
        (SemanticOp.TRANSFORM, _expand_transform),
        (SemanticOp.MORPH, _expand_morph),
        (SemanticOp.SPLIT, _expand_split),
        (SemanticOp.MERGE, _expand_merge),
        (SemanticOp.TRACE, _expand_trace),
    )
}

#: Operations the compiler cannot realize on its own. ``simulate`` names a
#: behaviour a skill defines; with no skill supplying one there is nothing to draw,
#: so P2 reports ``CMP402`` rather than emitting a step no renderer can execute.
NEEDS_SKILL: frozenset[SemanticOp] = frozenset({SemanticOp.SIMULATE})


def expansion_for(
    op: SemanticOp, overrides: Mapping[SemanticOp, ExpansionRule]
) -> ExpansionRule | None:
    """The rule for one operation: a skill's if it has one, otherwise the built-in.

    Skills win. A pack that knows how packets really move through *its* topology
    should be able to say so without the compiler's generic answer competing.
    """
    return overrides.get(op) or BUILTIN_EXPANSIONS.get(op)
