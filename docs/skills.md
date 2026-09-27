# Visual Skills

A skill is a **domain vocabulary pack**: the extra object kinds, operations, layout
solvers, constraints and macro expansions that a subject area needs, plus the prose
that teaches a model to use them. The models live in
`packages/skills/src/manorem_skills/`.

## A skill claims vocabulary; it never extends it

`ObjectKind` and `SemanticOp` are closed enums in `manorem_ir`, and they stay
closed. The JSON Schema export enumerates them, CI gates on `schema_digest`, and the
renderer's factory tables are keyed by them. A vocabulary that grew at import time
would make the exported schema a function of *which skills happened to be loaded* —
so a skill **claims and specializes** part of the fixed vocabulary rather than
adding to it.

That is the design, not a limitation worked around. When a planner wants something
the vocabulary cannot express, the answer is a `CMP402` unsupported-intent
diagnostic naming the gap — not a silently invented operation no renderer can run.

## What a skill contributes

```python
class VisualSkill(Protocol):
    id: str
    version: str
    summary: str
    primitives:  Mapping[ObjectKind, PrimitiveDecl]   # object kinds it provides → IR215
    operations:  Mapping[SemanticOp, OperationDecl]    # ops it offers, read by validator + prompt
    constraints: Sequence[SceneConstraint]             # IR209 domain predicates
    layouts:     Mapping[LayoutKind, LayoutSolver]     # solvers called by pass P3
    expansions:  Mapping[SemanticOp, ExpansionRule]    # P2 macros: one cue → primitive steps
    prompt_fragment: str                               # instructions injected into the IR prompt
    examples:    Sequence[Path]                        # few-shot exemplars AND test corpus
```

- **`operations`** is read by the validator, by duration resolution, *and* by the
  IR-generation prompt — so the model's menu and the validator's rules cannot drift
  apart.
- **`layouts`** solvers take a `LayoutRequest` whose `sizes` are already resolved and
  must be pure functions of numbers, so pass P3 stays deterministic and
  snapshot-testable.
- **`expansions`** emit `ExpandedStep`s timed in *fractions of the cue's own window*
  (`[0, 1]`), never seconds — a cue's length may come from a narration segment
  resolved in P1. Offsets are explicit rather than implied by a `lag_ratio`, because
  anything time-addressable has to survive frame quantization.
- **`examples`** are auto-compiled and snapshot-tested, so a skill can't land without
  a passing golden.

## The built-in packs

`SkillRegistry.with_builtins()` loads four: `core` (the base pack, always composed
first), `networks`, `geography`, `dataviz`. Third-party packs advertise themselves
under the `manorem.skills` entry-point group; `discover()` loads them, but only when
called — importing an entry point runs third-party code, a decision for whoever
configures the process, not a side effect of import.

## Resolution is per scene, and honest

`registry.resolve(scene.skills)` composes the requested packs — `core` first, then
as listed — into a `ResolvedSkills` carrying one fresh `OperationRegistry`, the
allowed object kinds, the constraints, the layouts and the expansions. Building it
per scene in a fixed order makes composition deterministic (a test asserts packs
sharing an operation declare it identically, so order can't decide anything), and
composing only the *requested* packs is what gives `IR205` its meaning: an operation
no enabled skill provides is genuinely unknown.

An unrequestable skill id does not raise and is not dropped — it lands in
`ResolvedSkills.unknown` and also fails the `IR210` check with a JSON pointer at the
scene that asked for it. A compile that died on `KeyError` would lose the pointer; one
that silently ignored the id would ship a scene missing the vocabulary it was written
against.

`ResolvedSkills.validation_context()` is the one place `manorem_skills` and
`manorem_ir` meet: `manorem_ir` declares the `ValidationContext` protocol and the
skill layer fills it in, so the dependency runs one way and `manorem_ir` never imports
a skill.
