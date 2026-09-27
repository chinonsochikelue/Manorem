"""The packs' ``IR209`` predicates, driven through the real validator.

Exercised end to end rather than by calling ``check`` directly: the seam being
tested is not the predicate alone but the whole path -- a scene's ``skills`` list
resolves to constraints, those reach ``ValidationContext``, and ``validate_scene``
runs them. A predicate that worked in isolation while never being invoked would pass
a unit test and ship nothing.

Every case asserts the exact **error** set. Two behaviours depend on that being
exact: a constraint must fire once per fault (a duplicate would spam the bounded
repair loop), and it must stay silent when another check already owns the defect --
a flow to an object that does not exist is ``IR201``'s finding, and adding ``IR209``
on top would hand the repair agent two diagnostics for one mistake.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from manorem_core import Code, DiagnosticBag
from manorem_ir import (
    Cue,
    Group,
    RelationKind,
    Relationship,
    Scene,
    SceneObject,
    SemanticOp,
    after,
    lasting,
    validate_scene,
)
from manorem_skills import default_registry
from tests.support.diag import error_codes, only
from tests.support.ir_builders import (
    cue,
    dot_obj,
    group,
    make_scene,
    relationship,
    show,
    text_obj,
)

_IR209 = Code.IR209_UNSATISFIED_SKILL_CONSTRAINT


def _check(scene: Scene, *skills: str) -> DiagnosticBag:
    """Validate ``scene`` with those skills enabled, exactly as the pipeline will."""
    resolved = default_registry().resolve(list(skills))
    return validate_scene(scene, resolved.validation_context())


def _connected(source: str, target: str) -> Relationship:
    return relationship(RelationKind.CONNECTED_TO, source, target)


def _flow_scene(
    *,
    links: Sequence[Relationship] = (),
    extra_cues: Sequence[Cue] = (),
    objects: Sequence[SceneObject] | None = None,
    groups: Sequence[Group] = (),
    shown: Sequence[str] = ("sat", "phone"),
    targets: Sequence[str] = ("sat", "phone"),
) -> Scene:
    """Objects shown, then a flow between two of them.

    Everything except the connection is already valid, so an asserted error set of
    exactly ``{IR209}`` means the constraint -- and only the constraint -- fired.
    """
    return make_scene(
        intent="A signal travels from the satellite to the phone.",
        objects=list(objects) if objects is not None else [dot_obj("sat"), dot_obj("phone")],
        groups=list(groups),
        relationships=list(links),
        timeline=[
            show("show_all", list(shown), duration=lasting(1.0)),
            *extra_cues,
            cue(
                "send",
                SemanticOp.FLOW,
                list(targets),
                at=after("show_all"),
                duration=lasting(1.0),
            ),
        ],
    )


class TestFlowFollowsAConnection:
    """The demo's load-bearing rule: a packet needs something to travel along."""

    def test_a_flow_across_empty_space_is_an_error(self) -> None:
        assert error_codes(_check(_flow_scene(), "networks")) == {_IR209}

    def test_the_error_points_at_the_cue(self) -> None:
        # The pointer is the machine contract the repair agent patches against.
        diagnostic = only(_check(_flow_scene(), "networks"), _IR209)
        assert diagnostic.pointer == "/timeline/1"
        assert diagnostic.scene_id == "intro"
        assert diagnostic.hint

    def test_a_declared_connection_satisfies_it(self) -> None:
        assert error_codes(_check(_flow_scene(links=[_connected("sat", "phone")]), "networks")) == (
            set()
        )

    def test_the_connection_may_be_declared_either_way_round(self) -> None:
        # The channel is the same object; which end the author named is not meaning.
        assert error_codes(_check(_flow_scene(links=[_connected("phone", "sat")]), "networks")) == (
            set()
        )

    def test_points_to_is_also_a_link(self) -> None:
        link = relationship(RelationKind.POINTS_TO, "sat", "phone")
        assert error_codes(_check(_flow_scene(links=[link]), "networks")) == set()

    def test_connectivity_is_transitive(self) -> None:
        scene = _flow_scene(
            objects=[dot_obj("sat"), dot_obj("relay"), dot_obj("phone")],
            links=[_connected("sat", "relay"), _connected("relay", "phone")],
            shown=("sat", "relay", "phone"),
        )
        assert error_codes(_check(scene, "networks")) == set()

    def test_a_connect_cue_satisfies_it(self) -> None:
        # A link created in the timeline is as real as one declared up front.
        joining = cue(
            "join",
            SemanticOp.CONNECT,
            ["sat", "phone"],
            at=after("show_all"),
            duration=lasting(0.5),
        )
        assert error_codes(_check(_flow_scene(extra_cues=[joining]), "networks")) == set()

    def test_hierarchy_is_not_a_channel(self) -> None:
        # ``parent_of`` and ``contains`` describe structure; a packet does not travel
        # along containment, so neither may satisfy the rule.
        for kind in (RelationKind.PARENT_OF, RelationKind.CONTAINS):
            link = relationship(kind, "sat", "phone")
            assert error_codes(_check(_flow_scene(links=[link]), "networks")) == {_IR209}, kind

    def test_an_unrelated_link_does_not_satisfy_it(self) -> None:
        scene = _flow_scene(
            objects=[dot_obj("sat"), dot_obj("phone"), dot_obj("tower")],
            links=[_connected("sat", "tower")],
            shown=("sat", "phone", "tower"),
        )
        assert error_codes(_check(scene, "networks")) == {_IR209}

    def test_a_connected_group_member_is_enough(self) -> None:
        # A link may be declared against a group or one of its members, and an ERROR
        # that stops the build should take the reading with no false positives: the
        # packet leaves from the connected part.
        scene = _flow_scene(
            objects=[dot_obj("sat_a"), dot_obj("sat_b"), dot_obj("phone")],
            groups=[group("cluster", ["sat_a", "sat_b"])],
            links=[_connected("sat_a", "phone")],
            shown=("sat_a", "sat_b", "phone"),
            targets=("cluster", "phone"),
        )
        assert error_codes(_check(scene, "networks")) == set()

    def test_a_link_on_the_group_itself_is_enough(self) -> None:
        scene = _flow_scene(
            objects=[dot_obj("sat_a"), dot_obj("sat_b"), dot_obj("phone")],
            groups=[group("cluster", ["sat_a", "sat_b"])],
            links=[_connected("cluster", "phone")],
            shown=("sat_a", "sat_b", "phone"),
            targets=("cluster", "phone"),
        )
        assert error_codes(_check(scene, "networks")) == set()

    def test_an_unknown_endpoint_stays_ir201s_business(self) -> None:
        scene = _flow_scene(targets=("sat", "satellite_4"))
        assert error_codes(_check(scene, "networks")) == {Code.IR201_UNKNOWN_OBJECT_REF}

    def test_the_constraint_does_not_run_without_the_skill(self) -> None:
        # Without ``networks`` the operation itself is unknown -- that is IR205, and
        # the constraint that would have judged it is not even loaded.
        assert error_codes(_check(_flow_scene())) == {Code.IR205_UNKNOWN_OP}

    def test_the_constraint_leaves_the_scene_alone(self) -> None:
        scene = _flow_scene()
        before = scene.model_dump_json()
        _check(scene, "networks")
        assert scene.model_dump_json() == before


class TestPropagationHasSomewhereToGo:
    """The single-target case ``FlowFollowsAConnection`` cannot see."""

    def _scene(
        self, *, links: Sequence[Relationship] = (), targets: Sequence[str] = ("hub",)
    ) -> Scene:
        return make_scene(
            intent="The outage spreads through the network.",
            objects=[dot_obj("hub"), dot_obj("leaf")],
            relationships=list(links),
            timeline=[
                show("show_all", ["hub", "leaf"], duration=lasting(1.0)),
                cue(
                    "spread",
                    SemanticOp.PROPAGATE,
                    list(targets),
                    at=after("show_all"),
                    duration=lasting(1.0),
                ),
            ],
        )

    def test_propagating_from_an_isolated_object_is_an_error(self) -> None:
        bag = _check(self._scene(), "networks")
        assert error_codes(bag) == {_IR209}
        assert only(bag, _IR209).object_id == "hub"

    def test_one_link_is_enough(self) -> None:
        assert error_codes(_check(self._scene(links=[_connected("hub", "leaf")]), "networks")) == (
            set()
        )

    def test_two_targets_are_the_other_constraints_business(self) -> None:
        # Both predicates must not report one fault: with two targets the
        # reachability check owns it, and this one stands down.
        bag = _check(self._scene(targets=("hub", "leaf")), "networks")
        assert len([d for d in bag if d.code is _IR209]) == 1


class TestAccumulationGoesSomewhere:
    """``accumulate``'s params can be individually valid and jointly pointless."""

    def _scene(self, **params: Any) -> Scene:
        return make_scene(
            intent="The count climbs to four satellites.",
            objects=[text_obj("counter", "0")],
            timeline=[
                show("show_counter", ["counter"], duration=lasting(1.0)),
                cue(
                    "climb",
                    SemanticOp.ACCUMULATE,
                    ["counter"],
                    at=after("show_counter"),
                    duration=lasting(1.0),
                    **params,
                ),
            ],
        )

    def test_a_real_accumulation_is_clean(self) -> None:
        assert error_codes(_check(self._scene(to=4), "dataviz")) == set()

    def test_an_explicit_start_is_clean(self) -> None:
        assert error_codes(_check(self._scene(to=4, **{"from": 1}), "dataviz")) == set()

    def test_counting_down_is_allowed(self) -> None:
        # Shrinking is a legitimate story beat; only standing still is not.
        assert error_codes(_check(self._scene(to=1, **{"from": 4}), "dataviz")) == set()

    def test_going_nowhere_is_an_error(self) -> None:
        bag = _check(self._scene(to=0), "dataviz")
        assert error_codes(bag) == {_IR209}
        assert only(bag, _IR209).pointer == "/timeline/1/params"

    def test_the_implicit_start_counts(self) -> None:
        # ``from`` defaults to 0, so ``to=0`` goes nowhere even unstated.
        assert error_codes(_check(self._scene(to=0.0), "dataviz")) == {_IR209}

    def test_a_non_numeric_destination_is_an_error(self) -> None:
        # Nothing in manorem_ir compares a param against its declared type yet, so
        # without this the cue would reach the compiler with to="four".
        assert error_codes(_check(self._scene(to="four"), "dataviz")) == {_IR209}

    def test_a_non_numeric_start_is_an_error(self) -> None:
        assert error_codes(_check(self._scene(to=4, **{"from": "zero"}), "dataviz")) == {_IR209}

    def test_a_boolean_is_not_a_number(self) -> None:
        # ``True`` is an ``int`` in Python; ``accumulate(to=True)`` is a mistake, not
        # a request to grow to 1.
        assert error_codes(_check(self._scene(to=True), "dataviz")) == {_IR209}

    def test_a_missing_destination_stays_ir211s_business(self) -> None:
        assert error_codes(_check(self._scene(), "dataviz")) == {Code.IR211_MISSING_REQUIRED_PARAM}
