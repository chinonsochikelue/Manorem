"""Registry discovery, and what resolving a scene's ``skills`` list composes to.

The behaviours under test are the ones a wrong answer would hide rather than
surface: ``core`` present whether or not a scene asked for it, an unknown skill id
recorded instead of raised or dropped, a duplicate registration refused instead of
silently overwriting, and a resolved operation registry holding *only* the enabled
packs' operations -- which is what gives ``IR205`` its meaning.

Entry-point discovery is driven through a stubbed ``entry_points`` rather than an
installed distribution, so the test stays offline and the two properties that matter
stay assertable: it happens only when asked, and a third-party pack cannot take over
a builtin's id.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from manorem_ir import ObjectKind, SemanticOp, ValidationPolicy
from manorem_skills import (
    CORE,
    DATAVIZ,
    ENTRY_POINT_GROUP,
    GEOGRAPHY,
    NETWORKS,
    SkillPack,
    SkillRegistry,
    default_registry,
    provide,
)
from manorem_skills import registry as registry_module


class TestRegistration:
    def test_a_registry_starts_empty(self) -> None:
        assert len(SkillRegistry()) == 0
        assert SkillRegistry().ids == frozenset()

    def test_builtins_register_under_their_own_ids(self) -> None:
        registry = default_registry()
        assert registry.ids == frozenset({"core", "networks", "geography", "dataviz"})
        assert registry.get("networks") is NETWORKS
        assert "geography" in registry
        assert len(registry) == 4

    def test_iteration_yields_the_registered_packs(self) -> None:
        assert {skill.id for skill in default_registry()} == default_registry().ids

    def test_a_duplicate_id_is_refused(self) -> None:
        # Silent replacement is the failure: every scene would get whichever pack
        # imported last, and nothing would say so.
        registry = SkillRegistry([CORE])
        impostor = SkillPack(id="core", version="9.9", summary="Not the real core.")
        with pytest.raises(ValueError, match="already registered"):
            registry.register(impostor)
        assert registry.get("core") is CORE

    def test_an_unknown_id_names_the_alternatives(self) -> None:
        with pytest.raises(KeyError, match="core, dataviz, geography, networks"):
            default_registry().get("netwroks")

    def test_the_default_registry_is_not_shared(self) -> None:
        # A module-level constant would let one test's registration change what a
        # later test resolves.
        first = default_registry()
        first.register(SkillPack(id="scratch", version="1.0", summary="Temporary."))
        assert "scratch" not in default_registry()


class TestResolutionComposesCoreFirst:
    def test_an_empty_request_still_gets_core(self) -> None:
        resolved = default_registry().resolve()
        assert resolved.ids == ("core",)
        assert SemanticOp.SHOW in resolved.registry

    def test_core_is_prepended_not_appended(self) -> None:
        # Order is fixed so that composition is deterministic, and core goes first
        # so a later pack's specialization is the one that survives.
        assert default_registry().resolve(["networks"]).ids == ("core", "networks")

    def test_core_is_not_duplicated_when_requested_explicitly(self) -> None:
        assert default_registry().resolve(["core", "networks"]).ids == ("core", "networks")

    def test_requested_order_is_preserved(self) -> None:
        resolved = default_registry().resolve(["dataviz", "geography"])
        assert resolved.ids == ("core", "dataviz", "geography")

    def test_a_repeated_request_is_resolved_once(self) -> None:
        assert default_registry().resolve(["networks", "networks"]).ids == ("core", "networks")

    def test_core_is_active_even_when_unregistered(self) -> None:
        # "Always active, whatever Scene.skills says" has to hold for a registry
        # assembled without it, or the claim depends on registration discipline.
        resolved = SkillRegistry([NETWORKS]).resolve(["networks"])
        assert resolved.ids == ("core", "networks")


class TestResolutionIsTotalAndHonest:
    def test_an_unknown_skill_is_recorded_not_raised(self) -> None:
        # Raising would lose the JSON pointer that IR210 reports against.
        resolved = default_registry().resolve(["networks", "astrophysics"])
        assert resolved.unknown == ("astrophysics",)
        assert resolved.ids == ("core", "networks")

    def test_known_skills_covers_the_registry_not_the_request(self) -> None:
        # This is what turns a typo into an IR210 that can name the alternatives.
        resolved = default_registry().resolve(["networks"])
        assert resolved.known_skills == frozenset({"core", "networks", "geography", "dataviz"})

    def test_unknown_ids_keep_their_order_and_repeats(self) -> None:
        resolved = default_registry().resolve(["a", "b", "a"])
        assert resolved.unknown == ("a", "b")


class TestTheComposedVocabulary:
    def test_only_enabled_operations_are_registered(self) -> None:
        # An operation no enabled skill provides must be *unknown*, not merely
        # unusual -- IR205 says "which no enabled skill declares".
        resolved = default_registry().resolve(["networks"])
        assert SemanticOp.FLOW in resolved.registry
        assert SemanticOp.ACCUMULATE not in resolved.registry

    def test_allowed_kinds_is_the_union_of_the_packs_primitives(self) -> None:
        resolved = default_registry().resolve(["geography"])
        assert resolved.allowed_kinds == frozenset(CORE.primitives) | frozenset(
            GEOGRAPHY.primitives
        )
        assert ObjectKind.MAP in resolved.allowed_kinds
        assert ObjectKind.CHART not in resolved.allowed_kinds

    def test_everything_enabled_covers_both_enums(self) -> None:
        resolved = default_registry().resolve(["networks", "geography", "dataviz"])
        assert resolved.allowed_kinds == frozenset(ObjectKind)
        assert resolved.registry.known_ops() == frozenset(SemanticOp)

    def test_constraints_arrive_in_pack_order(self) -> None:
        resolved = default_registry().resolve(["dataviz", "networks"])
        prefixes = [constraint.id.split(".")[0] for constraint in resolved.constraints]
        assert prefixes == ["dataviz"] * len(DATAVIZ.constraints) + ["networks"] * len(
            NETWORKS.constraints
        )

    def test_a_pack_that_was_not_requested_contributes_nothing(self) -> None:
        resolved = default_registry().resolve(["geography"])
        assert not [c for c in resolved.constraints if c.id.startswith("networks.")]

    def test_operations_exposes_the_composed_declarations(self) -> None:
        resolved = default_registry().resolve(["networks"])
        assert set(resolved.operations) == set(resolved.registry.known_ops())
        assert resolved.operations[SemanticOp.FLOW].min_targets == 2

    def test_resolution_is_deterministic(self) -> None:
        request = ["dataviz", "networks", "nope"]
        first = default_registry().resolve(request)
        second = default_registry().resolve(request)
        assert first.ids == second.ids
        assert first.unknown == second.unknown
        assert [c.id for c in first.constraints] == [c.id for c in second.constraints]


class TestTheHandOffToValidation:
    """The one place ``manorem_skills`` and ``manorem_ir`` meet."""

    def test_the_context_carries_all_four_contributions(self) -> None:
        resolved = default_registry().resolve(["networks"])
        ctx = resolved.validation_context()
        assert ctx.registry is resolved.registry
        assert ctx.allowed_kinds == resolved.allowed_kinds
        assert ctx.known_skills == resolved.known_skills
        assert tuple(ctx.constraints) == resolved.constraints

    def test_the_policy_defaults_but_can_be_replaced(self) -> None:
        resolved = default_registry().resolve()
        assert resolved.validation_context().policy == ValidationPolicy()
        strict = ValidationPolicy(strict_lints=True)
        assert resolved.validation_context(policy=strict).policy is strict

    def test_pacing_inputs_pass_through(self) -> None:
        ctx = default_registry().resolve().validation_context(wpm=120.0, fps=60)
        assert (ctx.wpm, ctx.fps) == (120.0, 60)


@dataclass(frozen=True, slots=True)
class _FakeEntryPoint:
    """Stands in for what an installed distribution advertises."""

    pack: SkillPack

    def load(self) -> SkillPack:
        return self.pack


#: A plausible out-of-tree pack. It claims no object kinds, so nothing here depends
#: on the builtins' partition of ``ObjectKind``.
_THIRD_PARTY = SkillPack(
    id="chemistry",
    version="0.1",
    summary="Molecules, bonds, and reactions.",
    operations=provide(SemanticOp.SIMULATE),
    prompt_fragment="The `chemistry` vocabulary stands in for an installed pack.",
)


def _served(monkeypatch: pytest.MonkeyPatch, *packs: SkillPack) -> list[str]:
    """Serve ``packs`` as if installed. Returns the groups ``discover`` asked for."""
    asked: list[str] = []

    def fake_entry_points(*, group: str) -> tuple[_FakeEntryPoint, ...]:
        asked.append(group)
        return tuple(_FakeEntryPoint(pack) for pack in packs)

    monkeypatch.setattr(registry_module, "entry_points", fake_entry_points)
    return asked


class TestEntryPointDiscovery:
    """The extension path: opt-in, additive, and unable to hijack a builtin."""

    def test_importing_the_package_discovers_nothing(self) -> None:
        # Loading an entry point runs third-party code, so it is a decision for
        # whoever configures the process, never a side effect of an import.
        assert default_registry().ids == frozenset({"core", "networks", "geography", "dataviz"})

    def test_a_discovered_pack_is_added_and_reported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _served(monkeypatch, _THIRD_PARTY)
        registry = default_registry()
        assert registry.discover() == ("chemistry",)
        assert registry.get("chemistry") is _THIRD_PARTY

    def test_a_discovered_pack_composes_like_a_builtin(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _served(monkeypatch, _THIRD_PARTY)
        registry = default_registry()
        registry.discover()
        resolved = registry.resolve(["chemistry"])
        assert resolved.ids == ("core", "chemistry")
        assert SemanticOp.SIMULATE in resolved.registry
        assert "chemistry" in resolved.known_skills

    def test_the_group_queried_is_the_published_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # This string is the contract a pack declares itself under; changing it
        # silently would unload every installed third-party pack at once.
        asked = _served(monkeypatch)
        assert default_registry().discover() == ()
        assert asked == ["manorem.skills"] == [ENTRY_POINT_GROUP]

    def test_discovery_cannot_hijack_a_builtin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _served(monkeypatch, SkillPack(id="core", version="9.9", summary="Not the real core."))
        registry = default_registry()
        with pytest.raises(ValueError, match="already registered"):
            registry.discover()
        assert registry.get("core") is CORE
