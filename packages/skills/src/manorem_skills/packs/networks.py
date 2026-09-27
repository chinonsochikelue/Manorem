"""The ``networks`` pack: things joined to other things, and what moves between them.

The pack that carries the demo. "Satellite broadcasts to phone" is a flow along a
link, and the constraint below is the reason that stays meaningful: a ``flow``
between two objects with nothing joining them would render as a particle crossing
empty space, which reads as a bug rather than as a signal.

The check is deliberately generous about *how* the link was expressed -- a
``connected_to`` relationship, a ``points_to`` relationship, or a ``connect`` cue
all count, and connectivity is transitive. What it will not do is invent the link:
an unsatisfied flow is an ``IR209`` error that reaches the repair agent, because
the alternative is a render that quietly drops the packet.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Mapping
from dataclasses import dataclass

from manorem_core import Code, DiagnosticBag
from manorem_ir import ObjectKind, RelationKind, Scene, SemanticOp
from manorem_skills.pack import SkillPack, kinds, provide
from manorem_skills.protocol import PrimitiveDecl

#: Relationship kinds that mean "there is a link here". ``parent_of`` and
#: ``contains`` describe hierarchy rather than a channel, so they do not count:
#: a packet does not travel along containment.
_LINKING = frozenset({RelationKind.CONNECTED_TO, RelationKind.POINTS_TO})

_FLOWING_OPS = frozenset({SemanticOp.FLOW, SemanticOp.PROPAGATE})


def _adjacency(scene: Scene) -> Mapping[str, set[str]]:
    """Undirected connectivity, from relationships and from ``connect`` cues alike.

    Undirected on purpose: a link drawn from the satellite to the phone is the same
    channel as one drawn the other way, and a flow may legitimately run against the
    direction the author happened to declare.
    """
    graph: defaultdict[str, set[str]] = defaultdict(set)
    for rel in scene.relationships:
        if rel.kind in _LINKING:
            graph[rel.source].add(rel.target)
            graph[rel.target].add(rel.source)
    for cue in scene.timeline:
        if cue.op is SemanticOp.CONNECT and len(cue.targets) >= 2:
            first, second = cue.targets[0], cue.targets[1]
            graph[first].add(second)
            graph[second].add(first)
    return graph


def _endpoints(scene: Scene, target_id: str) -> list[str]:
    """Ids a link may legitimately be declared against for this cue target.

    Empty when the id resolves to nothing, which is the signal to stay quiet.
    """
    resolved = scene.resolve_targets(target_id)
    return [target_id, *resolved] if resolved else []


def _reachable(graph: Mapping[str, set[str]], sources: list[str], targets: set[str]) -> bool:
    """True when any source reaches any target. Generous by design.

    A cue may target a group, and the link may be declared against the group id or
    against one of its members -- both express the same channel. Since an
    unsatisfied flow is an ERROR that stops the build, the reading that avoids
    false positives is the right one: one connected member is enough.
    """
    seen = set(sources)
    queue = deque(sources)
    while queue:
        node = queue.popleft()
        if node in targets:
            return True
        for neighbour in graph.get(node, ()):
            if neighbour not in seen:
                seen.add(neighbour)
                queue.append(neighbour)
    return False


@dataclass(frozen=True, slots=True)
class FlowFollowsAConnection:
    """``IR209``: a flow must travel along a link that exists in the scene."""

    @property
    def id(self) -> str:
        return "networks.flow_follows_a_connection"

    def check(self, scene: Scene, bag: DiagnosticBag, base: str) -> None:
        graph = _adjacency(scene)
        for index, cue in enumerate(scene.timeline):
            if cue.op not in _FLOWING_OPS or len(cue.targets) < 2:
                continue
            source, target = cue.targets[0], cue.targets[1]
            # A link may be declared against a group or against its members, so both
            # are valid endpoints. An unresolvable id yields nothing and is IR201's
            # finding -- reporting it again here would give the repair agent two
            # diagnostics for one defect.
            from_ids = _endpoints(scene, source)
            to_ids = _endpoints(scene, target)
            if not from_ids or not to_ids:
                continue
            if not _reachable(graph, from_ids, set(to_ids)):
                bag.add(
                    Code.IR209_UNSATISFIED_SKILL_CONSTRAINT,
                    f"cue {cue.id!r}: {cue.op.value} from {source!r} to {target!r} "
                    "has no connection to travel along",
                    pointer=f"{base}/timeline/{index}",
                    scene_id=scene.id,
                    hint=(
                        f"Add a connected_to relationship between {source!r} and {target!r}, "
                        "or a connect cue joining them, before this cue."
                    ),
                )


@dataclass(frozen=True, slots=True)
class PropagationHasSomewhereToGo:
    """``IR209``: a one-target ``propagate`` needs at least one link to spread along.

    ``propagate`` accepts a single target -- "spread outward from the hub" -- which
    :class:`FlowFollowsAConnection` cannot check, having no second endpoint to reach.
    An isolated node still spreads nothing, so the gap is worth its own predicate.
    """

    @property
    def id(self) -> str:
        return "networks.propagation_has_somewhere_to_go"

    def check(self, scene: Scene, bag: DiagnosticBag, base: str) -> None:
        graph = _adjacency(scene)
        for index, cue in enumerate(scene.timeline):
            if cue.op is not SemanticOp.PROPAGATE or len(cue.targets) != 1:
                continue
            origin = cue.targets[0]
            endpoints = _endpoints(scene, origin)
            if not endpoints:
                continue  # IR201's finding.
            if not any(graph.get(node) for node in endpoints):
                bag.add(
                    Code.IR209_UNSATISFIED_SKILL_CONSTRAINT,
                    f"cue {cue.id!r}: propagate from {origin!r}, which is connected to nothing",
                    pointer=f"{base}/timeline/{index}",
                    scene_id=scene.id,
                    object_id=origin,
                    hint=(
                        f"Connect {origin!r} to at least one other object, or use highlight "
                        "if the intent is to draw attention rather than to spread."
                    ),
                )


_PROMPT = """\
The `networks` vocabulary describes things joined to other things.

Objects: `graph` for an abstract node-and-edge structure, `network` when the
topology matters (star, mesh, ring), `particles` for a swarm rather than
individually named dots.

Operations: `connect` and `disconnect` to create and remove a link; `flow` to
send something from one object to another along a link; `propagate` to spread an
effect outward through the links; `trace` to draw a path; `simulate` for a named
domain behaviour.

`flow` and `propagate` require a link between their endpoints -- declare a
`connected_to` relationship, or issue a `connect` cue first. A flow with nothing
to travel along is rejected, not drawn across empty space.
"""

NETWORKS = SkillPack(
    id="networks",
    version="1.0",
    summary="Nodes, links, and what travels along them.",
    primitives=kinds(
        PrimitiveDecl(
            kind=ObjectKind.GRAPH,
            summary="Nodes and edges laid out by structure.",
            prompt_hint="Give every node an id; edges reference those ids.",
        ),
        PrimitiveDecl(
            kind=ObjectKind.NETWORK,
            summary="A graph whose topology is the point (star, mesh, ring).",
        ),
        PrimitiveDecl(
            kind=ObjectKind.PARTICLES,
            summary="A swarm treated as one object rather than as named dots.",
            prompt_hint="Use when the count matters but the individuals do not.",
        ),
    ),
    operations=provide(
        SemanticOp.CONNECT,
        SemanticOp.DISCONNECT,
        SemanticOp.FLOW,
        SemanticOp.PROPAGATE,
        SemanticOp.TRACE,
        SemanticOp.SIMULATE,
    ),
    constraints=(FlowFollowsAConnection(), PropagationHasSomewhereToGo()),
    prompt_fragment=_PROMPT,
)
