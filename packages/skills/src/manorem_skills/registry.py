"""The registry, and what resolving a scene's ``skills`` list produces.

Two objects. :class:`SkillRegistry` is the catalogue of packs a process can load.
:class:`ResolvedSkills` is what one scene's request composes to -- and its shape is
not invented here: :class:`~manorem_ir.ValidationContext` already asks for exactly
four things a skill layer must supply (an operation registry, the known skill ids,
the allowed object kinds, the constraints), so resolution's job is to produce them
rather than to define a parallel vocabulary.

Two decisions worth stating.

**Composition is per scene, and ``core`` goes first.** ``OperationRegistry.register``
is last-write-wins, so two packs specializing one operation would otherwise fight
invisibly. Building a fresh registry per scene from the listed packs in a fixed
order makes the outcome deterministic, and a test asserts that packs sharing an
operation declare it identically -- so the order cannot decide anything in practice
either. Composing only the *requested* packs is also what gives ``IR205`` its
meaning: an operation no enabled skill provides is unknown, not merely unusual.

**Resolution is total and honest.** An unrequestable skill id does not raise and is
not dropped: it lands in :attr:`ResolvedSkills.unknown`, and the same id also fails
the ``IR210`` check with a JSON pointer at the scene that asked for it. A compile
that died on ``KeyError`` would lose the pointer, and one that quietly ignored the
id would ship a scene missing the vocabulary it was written against.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from importlib.metadata import entry_points

from manorem_ir import (
    DEFAULT_WPM,
    LayoutKind,
    ObjectKind,
    OperationDecl,
    OperationRegistry,
    SceneConstraint,
    SemanticOp,
    ValidationContext,
    ValidationPolicy,
)
from manorem_skills.packs import BASE_PACK, BUILTIN_PACKS
from manorem_skills.protocol import ExpansionRule, LayoutSolver, PrimitiveDecl, VisualSkill

__all__ = ["ENTRY_POINT_GROUP", "ResolvedSkills", "SkillRegistry", "default_registry"]

#: Entry-point group third-party packs advertise themselves under.
ENTRY_POINT_GROUP = "manorem.skills"


@dataclass(frozen=True, slots=True)
class ResolvedSkills:
    """The composed vocabulary for one scene."""

    #: Packs in composition order: the base pack first, then as requested.
    skills: tuple[VisualSkill, ...]
    #: Requested ids no pack answers for. Reported, never silently dropped.
    unknown: tuple[str, ...]
    #: Only the enabled packs' operations, so ``IR205`` means what it says.
    registry: OperationRegistry
    allowed_kinds: frozenset[ObjectKind]
    constraints: tuple[SceneConstraint, ...]
    layouts: Mapping[LayoutKind, LayoutSolver]
    expansions: Mapping[SemanticOp, ExpansionRule]
    #: Every id the *registry* knows, not just the resolved ones -- this is what
    #: turns a typo'd skill name into an IR210 naming the alternatives.
    known_skills: frozenset[str]
    primitives: Mapping[ObjectKind, PrimitiveDecl] = field(default_factory=dict)

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(skill.id for skill in self.skills)

    @property
    def operations(self) -> Mapping[SemanticOp, OperationDecl]:
        return {op: self.registry.require(op) for op in sorted(self.registry.known_ops())}

    def validation_context(
        self,
        *,
        policy: ValidationPolicy | None = None,
        wpm: float = DEFAULT_WPM,
        fps: int = 30,
    ) -> ValidationContext:
        """Hand the composed vocabulary to the T2/T3 validator.

        The one place the two packages meet: ``manorem_ir`` declares the protocol and
        this fills it in, so the dependency runs one way and ``manorem_ir`` never
        imports a skill.
        """
        return ValidationContext(
            registry=self.registry,
            policy=policy if policy is not None else ValidationPolicy(),
            known_skills=self.known_skills,
            allowed_kinds=self.allowed_kinds,
            constraints=self.constraints,
            wpm=wpm,
            fps=fps,
        )


class SkillRegistry:
    """The packs a process can load, and how a scene's request composes them."""

    def __init__(self, skills: Iterable[VisualSkill] = ()) -> None:
        self._by_id: dict[str, VisualSkill] = {}
        for skill in skills:
            self.register(skill)

    @classmethod
    def with_builtins(cls) -> SkillRegistry:
        return cls(BUILTIN_PACKS)

    def register(self, skill: VisualSkill) -> None:
        """Add a pack. Rejects a duplicate id rather than overwriting.

        Silent replacement is the failure this prevents: two packs claiming ``core``
        would give every scene whichever one imported last, and nothing would say so.
        """
        if skill.id in self._by_id:
            raise ValueError(f"skill id {skill.id!r} is already registered")
        self._by_id[skill.id] = skill

    def discover(self, group: str = ENTRY_POINT_GROUP) -> tuple[str, ...]:
        """Load packs advertised by installed distributions. Returns the ids added.

        Not called automatically, and deliberately: importing an entry point runs
        third-party code, which is a decision for whoever configures the process
        rather than a side effect of importing this module.
        """
        added: list[str] = []
        for entry in entry_points(group=group):
            skill: VisualSkill = entry.load()
            self.register(skill)
            added.append(skill.id)
        return tuple(added)

    def get(self, skill_id: str) -> VisualSkill:
        try:
            return self._by_id[skill_id]
        except KeyError:
            known = ", ".join(sorted(self._by_id)) or "none"
            raise KeyError(f"unknown skill {skill_id!r}; registered: {known}") from None

    @property
    def ids(self) -> frozenset[str]:
        return frozenset(self._by_id)

    def __contains__(self, skill_id: object) -> bool:
        return skill_id in self._by_id

    def __iter__(self) -> Iterator[VisualSkill]:
        return iter(self._by_id.values())

    def __len__(self) -> int:
        return len(self._by_id)

    def resolve(self, requested: Sequence[str] = ()) -> ResolvedSkills:
        """Compose the requested packs, base pack first, into one vocabulary.

        Each id is considered once, whether or not a pack answers for it: a scene
        listing ``networks`` twice resolves to one pack, and one listing a typo twice
        reports it once. Per-occurrence reporting is ``IR210``'s job, which has the
        JSON pointer to say *which* entry was wrong.
        """
        chosen: list[VisualSkill] = []
        unknown: list[str] = []
        seen: set[str] = set()

        base = self._by_id.get(BASE_PACK.id, BASE_PACK)
        chosen.append(base)
        seen.add(base.id)

        for skill_id in requested:
            if skill_id in seen:
                continue
            seen.add(skill_id)
            skill = self._by_id.get(skill_id)
            if skill is None:
                unknown.append(skill_id)
                continue
            chosen.append(skill)

        registry = OperationRegistry(())
        primitives: dict[ObjectKind, PrimitiveDecl] = {}
        constraints: list[SceneConstraint] = []
        layouts: dict[LayoutKind, LayoutSolver] = {}
        expansions: dict[SemanticOp, ExpansionRule] = {}
        for skill in chosen:
            for decl in skill.operations.values():
                registry.register(decl)
            primitives.update(skill.primitives)
            constraints.extend(skill.constraints)
            layouts.update(skill.layouts)
            expansions.update(skill.expansions)

        return ResolvedSkills(
            skills=tuple(chosen),
            unknown=tuple(unknown),
            registry=registry,
            allowed_kinds=frozenset(primitives),
            constraints=tuple(constraints),
            layouts=layouts,
            expansions=expansions,
            known_skills=self.ids | {base.id},
            primitives=primitives,
        )


def default_registry() -> SkillRegistry:
    """A registry holding the built-in packs and nothing else.

    A function rather than a module constant: a registry is mutable, and a shared
    one would let a test that registers a pack change what a later test resolves.
    """
    return SkillRegistry.with_builtins()
