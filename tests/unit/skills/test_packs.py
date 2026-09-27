"""Rules about the packs themselves: coverage, partition, and safe specialization.

Two ratchets carry this module. The **coverage** tests assert that the four built-in
packs between them provide every ``ObjectKind`` and every ``SemanticOp``, so adding
an enum member without a pack to offer it fails here rather than surfacing as a kind
no scene can legally use or an operation ``IR205`` calls unknown. The **partition**
test asserts each kind is claimed exactly once, so there is always one obvious pack
to enable for a given object.

The specialization tests guard composition. ``OperationRegistry.register`` is
last-write-wins, so a shared operation whose declarations differ between packs would
make the outcome depend on resolution order. Asserting the declarations are
*identical* means the order cannot decide anything -- and asserting any deviation
from the base table only ever *narrows* it means a pack cannot quietly grant itself
more than :mod:`manorem_ir` declared.
"""

from __future__ import annotations

from collections import Counter

import pytest

from manorem_ir import DEFAULT_REGISTRY, ObjectKind, OperationDecl, SemanticOp
from manorem_skills import BASE_PACK, BUILTIN_PACKS, CORE, SkillPack


def _packs_providing(op: SemanticOp) -> list[SkillPack]:
    return [pack for pack in BUILTIN_PACKS if op in pack.operations]


class TestTheVocabularyIsFullyCovered:
    """Both closed enums are accounted for. This is the ratchet."""

    def test_every_object_kind_is_provided_by_a_pack(self) -> None:
        provided = frozenset[ObjectKind]().union(*(p.primitives.keys() for p in BUILTIN_PACKS))
        missing = sorted(k.value for k in frozenset(ObjectKind) - provided)
        assert not missing, f"object kinds no pack provides: {missing}"

    def test_every_operation_is_provided_by_a_pack(self) -> None:
        provided = frozenset[SemanticOp]().union(*(p.operations.keys() for p in BUILTIN_PACKS))
        missing = sorted(o.value for o in frozenset(SemanticOp) - provided)
        assert not missing, f"operations no pack provides: {missing}"

    def test_no_pack_provides_a_kind_outside_the_enum(self) -> None:
        # Guards the guard: a frozenset union would happily hide a typo'd member.
        for pack in BUILTIN_PACKS:
            assert all(isinstance(kind, ObjectKind) for kind in pack.primitives)

    def test_each_kind_is_claimed_by_exactly_one_pack(self) -> None:
        counts = Counter(kind for pack in BUILTIN_PACKS for kind in pack.primitives)
        shared = sorted(kind.value for kind, n in counts.items() if n > 1)
        assert not shared, f"kinds claimed by more than one pack: {shared}"

    def test_core_is_the_base_pack(self) -> None:
        # The scene that lists only ``networks`` still needs ``show``.
        assert BASE_PACK is CORE
        assert SemanticOp.SHOW in CORE.operations


class TestSpecializationOnlyNarrows:
    """A pack may narrow an operation for its domain. It may not widen one."""

    def test_the_shared_operations_are_the_expected_ones(self) -> None:
        # An overlap should be a deliberate, visible decision. ``trace`` is the one:
        # a trail behind a moving dot and a route across a map are the same operation.
        shared = {op.value for op in SemanticOp if len(_packs_providing(op)) > 1}
        assert shared == {"trace"}

    def test_packs_sharing_an_operation_declare_it_identically(self) -> None:
        for op in sorted(SemanticOp, key=lambda o: o.value):
            declarations = [pack.operations[op] for pack in _packs_providing(op)]
            if len(declarations) < 2:
                continue
            assert all(decl == declarations[0] for decl in declarations), (
                f"{op.value} is declared differently by different packs, so "
                "composition order would decide which one a scene gets"
            )

    @pytest.mark.parametrize(
        ("pack", "op"),
        [(pack, op) for pack in BUILTIN_PACKS for op in sorted(pack.operations, key=str)],
        ids=lambda value: value.id if isinstance(value, SkillPack) else str(value),
    )
    def test_a_declaration_never_widens_the_base_table(
        self, pack: SkillPack, op: SemanticOp
    ) -> None:
        decl: OperationDecl = pack.operations[op]
        base = DEFAULT_REGISTRY.require(op)
        assert decl.allowed_kinds <= base.allowed_kinds
        assert decl.min_targets >= base.min_targets
        assert decl.max_targets <= base.max_targets
        # Dropping a required param would accept more input, not less.
        assert set(base.required_params()) <= set(decl.required_params())
        # Flags the compiler branches on: a pack may not reinterpret them.
        assert (decl.is_camera, decl.introduces, decl.removes) == (
            base.is_camera,
            base.introduces,
            base.removes,
        )

    def test_a_declaration_is_keyed_by_its_own_operation(self) -> None:
        for pack in BUILTIN_PACKS:
            for op, decl in pack.operations.items():
                assert decl.op is op, f"{pack.id} keys {decl.op.value} under {op.value}"

    def test_a_primitive_is_keyed_by_its_own_kind(self) -> None:
        for pack in BUILTIN_PACKS:
            for kind, decl in pack.primitives.items():
                assert decl.kind is kind, f"{pack.id} keys {decl.kind.value} under {kind.value}"


class TestPacksAreWellFormed:
    """The prose is part of the contract: it is what the model reads."""

    def test_pack_ids_are_unique(self) -> None:
        ids = [pack.id for pack in BUILTIN_PACKS]
        assert len(ids) == len(set(ids))

    @pytest.mark.parametrize("pack", BUILTIN_PACKS, ids=lambda p: p.id)
    def test_a_pack_describes_itself(self, pack: SkillPack) -> None:
        assert pack.id and pack.id.islower()
        assert pack.version
        assert pack.summary.endswith(".")
        assert pack.prompt_fragment.strip(), "a pack with no prompt fragment teaches nothing"

    @pytest.mark.parametrize("pack", BUILTIN_PACKS, ids=lambda p: p.id)
    def test_a_pack_provides_something(self, pack: SkillPack) -> None:
        assert pack.primitives or pack.operations

    def test_constraint_ids_are_unique_and_namespaced(self) -> None:
        seen: list[str] = []
        for pack in BUILTIN_PACKS:
            for constraint in pack.constraints:
                assert constraint.id.startswith(f"{pack.id}."), (
                    f"constraint {constraint.id!r} does not name its pack, so a "
                    "diagnostic cannot be traced back to what enabled it"
                )
                seen.append(constraint.id)
        assert len(seen) == len(set(seen))
