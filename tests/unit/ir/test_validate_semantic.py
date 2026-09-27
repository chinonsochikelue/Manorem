"""T2 referential and semantic validation: IR201-IR215.

This is the tier the autofix guardrail depends on. Every code here is an ERROR
that is never autofixable, because each one means the IR says something its author
did not: a cue pointing at an object that was never declared, an operation applied
to a kind it cannot animate, a relationship that cannot hold. Repairing those
needs to know what was *meant* -- the bounded ``RepairAgent``'s job. Dropping the
offending cue instead would render a plausible video with a satellite missing.

Each test asserts the exact set of **errors**, so a check that fires twice, or
drags an unrelated code along with it, fails here rather than in the repair loop.
Incidental pacing warnings are the pacing module's business.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from manorem_core import Code, DiagnosticBag, Severity
from manorem_ir import (
    DEFAULT_REGISTRY,
    AnchorPlacement,
    CameraSpec,
    Cue,
    LayoutKind,
    LayoutSlot,
    LayoutSpec,
    ObjectKind,
    OperationRegistry,
    RelationKind,
    Scene,
    SemanticOp,
    SlotPlacement,
    TimeExpr,
    ValidationContext,
    after,
    at_narration,
    at_seconds,
    lasting,
    spanning,
    validate_scene,
    with_cue,
)
from tests.support.diag import error_codes, only
from tests.support.ir_builders import (
    arrow_obj,
    cue,
    dot_obj,
    group,
    group_obj,
    relationship,
    scene_with,
    segment,
    show,
    text_obj,
    valid_scene,
)

_ONLY_SHOW = OperationRegistry((DEFAULT_REGISTRY.require(SemanticOp.SHOW),))


def _with_last_cue(replacement: Cue) -> Scene:
    """The baseline scene with its final cue swapped out.

    Objects, narration and the first two cues stay valid, so the replacement is
    the only deviation and the asserted error set can be exact.
    """
    return scene_with(timeline=[*valid_scene().timeline[:2], replacement])


class TestUnknownObjectRef:
    """IR201. An object id can hide in six places; all of them are checked."""

    def test_cue_target(self) -> None:
        # The canonical failure: a cue for a satellite the planner never declared.
        scene = _with_last_cue(
            cue(
                "pulse",
                SemanticOp.HIGHLIGHT,
                ["satellite_4"],
                at=after("show_phone"),
                duration=lasting(1.0),
            )
        )
        bag = validate_scene(scene)

        assert error_codes(bag) == {Code.IR201_UNKNOWN_OBJECT_REF}
        diagnostic = only(bag, Code.IR201_UNKNOWN_OBJECT_REF)
        assert diagnostic.pointer == "/timeline/2/targets/0"
        assert diagnostic.object_id == "satellite_4"
        assert "satellite_4" in diagnostic.message

    def test_anchor_reference(self) -> None:
        scene = scene_with(
            objects=[text_obj("title"), dot_obj("phone", placement=AnchorPlacement(ref="sat_4"))]
        )
        bag = validate_scene(scene)

        assert error_codes(bag) == {Code.IR201_UNKNOWN_OBJECT_REF}
        assert only(bag, Code.IR201_UNKNOWN_OBJECT_REF).pointer == "/objects/1/placement/ref"

    def test_arrow_endpoint(self) -> None:
        scene = scene_with(
            objects=[text_obj("title"), dot_obj("phone"), arrow_obj("beam", "phone", "sat_4")]
        )
        bag = validate_scene(scene)

        assert error_codes(bag) == {Code.IR201_UNKNOWN_OBJECT_REF}
        assert only(bag, Code.IR201_UNKNOWN_OBJECT_REF).pointer == "/objects/2/props/end"

    def test_relationship_endpoint(self) -> None:
        scene = scene_with(
            relationships=[relationship(RelationKind.CONNECTED_TO, "phone", "sat_4")]
        )
        bag = validate_scene(scene)

        assert error_codes(bag) == {Code.IR201_UNKNOWN_OBJECT_REF}
        assert only(bag, Code.IR201_UNKNOWN_OBJECT_REF).pointer == "/relationships/0/target"

    def test_camera_follow(self) -> None:
        bag = validate_scene(scene_with(camera=CameraSpec(follow="sat_4")))

        assert error_codes(bag) == {Code.IR201_UNKNOWN_OBJECT_REF}
        assert only(bag, Code.IR201_UNKNOWN_OBJECT_REF).pointer == "/camera/follow"

    def test_narration_mention(self) -> None:
        # ``mentions`` is what a future Visual QA stage compares against what is
        # actually on screen, so a dangling mention is a defect, not a note.
        scene = scene_with(narration=[segment("line_one", "Where is it?", mentions=["sat_4"])])
        bag = validate_scene(scene)

        assert error_codes(bag) == {Code.IR201_UNKNOWN_OBJECT_REF}
        assert only(bag, Code.IR201_UNKNOWN_OBJECT_REF).pointer == "/narration/0/mentions/0"


class TestUnknownTimingRefs:
    @pytest.mark.parametrize("at", [after("ghost_cue"), with_cue("ghost_cue", 0.5)])
    def test_scheduling_against_a_missing_cue_is_ir202(self, at: TimeExpr) -> None:
        scene = _with_last_cue(
            cue("pulse", SemanticOp.HIGHLIGHT, ["phone"], at=at, duration=lasting(1.0))
        )
        bag = validate_scene(scene)

        assert error_codes(bag) == {Code.IR202_UNKNOWN_CUE_REF}
        assert only(bag, Code.IR202_UNKNOWN_CUE_REF).pointer == "/timeline/2/at/cue"

    def test_anchoring_to_a_missing_segment_is_ir203(self) -> None:
        scene = _with_last_cue(
            cue(
                "pulse",
                SemanticOp.HIGHLIGHT,
                ["phone"],
                at=at_narration("ghost"),
                duration=lasting(1.0),
            )
        )
        bag = validate_scene(scene)

        assert error_codes(bag) == {Code.IR203_UNKNOWN_NARRATION_REF}
        assert only(bag, Code.IR203_UNKNOWN_NARRATION_REF).pointer == "/timeline/2/at/segment"

    def test_borrowing_duration_from_a_missing_segment_is_ir203(self) -> None:
        # Narration-derived durations are the mechanism behind narration sync, so a
        # dangling segment id silently unsyncs the scene if it is not caught here.
        scene = _with_last_cue(
            cue(
                "pulse",
                SemanticOp.HIGHLIGHT,
                ["phone"],
                at=after("show_phone"),
                duration=spanning("ghost"),
            )
        )
        bag = validate_scene(scene)

        assert error_codes(bag) == {Code.IR203_UNKNOWN_NARRATION_REF}
        assert only(bag, Code.IR203_UNKNOWN_NARRATION_REF).pointer == "/timeline/2/duration/segment"


class TestTimelineCycle:
    """IR204. A cycle has no schedule at all, so it cannot be lowered."""

    def test_cue_scheduled_against_itself(self) -> None:
        scene = _with_last_cue(
            cue("pulse", SemanticOp.HIGHLIGHT, ["phone"], at=after("pulse"), duration=lasting(1.0))
        )
        bag = validate_scene(scene)

        assert error_codes(bag) == {Code.IR204_TIMELINE_CYCLE}
        assert only(bag, Code.IR204_TIMELINE_CYCLE).pointer == "/timeline/2/at/cue"

    def test_mutual_cycle_is_reported_once_against_the_timeline(self) -> None:
        scene = scene_with(
            timeline=[
                show("show_title", ["title"], duration=lasting(1.0)),
                show("show_phone", ["phone"], at=after("pulse_phone"), duration=lasting(1.0)),
                cue(
                    "pulse_phone",
                    SemanticOp.HIGHLIGHT,
                    ["phone"],
                    at=after("show_phone"),
                    duration=lasting(1.0),
                ),
            ]
        )
        bag = validate_scene(scene)

        assert error_codes(bag) == {Code.IR204_TIMELINE_CYCLE}
        diagnostic = only(bag, Code.IR204_TIMELINE_CYCLE)
        assert diagnostic.pointer == "/timeline"
        assert "show_phone" in diagnostic.message
        assert "pulse_phone" in diagnostic.message
        assert diagnostic.hint is not None


class TestOperationVocabulary:
    """IR205/IR206/IR214/IR211: the closed vocabulary, enforced from the table."""

    def test_operation_no_enabled_skill_declares_is_ir205(self) -> None:
        # A registry restricted to the enabled skills' operations is how the closed
        # vocabulary is enforced per scene; DEFAULT_REGISTRY declares every core op.
        bag = validate_scene(valid_scene(), ValidationContext(registry=_ONLY_SHOW))

        assert error_codes(bag) == {Code.IR205_UNKNOWN_OP}
        diagnostic = only(bag, Code.IR205_UNKNOWN_OP)
        assert diagnostic.pointer == "/timeline/2/op"
        assert "highlight" in diagnostic.message

    def test_unknown_op_suppresses_target_checks(self) -> None:
        # With no declaration there is nothing to check the kind against, and
        # guessing would add a second, misleading diagnostic for one fault.
        scene = _with_last_cue(
            cue(
                "trace_it",
                SemanticOp.TRACE,
                ["title"],
                at=after("show_phone"),
                duration=lasting(1.0),
            )
        )
        bag = validate_scene(scene, ValidationContext(registry=_ONLY_SHOW))

        assert error_codes(bag) == {Code.IR205_UNKNOWN_OP}

    def test_kind_the_operation_cannot_animate_is_ir206(self) -> None:
        scene = _with_last_cue(
            cue(
                "trace_it",
                SemanticOp.TRACE,
                ["title"],
                at=after("show_phone"),
                duration=lasting(1.0),
            )
        )
        bag = validate_scene(scene)

        assert error_codes(bag) == {Code.IR206_TARGET_KIND_NOT_ALLOWED}
        diagnostic = only(bag, Code.IR206_TARGET_KIND_NOT_ALLOWED)
        assert diagnostic.pointer == "/timeline/2/targets/0"
        assert diagnostic.object_id == "title"
        assert diagnostic.hint is not None and "dot" in diagnostic.hint

    def test_group_target_is_checked_member_by_member(self) -> None:
        # Targets resolve through groups, so the finding names the offending member
        # -- the id a repair patch would have to touch.
        scene = scene_with(
            groups=[group("pair", ["title", "phone"])],
            timeline=[
                *valid_scene().timeline[:2],
                cue(
                    "trace_it",
                    SemanticOp.TRACE,
                    ["pair"],
                    at=after("show_phone"),
                    duration=lasting(1.0),
                ),
            ],
        )
        bag = validate_scene(scene)

        assert error_codes(bag) == {Code.IR206_TARGET_KIND_NOT_ALLOWED}
        assert only(bag, Code.IR206_TARGET_KIND_NOT_ALLOWED).object_id == "title"

    @pytest.mark.parametrize(
        ("op", "expected"),
        [(SemanticOp.CONNECT, "expected 2"), (SemanticOp.COMPARE, "expected 2-6")],
    )
    def test_too_few_targets_is_ir214(self, op: SemanticOp, expected: str) -> None:
        scene = _with_last_cue(
            cue("pair_up", op, ["phone"], at=after("show_phone"), duration=lasting(1.0))
        )
        bag = validate_scene(scene)

        assert error_codes(bag) == {Code.IR214_TARGET_COUNT_MISMATCH}
        diagnostic = only(bag, Code.IR214_TARGET_COUNT_MISMATCH)
        assert expected in diagnostic.message
        assert diagnostic.pointer == "/timeline/2/targets"

    def test_too_many_targets_is_ir214(self) -> None:
        scene = scene_with(
            objects=[text_obj("title"), dot_obj("phone"), dot_obj("beacon")],
            timeline=[
                show("show_all", ["title", "phone", "beacon"], duration=lasting(1.0)),
                cue(
                    "swap",
                    SemanticOp.TRANSFORM,
                    ["title", "phone", "beacon"],
                    at=at_seconds(1.5),
                    duration=lasting(1.0),
                ),
            ],
        )
        bag = validate_scene(scene)

        assert error_codes(bag) == {Code.IR214_TARGET_COUNT_MISMATCH}
        assert "3 target(s)" in only(bag, Code.IR214_TARGET_COUNT_MISMATCH).message

    @pytest.mark.parametrize(
        ("op", "targets", "missing"),
        [(SemanticOp.SIMULATE, ["phone"], "behaviour"), (SemanticOp.ACCUMULATE, ["title"], "to")],
    )
    def test_missing_required_param_is_ir211(
        self, op: SemanticOp, targets: list[str], missing: str
    ) -> None:
        scene = _with_last_cue(
            cue("do_it", op, targets, at=after("show_phone"), duration=lasting(1.0))
        )
        bag = validate_scene(scene)

        assert error_codes(bag) == {Code.IR211_MISSING_REQUIRED_PARAM}
        diagnostic = only(bag, Code.IR211_MISSING_REQUIRED_PARAM)
        assert missing in diagnostic.message
        assert diagnostic.pointer == "/timeline/2/params"

    def test_supplying_the_param_satisfies_the_signature(self) -> None:
        scene = _with_last_cue(
            cue(
                "do_it",
                SemanticOp.SIMULATE,
                ["phone"],
                at=after("show_phone"),
                duration=lasting(1.0),
                behaviour="orbit",
            )
        )

        assert error_codes(validate_scene(scene)) == set()


class TestUseBeforeShow:
    """IR207. Manim would render the animation onto nothing at all."""

    def test_object_never_shown(self) -> None:
        scene = scene_with(
            timeline=[
                show("show_title", ["title"], duration=lasting(1.0)),
                cue(
                    "pulse_phone",
                    SemanticOp.HIGHLIGHT,
                    ["phone"],
                    at=after("show_title"),
                    duration=lasting(1.0),
                ),
            ]
        )
        bag = validate_scene(scene)

        assert error_codes(bag) == {Code.IR207_USE_BEFORE_SHOW}
        diagnostic = only(bag, Code.IR207_USE_BEFORE_SHOW)
        assert diagnostic.pointer == "/timeline/1/targets/0"
        assert diagnostic.object_id == "phone"
        assert "never shown" in diagnostic.message

    def test_object_shown_later_in_the_timeline(self) -> None:
        # Declaration order is irrelevant; only the resolved schedule matters.
        scene = scene_with(
            timeline=[
                show("show_title", ["title"], duration=lasting(1.0)),
                cue(
                    "pulse_phone",
                    SemanticOp.HIGHLIGHT,
                    ["phone"],
                    at=at_seconds(0.5),
                    duration=lasting(1.0),
                ),
                show("show_phone", ["phone"], at=at_seconds(2.0), duration=lasting(1.0)),
            ]
        )
        bag = validate_scene(scene)

        assert error_codes(bag) == {Code.IR207_USE_BEFORE_SHOW}
        assert "before it appears" in only(bag, Code.IR207_USE_BEFORE_SHOW).message

    def test_unresolved_start_is_not_reported_as_too_early(self) -> None:
        # The check is deliberately conservative: pass P4 repeats it against the
        # quantized schedule. Reporting a *maybe* here would train callers to
        # ignore the code.
        scene = scene_with(
            timeline=[
                show("show_title", ["title"], duration=lasting(1.0)),
                cue(
                    "pulse_phone",
                    SemanticOp.HIGHLIGHT,
                    ["phone"],
                    at=after("ghost"),
                    duration=lasting(1.0),
                ),
                show("show_phone", ["phone"], at=at_seconds(2.0), duration=lasting(1.0)),
            ]
        )
        bag = validate_scene(scene)

        assert error_codes(bag) == {Code.IR202_UNKNOWN_CUE_REF}


class TestInvalidRelationship:
    """IR208. A relationship that cannot hold has no layout or geometry meaning."""

    def test_self_loop(self) -> None:
        scene = scene_with(
            relationships=[relationship(RelationKind.CONNECTED_TO, "phone", "phone")]
        )
        bag = validate_scene(scene)

        assert error_codes(bag) == {Code.IR208_INVALID_RELATIONSHIP}
        diagnostic = only(bag, Code.IR208_INVALID_RELATIONSHIP)
        assert diagnostic.pointer == "/relationships/0"
        assert diagnostic.object_id == "phone"

    def test_containment_cycle(self) -> None:
        # ``parent_of``/``contains`` feed the tree and graph layout solvers, which
        # need a root; a loop makes the solve non-terminating rather than ugly.
        scene = scene_with(
            relationships=[
                relationship(RelationKind.PARENT_OF, "title", "phone"),
                relationship(RelationKind.CONTAINS, "phone", "title"),
            ]
        )
        bag = validate_scene(scene)

        assert error_codes(bag) == {Code.IR208_INVALID_RELATIONSHIP}
        diagnostic = only(bag, Code.IR208_INVALID_RELATIONSHIP)
        assert diagnostic.pointer == "/relationships"
        assert diagnostic.hint is not None

    def test_anchor_cycle(self) -> None:
        # Anchors resolve positionally, so a cycle has no fixed point to solve for.
        scene = scene_with(
            objects=[
                text_obj("title", placement=AnchorPlacement(ref="phone")),
                dot_obj("phone", placement=AnchorPlacement(ref="title")),
            ]
        )
        bag = validate_scene(scene)

        assert error_codes(bag) == {Code.IR208_INVALID_RELATIONSHIP}
        assert only(bag, Code.IR208_INVALID_RELATIONSHIP).pointer == "/objects"


@dataclass(frozen=True, slots=True)
class _RejectingConstraint:
    """A stand-in for a skill-contributed rule, e.g. networks' flow-needs-an-edge.

    Constraints are *injected*, never imported, so ``manorem_ir`` never depends on
    ``manorem_skills``. This test therefore exercises the seam, not any real rule.
    """

    id: str = "test.always_rejects"

    def check(self, scene: Scene, bag: DiagnosticBag, base: str) -> None:
        bag.add(
            Code.IR209_UNSATISFIED_SKILL_CONSTRAINT,
            f"scene {scene.id!r} violates {self.id}",
            pointer=f"{base}/timeline",
            scene_id=scene.id,
        )


class TestSkillConstraints:
    """IR209. The extension point through which skills own their own semantics."""

    def test_injected_constraint_can_reject_a_scene(self) -> None:
        ctx = ValidationContext(constraints=(_RejectingConstraint(),))
        bag = validate_scene(valid_scene(), ctx)

        assert error_codes(bag) == {Code.IR209_UNSATISFIED_SKILL_CONSTRAINT}
        assert only(bag, Code.IR209_UNSATISFIED_SKILL_CONSTRAINT).pointer == "/timeline"

    def test_the_tier_is_silent_with_nothing_injected(self) -> None:
        assert Code.IR209_UNSATISFIED_SKILL_CONSTRAINT not in validate_scene(valid_scene()).codes()


class TestSceneVocabulary:
    """IR210/IR215: a scene may only ask for what the enabled skills provide."""

    def test_unknown_skill_is_ir210(self) -> None:
        ctx = ValidationContext(known_skills=frozenset({"core"}))
        bag = validate_scene(scene_with(skills=["core", "astrophysics"]), ctx)

        assert error_codes(bag) == {Code.IR210_UNKNOWN_SKILL}
        diagnostic = only(bag, Code.IR210_UNKNOWN_SKILL)
        assert diagnostic.pointer == "/skills/1"
        assert diagnostic.hint is not None and "core" in diagnostic.hint

    def test_skills_are_unchecked_when_the_caller_does_not_say_what_it_can_load(self) -> None:
        # A bare ``validate_scene`` is a schema-level check; only the CLI and the
        # pipeline know which packs are installed.
        scene = scene_with(skills=["core", "astrophysics"])

        assert error_codes(validate_scene(scene)) == set()

    def test_object_kind_no_enabled_skill_provides_is_ir215(self) -> None:
        ctx = ValidationContext(allowed_kinds=frozenset({ObjectKind.TEXT}))
        bag = validate_scene(valid_scene(), ctx)

        assert error_codes(bag) == {Code.IR215_UNKNOWN_OBJECT_KIND}
        diagnostic = only(bag, Code.IR215_UNKNOWN_OBJECT_KIND)
        assert diagnostic.pointer == "/objects/1/kind"
        assert diagnostic.object_id == "phone"
        assert diagnostic.hint is not None

    def test_kinds_are_unchecked_by_default(self) -> None:
        assert error_codes(validate_scene(valid_scene())) == set()


class TestUnknownGroupMember:
    """IR212. Reported per member, because that is the id a patch must touch."""

    def test_structural_group(self) -> None:
        scene = scene_with(groups=[group("constellation", ["phone", "satellite_4"])])
        bag = validate_scene(scene)

        assert error_codes(bag) == {Code.IR212_UNKNOWN_GROUP_MEMBER}
        diagnostic = only(bag, Code.IR212_UNKNOWN_GROUP_MEMBER)
        assert diagnostic.pointer == "/groups/0/members/1"
        assert diagnostic.object_id == "constellation"

    def test_group_object_props(self) -> None:
        # A group *object* keeps its members in typed props, a different pointer
        # path to the same class of fault -- so both are checked.
        scene = scene_with(
            objects=[text_obj("title"), dot_obj("phone"), group_obj("cluster", ["satellite_4"])]
        )
        bag = validate_scene(scene)

        assert error_codes(bag) == {Code.IR212_UNKNOWN_GROUP_MEMBER}
        assert only(bag, Code.IR212_UNKNOWN_GROUP_MEMBER).pointer == "/objects/2/props/members/0"


class TestUnknownLayoutSlot:
    """IR213. Slot placement is only meaningful against a layout that defines it."""

    def test_slot_missing_from_the_layout(self) -> None:
        scene = scene_with(
            objects=[text_obj("title"), dot_obj("phone", placement=SlotPlacement(slot="left"))]
        )
        bag = validate_scene(scene)

        assert error_codes(bag) == {Code.IR213_UNKNOWN_LAYOUT_SLOT}
        diagnostic = only(bag, Code.IR213_UNKNOWN_LAYOUT_SLOT)
        assert diagnostic.pointer == "/objects/1/placement/slot"
        assert "none defined" in diagnostic.message

    def test_declared_slot_is_accepted(self) -> None:
        scene = scene_with(
            objects=[text_obj("title"), dot_obj("phone", placement=SlotPlacement(slot="left"))],
            layout=LayoutSpec(
                kind=LayoutKind.SPLIT,
                slots=[LayoutSlot(name="left"), LayoutSlot(name="right")],
            ),
        )

        assert error_codes(validate_scene(scene)) == set()


class TestSemanticDamageIsNeverAutofixable:
    """The guardrail itself, asserted end to end over one thoroughly broken scene.

    ``autofixable`` is derived from the code rather than stored per diagnostic, so
    no caller can mark a semantic failure as safe to repair mechanically. Dropping
    any of these would render a plausible video that silently omits content.
    """

    def test_every_semantic_finding_is_a_hard_error(self) -> None:
        scene = scene_with(
            objects=[
                text_obj("title", placement=AnchorPlacement(ref="ghost")),
                dot_obj("phone"),
            ],
            groups=[group("pair", ["ghost"])],
            relationships=[relationship(RelationKind.CONNECTED_TO, "phone", "phone")],
            camera=CameraSpec(follow="ghost"),
            timeline=[
                show("show_phone", ["phone"], duration=lasting(1.0)),
                cue(
                    "pulse",
                    SemanticOp.HIGHLIGHT,
                    ["ghost"],
                    at=after("nowhere"),
                    duration=lasting(1.0),
                ),
            ],
        )
        bag = validate_scene(scene)
        semantic = [d for d in bag if d.code.value.startswith("IR2")]

        assert error_codes(bag) == {
            Code.IR201_UNKNOWN_OBJECT_REF,
            Code.IR202_UNKNOWN_CUE_REF,
            Code.IR208_INVALID_RELATIONSHIP,
            Code.IR212_UNKNOWN_GROUP_MEMBER,
        }
        assert len(semantic) == 6
        assert all(d.severity is Severity.ERROR for d in semantic)
        assert not any(d.autofixable for d in semantic)
