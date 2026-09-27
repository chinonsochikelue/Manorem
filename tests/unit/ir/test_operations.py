"""The operation table: one row per semantic operation, read by three consumers.

Validation is table-driven, cue durations default from the same rows, and the
IR-generation prompt is built from them too -- which is the mechanism that keeps
the model's menu and the validator's rules from drifting apart. That guarantee
only holds if the table itself is coherent, so most of what follows sweeps every
declaration rather than testing one, and reports every offending row at once.

The registry is a *parameter* everywhere it is used, never a global read at the
point of use. Skills extend the vocabulary by layering on a copy, and the last
test in each group holds that line.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from manorem_ir import (
    ANY_KIND,
    CAMERA_OPS,
    CORE_OPERATIONS,
    DEFAULT_REGISTRY,
    ObjectKind,
    OperationDecl,
    OperationRegistry,
    ParamDecl,
    SemanticOp,
)


class TestTableIntegrity:
    """Properties every declaration must hold for the table to mean anything."""

    def test_every_operation_in_the_vocabulary_is_declared(self) -> None:
        # An op in the enum but not in the table would be reported as unknown
        # vocabulary (IR205) even though the IR models accept it -- a
        # contradiction an author could not act on.
        assert DEFAULT_REGISTRY.known_ops() == frozenset(SemanticOp)

    def test_no_operation_is_declared_twice(self) -> None:
        # The registry is a dict keyed by op, so a duplicate row would silently
        # shadow the earlier one rather than failing to load.
        assert len(CORE_OPERATIONS) == len({decl.op for decl in CORE_OPERATIONS})

    def test_target_counts_are_coherent(self) -> None:
        bad = [
            decl.op.value
            for decl in CORE_OPERATIONS
            if decl.min_targets > decl.max_targets or decl.max_targets < 1
        ]

        assert bad == []

    def test_every_declaration_carries_a_summary(self) -> None:
        # The summary is what the IR-generation prompt shows the model, so an
        # empty one is a silently unusable operation rather than a cosmetic gap.
        assert [decl.op.value for decl in CORE_OPERATIONS if not decl.summary.strip()] == []

    def test_no_operation_both_introduces_and_removes(self) -> None:
        # The use-before-show check reads these two flags to decide whether an
        # object is on stage; a row claiming both leaves that question unanswerable.
        assert [decl.op.value for decl in CORE_OPERATIONS if decl.introduces and decl.removes] == []

    def test_the_camera_flag_agrees_with_the_enum(self) -> None:
        # Two consumers answer "is this a camera move" from two places: ``Cue``
        # reads ``CAMERA_OPS`` and the compiler reads the declaration. If they
        # disagree, a camera cue lands on the wrong track.
        assert {decl.op for decl in CORE_OPERATIONS if decl.is_camera} == CAMERA_OPS

    def test_camera_operations_leave_the_stage_contents_alone(self) -> None:
        # A camera move changes framing, never what exists. Were one to introduce
        # or remove, concurrency counts and IR207 would both start lying.
        camera = [decl for decl in CORE_OPERATIONS if decl.is_camera]

        assert camera != []
        assert [decl.op.value for decl in camera if decl.introduces or decl.removes] == []

    def test_parameter_names_are_unique_within_an_operation(self) -> None:
        # ``param`` returns the first match, so a duplicate would be unreachable
        # and its "required" flag would never be enforced.
        bad = [
            decl.op.value
            for decl in CORE_OPERATIONS
            if len(decl.params) != len({param.name for param in decl.params})
        ]

        assert bad == []

    def test_an_enum_parameter_declares_its_choices(self) -> None:
        # Validation checks a supplied value against ``choices``, so an empty one
        # would reject everything the model could possibly write.
        bad = [
            f"{decl.op.value}.{param.name}"
            for decl in CORE_OPERATIONS
            for param in decl.params
            if param.type == "enum" and not param.choices
        ]

        assert bad == []

    def test_a_declared_default_is_itself_a_legal_choice(self) -> None:
        # The default is what gets substituted when a cue omits the parameter, so
        # a default outside ``choices`` would only surface at render time.
        bad = [
            f"{decl.op.value}.{param.name}"
            for decl in CORE_OPERATIONS
            for param in decl.params
            if param.choices and param.default is not None and param.default not in param.choices
        ]

        assert bad == []

    def test_any_kind_is_every_kind(self) -> None:
        assert frozenset(ObjectKind) == ANY_KIND

    def test_a_narrowed_operation_really_is_narrowed(self) -> None:
        # ``ANY_KIND`` is the permissive default; rows that narrow it are what
        # give IR206 something to catch. Accumulating on a dot means nothing.
        decl = DEFAULT_REGISTRY.require(SemanticOp.ACCUMULATE)

        assert decl.allowed_kinds < ANY_KIND
        assert ObjectKind.DOT not in decl.allowed_kinds
        assert ObjectKind.CHART in decl.allowed_kinds

    def test_a_non_positive_default_duration_is_rejected(self) -> None:
        # A zero-length cue divides by nothing downstream. The model refuses one
        # at construction, so no skill can introduce it by hand-writing a row.
        with pytest.raises(ValidationError):
            OperationDecl(op=SemanticOp.SHOW, summary="Instant.", default_duration=0.0)


class TestDeclarationLookups:
    """What a declaration answers about itself."""

    def test_required_params_lists_only_the_required_ones(self) -> None:
        # ``simulate`` cannot do anything without a behaviour; ``show`` has an
        # optional style and therefore nothing the author must supply.
        assert DEFAULT_REGISTRY.require(SemanticOp.SIMULATE).required_params() == ("behaviour",)
        assert DEFAULT_REGISTRY.require(SemanticOp.SHOW).required_params() == ()

    def test_a_parameter_can_be_looked_up_by_name(self) -> None:
        param = DEFAULT_REGISTRY.require(SemanticOp.SHOW).param("style")

        assert param is not None
        assert param.choices == ("create", "write", "fade", "grow", "draw")

    def test_an_unknown_parameter_name_returns_none(self) -> None:
        assert DEFAULT_REGISTRY.require(SemanticOp.SHOW).param("colour") is None


class TestRegistry:
    """Lookup, extension, and the isolation that makes extension safe."""

    def test_a_known_operation_resolves(self) -> None:
        decl = DEFAULT_REGISTRY.get(SemanticOp.HIDE)

        assert decl is not None
        assert (decl.op, decl.default_duration, decl.removes) == (SemanticOp.HIDE, 0.6, True)

    def test_an_unknown_operation_is_absent_rather_than_an_error(self) -> None:
        # ``get`` is the total form: resolution uses it so a scene with an
        # undeclared op still yields times for every other cue.
        empty = OperationRegistry(())

        assert empty.get(SemanticOp.SHOW) is None
        assert SemanticOp.SHOW not in empty
        assert empty.known_ops() == frozenset()

    def test_require_names_the_operation_it_could_not_find(self) -> None:
        # ``require`` is for callers that have already validated the op, so the
        # message has to be actionable when that assumption turns out to be wrong.
        with pytest.raises(KeyError, match="show"):
            OperationRegistry(()).require(SemanticOp.SHOW)

    def test_membership_covers_the_whole_core_vocabulary(self) -> None:
        assert all(op in DEFAULT_REGISTRY for op in SemanticOp)

    def test_registering_replaces_an_existing_declaration(self) -> None:
        # How a skill retunes an operation for its own domain: a narrower target
        # list, a required parameter, its own pacing -- no branch in the validator.
        registry = OperationRegistry()
        registry.register(
            OperationDecl(
                op=SemanticOp.HIGHLIGHT,
                summary="A slower, stricter highlight.",
                allowed_kinds=frozenset({ObjectKind.NETWORK}),
                params=(ParamDecl(name="hops", type="number", required=True),),
                default_duration=3.0,
            )
        )
        decl = registry.require(SemanticOp.HIGHLIGHT)

        assert (decl.default_duration, decl.required_params()) == (3.0, ("hops",))
        assert decl.allowed_kinds == frozenset({ObjectKind.NETWORK})

    def test_an_override_does_not_leak_into_the_default_table(self) -> None:
        # What makes the previous test safe: one skill's tuning cannot re-time or
        # re-restrict every other project sharing the process.
        registry = OperationRegistry()
        registry.register(
            OperationDecl(op=SemanticOp.HIGHLIGHT, summary="Slow.", default_duration=9.0)
        )
        default = DEFAULT_REGISTRY.require(SemanticOp.HIGHLIGHT)

        assert registry.require(SemanticOp.HIGHLIGHT).default_duration == 9.0
        assert (default.default_duration, default.allowed_kinds) == (0.8, ANY_KIND)

    def test_each_registry_gets_its_own_table(self) -> None:
        # Guards the classic shared-default-argument bug: two registries built the
        # same way must not be the same dict underneath.
        first, second = OperationRegistry(), OperationRegistry()
        first.register(OperationDecl(op=SemanticOp.SHOW, summary="Slow.", default_duration=9.0))

        assert second.require(SemanticOp.SHOW).default_duration == 1.0
