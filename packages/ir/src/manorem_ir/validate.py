"""Three-tier IR validation.

The contract: **invalid IR never reaches the renderer.** Validation is layered so
that each failure is reported at the level where it is actually detectable.

* **T1 structural** -- shape of the document. Pydantic covers types, ranges and
  discriminators on parse; this tier adds the cross-field and cross-collection
  facts a schema cannot express (duplicate ids, empty scenes, durations that
  quantize away at the target frame rate).
* **T2 referential / semantic** -- does the document *mean* anything. Every
  reference resolves, every operation signature is satisfied, the timeline is
  acyclic, nothing is used before it exists. Every code emitted here is in
  :data:`~manorem_core.SEMANTIC_ERROR_CODES`, so none of it may be quietly
  autofixed: it escalates to the bounded repair agent instead.
* **T3 pacing and geometry** -- well-formed but questionable. Warnings by
  default, promotable to errors by policy.

All three tiers are computed from the IR and the solved plan -- never from
pixels. They establish that a plan is *well-formed*, which is a different claim
from *looks good*. Perceptual judgement belongs to the Visual QA stage and its
own ``VQA6xx`` codes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Protocol

from pydantic import ValidationError

from manorem_core import (
    Code,
    Diagnostic,
    DiagnosticBag,
    IRValidationError,
    Severity,
    pointer,
)
from manorem_ir.camera import CameraSpec
from manorem_ir.enums import ObjectKind, RelationKind
from manorem_ir.geometry import SAFE_AREA, StageBounds
from manorem_ir.narration import DEFAULT_WPM
from manorem_ir.objects import AnchorPlacement, SceneObject, SlotPlacement
from manorem_ir.operations import DEFAULT_REGISTRY, OperationDecl, OperationRegistry
from manorem_ir.project import Project
from manorem_ir.resolve import ResolvedTiming, resolve_timing
from manorem_ir.scene import Scene
from manorem_ir.timeline import Cue
from manorem_ir.timing import (
    AfterCue,
    NarrationDuration,
    NarrationTime,
    WithCue,
)

#: Field names whose value is an identifier. Used to report a malformed id as
#: IR103 rather than a generic schema failure, so the repair agent gets a
#: specific instruction instead of "something is wrong at this pointer".
_ID_FIELDS = frozenset(
    {
        "id",
        "ref",
        "cue",
        "segment",
        "source",
        "target",
        "targets",
        "members",
        "mentions",
        "follow",
    }
)

_ID_ERROR_TYPES = frozenset({"value_error", "string_pattern_mismatch", "string_type"})

#: DFS colors for cycle detection.
_WHITE, _GREY, _BLACK = 0, 1, 2

#: Slack allowed before a duration mismatch is reported, in seconds. Absorbs
#: float noise in summed narration estimates.
_EPSILON = 0.05


class SceneConstraint(Protocol):
    """A skill-contributed semantic rule, checked during T2.

    Skills own rules the IR package cannot know -- "a ``flow`` must follow an
    existing ``connected_to`` edge" is a networks concept, not a generic one.
    They are injected rather than imported so ``manorem_ir`` never depends on
    ``manorem_skills``.
    """

    @property
    def id(self) -> str:
        """Stable identifier, reported alongside the diagnostic.

        Read-only so an implementation may be a frozen dataclass -- which is what
        a skill-contributed rule should be, since a constraint carries no state.
        """
        ...

    def check(self, scene: Scene, bag: DiagnosticBag, base: str) -> None:
        """Append ``IR209`` diagnostics for violations. Must not mutate ``scene``."""
        ...


@dataclass(frozen=True, slots=True)
class ValidationPolicy:
    """Thresholds for the T3 lints.

    Every value is a judgement call about pacing, so they are configurable rather
    than baked into the checks -- a dense technical explainer and a gentle
    intro have genuinely different limits.
    """

    max_concurrent_objects: int = 12
    max_dead_air: float = 2.5
    min_scene_duration: float = 1.5
    #: Fraction of the smaller object's area that may be covered before the
    #: overlap is reported.
    max_overlap_ratio: float = 0.35
    #: Treat T3 lints as errors. Off by default: a slightly slow scene should not
    #: block a render, but a caller preparing a final cut may want it on.
    strict_lints: bool = False


@dataclass(frozen=True, slots=True)
class ValidationContext:
    """Everything validation needs that does not come from the IR itself."""

    registry: OperationRegistry = DEFAULT_REGISTRY
    policy: ValidationPolicy = field(default_factory=ValidationPolicy)
    #: Skill ids the caller can actually load. ``None`` skips the IR210 check --
    #: the CLI and pipeline always pass the registry's real names.
    known_skills: frozenset[str] | None = None
    #: Object kinds the enabled skills provide. ``None`` skips the IR215 check.
    allowed_kinds: frozenset[ObjectKind] | None = None
    constraints: Sequence[SceneConstraint] = ()
    wpm: float = DEFAULT_WPM
    fps: int = 30


# ---------------------------------------------------------------------------
# Parsing (T1 via Pydantic)
# ---------------------------------------------------------------------------


def diagnostics_from_validation_error(exc: ValidationError) -> list[Diagnostic]:
    """Translate a Pydantic failure into the shared diagnostic vocabulary.

    Pydantic's own error shape is not the contract the repair agent consumes; the
    ``Diagnostic`` type is. Translating at the boundary keeps every downstream
    consumer -- inspector, logs, repair loop -- looking at one thing.
    """
    out: list[Diagnostic] = []
    for err in exc.errors():
        loc = err["loc"]
        field_name = next((p for p in reversed(loc) if isinstance(p, str)), "")
        is_id = field_name in _ID_FIELDS and err["type"] in _ID_ERROR_TYPES
        out.append(
            Diagnostic(
                code=Code.IR103_INVALID_ID if is_id else Code.IR101_SCHEMA_INVALID,
                severity=Severity.ERROR,
                message=err["msg"],
                pointer=pointer(*loc),
                hint=(
                    "Identifiers must be lowercase, start with a letter, and use "
                    "only letters, digits and underscores."
                    if is_id
                    else None
                ),
            )
        )
    return out


def parse_project(data: object) -> Project:
    """Parse untrusted JSON into a :class:`Project`.

    Raises :class:`IRValidationError` carrying diagnostics rather than letting a
    Pydantic error escape, so callers handle one failure type.
    """
    try:
        return Project.model_validate(data)
    except ValidationError as exc:
        raise IRValidationError(
            "IR failed structural validation",
            diagnostics=diagnostics_from_validation_error(exc),
        ) from exc


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def validate_project(project: Project, ctx: ValidationContext | None = None) -> DiagnosticBag:
    """Run all three tiers over a whole project."""
    context = replace(ctx or ValidationContext(), fps=project.format.fps, wpm=project.narration_wpm)
    bag = DiagnosticBag()

    if not project.episodes:
        bag.add(
            Code.IR106_NO_SCENES,
            "project has no episodes",
            pointer=pointer("episodes"),
            hint="A project needs at least one episode containing at least one scene.",
        )

    _check_unique(bag, [e.id for e in project.episodes], pointer("episodes"), "episode")

    all_scene_ids: list[str] = []
    for ep_index, episode in enumerate(project.episodes):
        ep_ptr = pointer("episodes", ep_index)
        if not episode.scenes:
            bag.add(
                Code.IR106_NO_SCENES,
                f"episode {episode.id!r} has no scenes",
                pointer=f"{ep_ptr}/scenes",
            )
        for sc_index, scene in enumerate(episode.scenes):
            all_scene_ids.append(scene.id)
            bag.extend(validate_scene(scene, ctx=context, base=f"{ep_ptr}/scenes/{sc_index}"))

    # Scene ids are addressed project-wide (partial re-render, targeted repair),
    # so a collision across episodes is as damaging as one within a scene.
    _check_unique(bag, all_scene_ids, pointer("episodes"), "scene")
    return bag


def validate_scene(
    scene: Scene,
    ctx: ValidationContext | None = None,
    base: str = "",
) -> DiagnosticBag:
    """Run all three tiers over a single scene.

    Scenes validate independently -- that is what makes per-scene AI generation
    and per-scene repair possible.
    """
    context = ctx or ValidationContext()
    bag = DiagnosticBag()
    timing = resolve_timing(scene, registry=context.registry, wpm=context.wpm)

    _check_structure(scene, bag, context, base, timing)
    _check_references(scene, bag, context, base, timing)
    _check_pacing(scene, bag, context, base, timing)

    for constraint in context.constraints:
        constraint.check(scene, bag, base)
    return bag


# ---------------------------------------------------------------------------
# T1: structural
# ---------------------------------------------------------------------------


def _check_unique(bag: DiagnosticBag, ids: list[str], ptr: str, label: str) -> None:
    seen: set[str] = set()
    for value in ids:
        if value in seen:
            bag.add(
                Code.IR102_DUPLICATE_ID,
                f"duplicate {label} id {value!r}",
                pointer=ptr,
                object_id=value,
                hint=f"Every {label} id must be unique within its scope.",
            )
        seen.add(value)


def _check_structure(
    scene: Scene,
    bag: DiagnosticBag,
    ctx: ValidationContext,
    base: str,
    timing: ResolvedTiming,
) -> None:
    sid = scene.id
    for values, ptr, label in (
        ([o.id for o in scene.objects], f"{base}/objects", "object"),
        ([g.id for g in scene.groups], f"{base}/groups", "group"),
        ([c.id for c in scene.timeline], f"{base}/timeline", "cue"),
        ([s.id for s in scene.narration], f"{base}/narration", "narration segment"),
    ):
        _check_unique(bag, values, ptr, label)

    # Objects and groups share one target namespace, so a collision makes every
    # cue targeting that id ambiguous.
    collisions = scene.object_ids & scene.group_ids
    for value in sorted(collisions):
        bag.add(
            Code.IR102_DUPLICATE_ID,
            f"id {value!r} names both an object and a group",
            pointer=f"{base}/groups",
            scene_id=sid,
            object_id=value,
            hint="Cue targets resolve against objects and groups together; rename one.",
        )

    if not scene.objects and not scene.timeline:
        bag.add(
            Code.IR104_EMPTY_SCENE,
            f"scene {sid!r} has no objects and no cues",
            pointer=base or "/",
            scene_id=sid,
            hint="A scene must show something. Remove it or give it content.",
        )

    # A duration that rounds to zero frames at the target rate renders nothing at
    # all. This is format-dependent, which is exactly why the schema cannot catch
    # it: the same IR is valid at 60fps and degenerate at 15fps.
    for index, cue in enumerate(scene.timeline):
        length = timing.durations.get(cue.id)
        if length is None:
            continue
        if length * ctx.fps < 0.5:
            bag.add(
                Code.IR105_NON_POSITIVE_DURATION,
                f"cue {cue.id!r} lasts {length:.4f}s, which is under one frame at {ctx.fps}fps",
                pointer=f"{base}/timeline/{index}/duration",
                scene_id=sid,
                hint=f"Use at least {1.0 / ctx.fps:.3f}s, or remove the cue.",
            )


# ---------------------------------------------------------------------------
# T2: referential and semantic
# ---------------------------------------------------------------------------


def _find_relationship_cycle(adjacency: Mapping[str, list[str]]) -> tuple[str, ...] | None:
    """First cycle in a containment/parent graph, as an ordered node tuple."""
    color: dict[str, int] = {}
    stack: list[str] = []

    def visit(node: str) -> tuple[str, ...] | None:
        color[node] = _GREY
        stack.append(node)
        for nxt in adjacency.get(node, ()):
            state = color.get(nxt, _WHITE)
            if state == _GREY:
                return tuple(stack[stack.index(nxt) :])
            if state == _WHITE:
                found = visit(nxt)
                if found is not None:
                    return found
        stack.pop()
        color[node] = _BLACK
        return None

    for node in adjacency:
        if color.get(node, _WHITE) == _WHITE:
            cycle = visit(node)
            if cycle is not None:
                return cycle
    return None


def _check_props_references(scene: Scene, obj: SceneObject, bag: DiagnosticBag, optr: str) -> None:
    """References buried inside typed props: group members and arrow endpoints."""
    props = obj.props
    if props.kind == "group":
        for m_index, member in enumerate(props.members):
            if member not in scene.object_ids:
                bag.add(
                    Code.IR212_UNKNOWN_GROUP_MEMBER,
                    f"group object {obj.id!r} contains unknown member {member!r}",
                    pointer=f"{optr}/props/members/{m_index}",
                    scene_id=scene.id,
                    object_id=obj.id,
                )
    elif props.kind == "arrow":
        for name, endpoint in (("start", props.start), ("end", props.end)):
            if isinstance(endpoint, str) and endpoint not in scene.addressable_ids:
                bag.add(
                    Code.IR201_UNKNOWN_OBJECT_REF,
                    f"arrow {obj.id!r} points at unknown object {endpoint!r}",
                    pointer=f"{optr}/props/{name}",
                    scene_id=scene.id,
                    object_id=obj.id,
                )


def _check_placement(
    scene: Scene,
    obj: SceneObject,
    bag: DiagnosticBag,
    optr: str,
    anchors: dict[str, list[str]],
) -> None:
    placement = obj.placement
    if isinstance(placement, AnchorPlacement):
        if placement.ref not in scene.addressable_ids:
            bag.add(
                Code.IR201_UNKNOWN_OBJECT_REF,
                f"object {obj.id!r} is anchored to unknown object {placement.ref!r}",
                pointer=f"{optr}/placement/ref",
                scene_id=scene.id,
                object_id=obj.id,
            )
        else:
            anchors.setdefault(obj.id, []).append(placement.ref)
    elif isinstance(placement, SlotPlacement) and placement.slot not in scene.layout.slot_names:
        known = ", ".join(sorted(scene.layout.slot_names)) or "none defined"
        bag.add(
            Code.IR213_UNKNOWN_LAYOUT_SLOT,
            f"object {obj.id!r} targets layout slot {placement.slot!r} (available: {known})",
            pointer=f"{optr}/placement/slot",
            scene_id=scene.id,
            object_id=obj.id,
        )


def _check_object_references(
    scene: Scene, bag: DiagnosticBag, ctx: ValidationContext, base: str
) -> None:
    anchors: dict[str, list[str]] = {}

    for index, obj in enumerate(scene.objects):
        optr = f"{base}/objects/{index}"
        if ctx.allowed_kinds is not None and obj.kind not in ctx.allowed_kinds:
            bag.add(
                Code.IR215_UNKNOWN_OBJECT_KIND,
                f"object {obj.id!r} uses kind {obj.kind.value!r}, which no enabled skill provides",
                pointer=f"{optr}/kind",
                scene_id=scene.id,
                object_id=obj.id,
                hint=f"Enable a skill that provides {obj.kind.value!r}, or use another kind.",
            )
        _check_placement(scene, obj, bag, optr, anchors)
        _check_props_references(scene, obj, bag, optr)

    cycle = _find_relationship_cycle(anchors)
    if cycle is not None:
        bag.add(
            Code.IR208_INVALID_RELATIONSHIP,
            "anchor chain forms a cycle: " + " -> ".join([*cycle, cycle[0]]),
            pointer=f"{base}/objects",
            scene_id=scene.id,
            hint="Anchor placement must terminate at an object the layout can position.",
        )


def _check_groups_and_relationships(scene: Scene, bag: DiagnosticBag, base: str) -> None:
    sid = scene.id
    addressable = scene.addressable_ids

    for index, group in enumerate(scene.groups):
        for m_index, member in enumerate(group.members):
            if member not in scene.object_ids:
                bag.add(
                    Code.IR212_UNKNOWN_GROUP_MEMBER,
                    f"group {group.id!r} contains unknown member {member!r}",
                    pointer=f"{base}/groups/{index}/members/{m_index}",
                    scene_id=sid,
                    object_id=group.id,
                )

    hierarchy: dict[str, list[str]] = {}
    for index, rel in enumerate(scene.relationships):
        rptr = f"{base}/relationships/{index}"
        for name, value in (("source", rel.source), ("target", rel.target)):
            if value not in addressable:
                bag.add(
                    Code.IR201_UNKNOWN_OBJECT_REF,
                    f"relationship {rel.kind.value!r} references unknown object {value!r}",
                    pointer=f"{rptr}/{name}",
                    scene_id=sid,
                    object_id=value,
                )
        if rel.source == rel.target:
            bag.add(
                Code.IR208_INVALID_RELATIONSHIP,
                f"relationship {rel.kind.value!r} links {rel.source!r} to itself",
                pointer=rptr,
                scene_id=sid,
                object_id=rel.source,
            )
        elif rel.kind in (RelationKind.PARENT_OF, RelationKind.CONTAINS):
            hierarchy.setdefault(rel.source, []).append(rel.target)

    cycle = _find_relationship_cycle(hierarchy)
    if cycle is not None:
        bag.add(
            Code.IR208_INVALID_RELATIONSHIP,
            "containment forms a cycle: " + " -> ".join([*cycle, cycle[0]]),
            pointer=f"{base}/relationships",
            scene_id=sid,
            hint="parent_of and contains must describe a tree, not a loop.",
        )


def _check_camera(scene: Scene, bag: DiagnosticBag, base: str) -> None:
    camera: CameraSpec = scene.camera
    if camera.follow is not None and camera.follow not in scene.addressable_ids:
        bag.add(
            Code.IR201_UNKNOWN_OBJECT_REF,
            f"camera follows unknown object {camera.follow!r}",
            pointer=f"{base}/camera/follow",
            scene_id=scene.id,
            object_id=camera.follow,
        )


def _check_narration_references(scene: Scene, bag: DiagnosticBag, base: str) -> None:
    for index, segment in enumerate(scene.narration):
        for m_index, mention in enumerate(segment.mentions):
            if mention not in scene.addressable_ids:
                bag.add(
                    Code.IR201_UNKNOWN_OBJECT_REF,
                    f"narration segment {segment.id!r} mentions unknown object {mention!r}",
                    pointer=f"{base}/narration/{index}/mentions/{m_index}",
                    scene_id=scene.id,
                    object_id=mention,
                    hint="mentions links a line to what it talks about; the id must exist.",
                )


def _check_cue_signature(
    cue: Cue, decl: OperationDecl, bag: DiagnosticBag, cptr: str, scene_id: str
) -> None:
    """Target arity and required parameters, from the operation's declaration."""
    if not (decl.min_targets <= len(cue.targets) <= decl.max_targets):
        expected = (
            str(decl.min_targets)
            if decl.min_targets == decl.max_targets
            else f"{decl.min_targets}-{decl.max_targets}"
        )
        bag.add(
            Code.IR214_TARGET_COUNT_MISMATCH,
            f"cue {cue.id!r} ({cue.op.value}) has {len(cue.targets)} target(s), "
            f"expected {expected}",
            pointer=f"{cptr}/targets",
            scene_id=scene_id,
        )
    for name in decl.required_params():
        if name not in cue.params:
            bag.add(
                Code.IR211_MISSING_REQUIRED_PARAM,
                f"cue {cue.id!r} ({cue.op.value}) is missing required parameter {name!r}",
                pointer=f"{cptr}/params",
                scene_id=scene_id,
            )


def _check_cue_targets(
    scene: Scene, cue: Cue, decl: OperationDecl | None, bag: DiagnosticBag, cptr: str
) -> None:
    """Each target exists, and its kind is one the operation accepts."""
    for t_index, target in enumerate(cue.targets):
        tptr = f"{cptr}/targets/{t_index}"
        if target not in scene.addressable_ids:
            bag.add(
                Code.IR201_UNKNOWN_OBJECT_REF,
                f"cue {cue.id!r} targets unknown object {target!r}",
                pointer=tptr,
                scene_id=scene.id,
                object_id=target,
                hint="Declare the object, or point the cue at one that exists.",
            )
            continue
        if decl is None:
            continue
        for object_id in scene.resolve_targets(target):
            obj = scene.object_by_id(object_id)
            if obj is not None and obj.kind not in decl.allowed_kinds:
                bag.add(
                    Code.IR206_TARGET_KIND_NOT_ALLOWED,
                    f"cue {cue.id!r} ({cue.op.value}) cannot target {object_id!r} "
                    f"of kind {obj.kind.value!r}",
                    pointer=tptr,
                    scene_id=scene.id,
                    object_id=object_id,
                    hint="Allowed kinds: " + ", ".join(sorted(k.value for k in decl.allowed_kinds)),
                )


def _check_cue_timing_refs(scene: Scene, cue: Cue, bag: DiagnosticBag, cptr: str) -> None:
    """Cue and narration ids named by this cue's ``at`` and ``duration``."""
    at = cue.at
    if isinstance(at, AfterCue | WithCue):
        if at.cue == cue.id:
            bag.add(
                Code.IR204_TIMELINE_CYCLE,
                f"cue {cue.id!r} is scheduled relative to itself",
                pointer=f"{cptr}/at/cue",
                scene_id=scene.id,
            )
        elif at.cue not in scene.cue_ids:
            bag.add(
                Code.IR202_UNKNOWN_CUE_REF,
                f"cue {cue.id!r} is scheduled against unknown cue {at.cue!r}",
                pointer=f"{cptr}/at/cue",
                scene_id=scene.id,
            )
    elif isinstance(at, NarrationTime) and at.segment not in scene.segment_ids:
        bag.add(
            Code.IR203_UNKNOWN_NARRATION_REF,
            f"cue {cue.id!r} is anchored to unknown narration segment {at.segment!r}",
            pointer=f"{cptr}/at/segment",
            scene_id=scene.id,
        )

    duration = cue.duration
    if isinstance(duration, NarrationDuration) and duration.segment not in scene.segment_ids:
        bag.add(
            Code.IR203_UNKNOWN_NARRATION_REF,
            f"cue {cue.id!r} lasts as long as unknown narration segment {duration.segment!r}",
            pointer=f"{cptr}/duration/segment",
            scene_id=scene.id,
        )


def _check_cues(
    scene: Scene,
    bag: DiagnosticBag,
    ctx: ValidationContext,
    base: str,
    timing: ResolvedTiming,
) -> None:
    for index, cue in enumerate(scene.timeline):
        cptr = f"{base}/timeline/{index}"
        decl = ctx.registry.get(cue.op)
        if decl is None:
            bag.add(
                Code.IR205_UNKNOWN_OP,
                f"cue {cue.id!r} uses operation {cue.op.value!r}, which no enabled skill declares",
                pointer=f"{cptr}/op",
                scene_id=scene.id,
                hint="Enable the skill that provides it, or express the intent differently.",
            )
        else:
            _check_cue_signature(cue, decl, bag, cptr, scene.id)
        _check_cue_targets(scene, cue, decl, bag, cptr)
        _check_cue_timing_refs(scene, cue, bag, cptr)

    for cycle in timing.cycles:
        if len(cycle) < 2:
            continue  # self-reference already reported against its own pointer
        bag.add(
            Code.IR204_TIMELINE_CYCLE,
            "cue timing forms a cycle: " + " -> ".join([*cycle, cycle[0]]),
            pointer=f"{base}/timeline",
            scene_id=scene.id,
            hint="Anchor one of these cues to an absolute time or a narration segment.",
        )


def _check_use_before_show(
    scene: Scene,
    bag: DiagnosticBag,
    ctx: ValidationContext,
    base: str,
    timing: ResolvedTiming,
) -> None:
    """Report objects used before -- or without ever -- being introduced.

    Deliberately conservative on ordering: a use is only reported as too early
    when both its own start and every introduction are resolved. Compiler pass P4
    repeats the check against the fully scheduled, frame-quantized timeline and
    catches what symbolic resolution could not. Reporting a *maybe* here would
    train callers to ignore the code.
    """
    introduced: dict[str, list[float]] = {}
    for cue in scene.timeline:
        decl = ctx.registry.get(cue.op)
        if decl is None or not decl.introduces:
            continue
        start = timing.starts.get(cue.id)
        for target in cue.targets:
            for object_id in scene.resolve_targets(target):
                introduced.setdefault(object_id, [])
                if start is not None:
                    introduced[object_id].append(start)

    for index, cue in enumerate(scene.timeline):
        decl = ctx.registry.get(cue.op)
        if decl is None or decl.introduces:
            continue
        use_start = timing.starts.get(cue.id)
        for t_index, target in enumerate(cue.targets):
            for object_id in scene.resolve_targets(target):
                ptr = f"{base}/timeline/{index}/targets/{t_index}"
                if object_id not in introduced:
                    bag.add(
                        Code.IR207_USE_BEFORE_SHOW,
                        f"cue {cue.id!r} ({cue.op.value}) uses {object_id!r}, which is never shown",
                        pointer=ptr,
                        scene_id=scene.id,
                        object_id=object_id,
                        hint="Add a show cue for it before this one.",
                    )
                    continue
                starts = introduced[object_id]
                if use_start is not None and starts and use_start < min(starts) - _EPSILON:
                    bag.add(
                        Code.IR207_USE_BEFORE_SHOW,
                        f"cue {cue.id!r} ({cue.op.value}) uses {object_id!r} at "
                        f"{use_start:.2f}s, before it appears at {min(starts):.2f}s",
                        pointer=ptr,
                        scene_id=scene.id,
                        object_id=object_id,
                    )


def _check_references(
    scene: Scene,
    bag: DiagnosticBag,
    ctx: ValidationContext,
    base: str,
    timing: ResolvedTiming,
) -> None:
    if ctx.known_skills is not None:
        for index, skill in enumerate(scene.skills):
            if skill not in ctx.known_skills:
                bag.add(
                    Code.IR210_UNKNOWN_SKILL,
                    f"scene {scene.id!r} requests unknown skill {skill!r}",
                    pointer=f"{base}/skills/{index}",
                    scene_id=scene.id,
                    hint="Known skills: " + ", ".join(sorted(ctx.known_skills)),
                )

    _check_object_references(scene, bag, ctx, base)
    _check_groups_and_relationships(scene, bag, base)
    _check_camera(scene, bag, base)
    _check_narration_references(scene, bag, base)
    _check_cues(scene, bag, ctx, base, timing)
    _check_use_before_show(scene, bag, ctx, base, timing)


# ---------------------------------------------------------------------------
# T3: pacing and geometry lints
# ---------------------------------------------------------------------------


def _lint(
    bag: DiagnosticBag,
    ctx: ValidationContext,
    code: Code,
    message: str,
    *,
    ptr: str,
    scene_id: str,
    hint: str | None = None,
) -> None:
    severity = Severity.ERROR if ctx.policy.strict_lints else Severity.WARNING
    bag.add(code, message, severity=severity, pointer=ptr, scene_id=scene_id, hint=hint)


def scene_duration(scene: Scene, timing: ResolvedTiming) -> float:
    """Effective scene length: the hint if given, else what the content needs."""
    if scene.duration_hint is not None:
        return scene.duration_hint
    narration_end = max((w.end for w in timing.narration.values()), default=0.0)
    return max(narration_end, timing.end)


def _check_pacing(
    scene: Scene,
    bag: DiagnosticBag,
    ctx: ValidationContext,
    base: str,
    timing: ResolvedTiming,
) -> None:
    sid = scene.id
    policy = ctx.policy
    duration = scene_duration(scene, timing)
    narration_end = max((w.end for w in timing.narration.values()), default=0.0)

    if scene.duration_hint is not None and narration_end > scene.duration_hint + _EPSILON:
        _lint(
            bag,
            ctx,
            Code.IR301_NARRATION_OVERFLOW,
            f"narration runs {narration_end:.1f}s but the scene is capped at "
            f"{scene.duration_hint:.1f}s",
            ptr=f"{base}/duration_hint",
            scene_id=sid,
            hint="Lengthen the scene or shorten the script; narration is never truncated.",
        )

    if duration > 0.0 and duration < policy.min_scene_duration:
        _lint(
            bag,
            ctx,
            Code.IR306_SCENE_TOO_SHORT,
            f"scene lasts {duration:.2f}s, under the {policy.min_scene_duration:.2f}s minimum",
            ptr=base or "/",
            scene_id=sid,
            hint="Too short to read. Merge it into a neighbour or give it more content.",
        )

    windows = [w for cue in scene.timeline if (w := timing.window(cue.id)) is not None]
    if windows:
        windows.sort(key=lambda w: w.start)
        covered = 0.0
        for window in windows:
            gap = window.start - covered
            if gap > policy.max_dead_air:
                _lint(
                    bag,
                    ctx,
                    Code.IR302_DEAD_AIR,
                    f"{gap:.1f}s with nothing happening before {window.start:.1f}s",
                    ptr=f"{base}/timeline",
                    scene_id=sid,
                    hint="Fill the gap, tighten the timings, or split the scene.",
                )
            covered = max(covered, window.end)
        trailing = duration - covered
        if trailing > policy.max_dead_air:
            _lint(
                bag,
                ctx,
                Code.IR302_DEAD_AIR,
                f"{trailing:.1f}s of stillness after the last cue ends",
                ptr=f"{base}/timeline",
                scene_id=sid,
            )

    peak = _peak_concurrency(scene, ctx, timing)
    if peak > policy.max_concurrent_objects:
        _lint(
            bag,
            ctx,
            Code.IR303_SCENE_TOO_DENSE,
            f"{peak} objects on stage at once, over the {policy.max_concurrent_objects} limit",
            ptr=f"{base}/objects",
            scene_id=sid,
            hint="Split the scene, or hide earlier objects before introducing more.",
        )


def _peak_concurrency(scene: Scene, ctx: ValidationContext, timing: ResolvedTiming) -> int:
    """Most objects visible simultaneously, from show/hide cues.

    Counts distinct object ids rather than events: showing the same object twice
    is redundant, not crowded.
    """
    events: list[tuple[float, bool, str]] = []
    for cue in scene.timeline:
        decl = ctx.registry.get(cue.op)
        if decl is None or not (decl.introduces or decl.removes):
            continue
        start = timing.starts.get(cue.id)
        if start is None:
            continue
        for target in cue.targets:
            for object_id in scene.resolve_targets(target):
                events.append((start, decl.introduces, object_id))

    # Removals sort before introductions at the same instant, so swapping one
    # object for another does not read as a density spike.
    events.sort(key=lambda e: (e[0], e[1]))
    visible: set[str] = set()
    peak = 0
    for _, is_show, object_id in events:
        if is_show:
            visible.add(object_id)
            peak = max(peak, len(visible))
        else:
            visible.discard(object_id)
    return peak


# ---------------------------------------------------------------------------
# Post-layout geometry (called by the compiler once positions are solved)
# ---------------------------------------------------------------------------


def check_geometry(
    scene_id: str,
    bounds: Mapping[str, StageBounds],
    ctx: ValidationContext | None = None,
    base: str = "",
    safe_area: StageBounds = SAFE_AREA,
) -> DiagnosticBag:
    """Overlap and off-stage lints, once pass P3 has solved positions.

    Lives here rather than in the compiler because it belongs to the same T3 tier
    and shares the same policy object -- the compiler is the caller, not the
    owner. Still geometric, not perceptual: it proves nothing is *outside the
    frame*, not that anything is readable.
    """
    context = ctx or ValidationContext()
    bag = DiagnosticBag()
    ids = sorted(bounds)

    for object_id in ids:
        box = bounds[object_id]
        if not safe_area.contains(box):
            _lint(
                bag,
                context,
                Code.IR305_OFF_STAGE,
                f"{object_id!r} extends outside the safe area",
                ptr=f"{base}/objects",
                scene_id=scene_id,
                hint="Shrink it, or use a layout that fits the content.",
            )

    for i, first in enumerate(ids):
        for second in ids[i + 1 :]:
            a, b = bounds[first], bounds[second]
            smaller = min(a.area, b.area)
            if smaller <= 0.0:
                continue
            ratio = a.intersection_area(b) / smaller
            if ratio > context.policy.max_overlap_ratio:
                _lint(
                    bag,
                    context,
                    Code.IR304_OBJECT_OVERLAP,
                    f"{first!r} and {second!r} overlap by {ratio * 100:.0f}%",
                    ptr=f"{base}/objects",
                    scene_id=scene_id,
                    hint="Increase the layout gap, or give them separate slots.",
                )
    return bag
