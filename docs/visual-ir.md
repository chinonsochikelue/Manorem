# The Visual IR

The Visual IR is the source of truth. It is *semantic*: a `flow` cue means "show
data moving from A to B", not `MoveAlongPath`; positions are *intent*, not
coordinates; timing is *symbolic*, not seconds. Everything mechanical is derived
downstream, which is why the same IR retargets to 16:9, 9:16 and 1:1 by changing one
field. The models live in `packages/ir/src/manorem_ir/` and *are* the schema.

## Shape

```
Project(ir_version, id, title, idea, style, format, episodes[])
 └ Episode(id, title, scenes[], audio?)
    └ Scene(id, name, intent, objects[], groups[], relationships[],
            layout, camera, narration[], timeline[])
```

The **scene** is the unit of authoring, generation, rendering, caching and repair.
It references nothing outside itself, which is what makes per-scene AI generation
viable (structured-output nesting limits rule out whole-project generation) and
repair local — a patch fixing scene 4 cannot disturb scene 7.

## Inside a scene

- **objects** — a closed set of semantic kinds (`text`, `math`, `circle`, `chart`,
  `globe`, `network`, …), each with a typed props model chosen by a `kind`
  discriminator. "A chart with no series" is a schema error, not a renderer crash.
- **placement** — `auto` (the layout engine decides), a named `slot`, `anchor`
  (relative to another object), or explicit `stage` coordinates as an escape hatch.
- **relationships** — typed edges (`connected_to`, `points_to`, `contains`, …) that
  feed layout solvers and skill constraints, and sometimes materialize geometry.
- **narration** — segments with roles (`hook`, `revelation`, `payoff`, …); timings
  are derived, never authored.
- **timeline** — `Cue`s: one semantic operation, its targets, when it starts, how
  long it lasts, and optionally *why*.
- **camera** — an initial pose plus clamps; camera *moves* are ordinary cues, so
  they can be ordered and time-anchored against visuals.

## Stage space

Positions live in **stage space**: `[-1, 1]` on both axes, where the unit square is
the safe area visible in every aspect ratio. No world coordinate and no 16:9
constant appears anywhere upstream of the compiler pass that maps stage space to
Manim units.

## Symbolic timing

A cue's `at` and `duration` are expressions, not numbers:

```
TimeExpr     = Absolute(t) | After(cue, gap) | With(cue, offset) | Narration(segment, edge, offset)
DurationExpr = Seconds(v) | Narration(segment) | Auto
```

Resolution lives in `manorem_ir.resolve` rather than the compiler because two
consumers need it and must not disagree: the T2/T3 validators and the compiler pass
that quantizes the same numbers to frames. Resolution iterates to a fixpoint rather
than sorting topologically, so a partially broken timeline still yields useful times
for the well-formed cues — which keeps diagnostics specific.

## Table-driven operations

Semantic operations (`show`, `hide`, `connect`, `flow`, `highlight`, `focus`,
`zoom_to`, …) are each registered with an `OperationDecl` (allowed target kinds,
required params, default duration) in `CORE_OPERATIONS`. Validation is therefore
table-driven, not a hand-written branch per op, and the IR-generation prompt is
built from the same declarations — so the model's menu and the validator's rules
cannot drift apart.

## Validation — three tiers

- **T1 structural** — the shape of the document: types, ranges, discriminators, plus
  what a schema cannot express (duplicate ids, empty scenes, durations that quantize
  to zero frames at the target rate).
- **T2 referential / semantic** — whether the document *means* anything: every
  reference resolves, every operation signature is satisfied, the timeline is
  acyclic, nothing is used before it is shown.
- **T3 pacing and geometry** — well-formed but questionable: dead air, an
  overcrowded stage, overlapping or off-stage objects, narration overflowing its
  scene. Warnings by default, promotable to errors by policy.

All three are computed from the IR and the solved plan, never from pixels. A finding
names a `code`, a `severity` and an RFC 6901 JSON Pointer into the offending
document. Every `IR2xx` code is in `SEMANTIC_ERROR_CODES`, and deterministic autofix
is forbidden from touching that set — it escalates to the bounded repair agent
instead.

## On the wire

`manorem_ir.schema` exports JSON Schema for `Project` and `Scene`, and `manorem
schema` prints it. It is the intended source for the TypeScript IR types and for the
structured-output request sent to the model. Cue parameters are restricted to flat
JSON scalars — a structural security boundary: a parameter cannot be a nested
structure or an expression, so nothing can smuggle behaviour toward the renderer.
