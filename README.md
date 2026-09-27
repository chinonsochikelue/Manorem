<p align="center">
  <picture>
    <source
      media="(prefers-color-scheme: dark)"
      srcset="assets/manorem_logo_dark.svg"
    />
    <source
      media="(prefers-color-scheme: light)"
      srcset="assets/manorem_logo.svg"
    />
    <img
      src="assets/manorem_logo_dark.svg"
      alt="Manorem"
      width="250"
      height="216"
    />
  </picture>
</p>


# Manorem

**English** · [Igbo](README.ig.md) · [Español](README.es.md) · [Français](README.fr.md) · [简体中文](README.zh-CN.md)

Turn an idea into a narrated explanatory video — without letting a language model
write animation code.

The pipeline's premise is that an LLM is good at deciding *what a scene should
mean* and bad at deciding *where things go*. So the model never emits Manim code,
never picks a coordinate, and never names a frame number. It emits **Visual IR**:
a strongly typed, validated, versioned document describing objects, relationships,
narration and timed intent. A deterministic compiler turns that into layout,
camera keyframes and render instructions.

Invalid IR never reaches the renderer. That single rule is what most of this
repository exists to enforce.

## Status

Milestone 1 is complete: all eight packages the workspace anticipates are
implemented, and `manorem build` takes an idea to a captioned video offline. What
exists is complete, strictly typed and tested (927 tests, `mypy --strict` clean);
nothing is stubbed out pretending to be more than it is.

| Package | State | Contents |
| --- | --- | --- |
| `manorem-core` | implemented | settings, structured logging, the diagnostic vocabulary, object storage, canonical hashing |
| `manorem-ir` | implemented | the Visual IR: models, JSON Schema export, three-tier validation, symbolic timing resolution |
| `manorem-skills` | implemented | domain vocabulary packs (extra object kinds, operations, constraints) |
| `manorem-compiler` | implemented | IR → `RenderPlan`: normalization, layout solving, timing, camera, autofix |
| `manorem-renderer` | implemented | sandboxed Manim worker (and a stub) producing silent per-scene video |
| `manorem-compositor` | implemented | scene concatenation, transitions, audio timeline, SRT/VTT subtitles |
| `manorem-ai` | implemented | providers (Gemini / recorded cassettes / stub), planning agents, bounded repair |
| `manorem-cli` | implemented | the `manorem` entry point: `build`, `validate`, `compile`, `render`, `schema` |

Honest about the edges: Milestone 1 renders are **not assessed for visual quality**
— `manorem build` reports `quality=None`, never "looks good", and the Visual QA
stage (`VQA6xx`) is designed in but not yet implemented. Provenance validation
proves a cited URL was actually retrieved, **not** that the source supports the
claim. There is no TTS: narration timings are estimated from a words-per-minute
model, so the video is silent-but-timed with synced subtitles. `examples/scratch/scene.py`
is a hand-written Manim file kept for reference, not part of the pipeline.

## The shape of the thing

```
idea ──► story plan ──► visual plan ──► Visual IR ──► validate ──► compile ──► render ──► composite ──► video
                                            ▲            │
                                            └── repair ◄─┘   (bounded, diagnostic-driven)
```

Two properties hold the design together.

**The IR is the source of truth.** It is semantic: a `flow` cue means "show data
moving from A to B", not `MoveAlongPath`. Positions are *intent* (`auto`, a named
slot, anchored to another object), not coordinates. Timing is *symbolic* ("when
the narration about satellites starts"), not seconds. Everything mechanical is
derived downstream, which is why the same IR can be retargeted to 16:9, 9:16 and
1:1 by changing one field.

**Failures are structured, not textual.** Every subsystem emits the same
`Diagnostic` type, addressed by RFC 6901 JSON Pointer, with a namespaced code.
That is what makes the repair loop possible: it consumes codes and pointers, not
prose, and it is bounded — never an open-ended retry.

## Layout

```
packages/
  core/src/manorem_core/         settings, logging, diagnostics, errors, ids, hashing, storage
  ir/src/manorem_ir/             project, scene, objects, props, layout, camera, narration,
                                 timeline, timing, resolve, geometry, format, enums,
                                 operations, validate, schema
  skills/src/manorem_skills/     skill protocol + registry; core, networks, geography, dataviz packs
  compiler/src/manorem_compiler/ passes P0–P8, layout solvers, scheduler, autofix, RenderPlan
  renderer/src/manorem_renderer/ Renderer protocol, Manim plan interpreter, stub renderer, sandbox
  compositor/src/manorem_compositor/ FFmpeg argv builder, scene concat, audio timeline, subtitles
  ai/src/manorem_ai/             LLMProvider, Gemini/cassette/stub, agents, prompts, pipeline, repair
  cli/src/manorem_cli/           the `manorem` command line
tests/
  support/                       IR/AI builders and diagnostic assertions shared by the suite
  unit/                          per-package: core, ir, skills, compiler, renderer, compositor, ai, cli
  integration/                   the hand-authored GPS example, end to end
examples/gps/                    the reference Visual IR: nine scenes, plus a broken-reference fixture
examples/scratch/                raw Manim reference file, excluded from lint
```

No root distribution exists on purpose: every unit of code lives in `packages/*`
so the sandboxed render worker can install the engine without dragging in API or
service dependencies. Relative imports across package boundaries are banned by
lint, so the dependency graph stays acyclic and readable — `manorem_core` knows
nothing about Manim, LLM providers or the IR.

## The Visual IR

A `Project` holds `Episode`s, which hold `Scene`s. The scene is the unit of
authoring, generation, rendering, caching and repair: it is self-contained and
references nothing outside itself, which is what makes per-scene AI generation
viable (structured-output nesting limits rule out whole-project generation) and
repair local — a patch fixing scene 4 cannot disturb scene 7.

Inside a scene:

- **objects** — a closed set of semantic kinds (`text`, `math`, `chart`, `globe`,
  `network`, …), each with a typed props model, so "a chart with no series" is a
  schema error rather than a renderer crash
- **placement** — `auto` (the layout engine decides), `slot`, `anchor` (relative
  to another object), or explicit `stage` coordinates as an escape hatch
- **layout** — declared intent (`grid`, `radial`, `tree`, `split`, …), solved later
- **relationships** — typed edges that feed layout solvers, skill constraints, and
  sometimes geometry (`points_to` becomes an arrow)
- **narration** — segments with roles (`hook`, `revelation`, `payoff`, …); timings
  are derived, never authored
- **timeline** — `Cue`s: one semantic operation, its targets, when it starts, how
  long it lasts, and *why* it exists
- **camera** — an initial pose plus clamps; camera *moves* are ordinary cues, so
  they can be ordered and time-anchored against visuals

Positions live in **stage space**: `[-1, 1]` on both axes, where the unit square is
the safe area visible in every aspect ratio. No world coordinate and no 16:9
constant appears anywhere upstream of the compiler pass that maps stage space to
Manim units.

### Authoring a scene

```python
from manorem_ir import (
    Cue, DotProps, Episode, NarrationSegment, ObjectKind, Project, Scene,
    SceneObject, SemanticOp, TextProps, at_narration, lasting, validate_project,
)

scene = Scene(
    id="intro",
    name="Where am I?",
    intent="Open with the question the video answers.",
    objects=[
        SceneObject(id="title", kind=ObjectKind.TEXT,
                    props=TextProps(content="Where am I?", role="title")),
        SceneObject(id="phone", kind=ObjectKind.DOT, props=DotProps()),
    ],
    narration=[
        NarrationSegment(id="hook", text="Where are you right now?"),
        NarrationSegment(id="answer", text="Your phone knows.", mentions=["phone"]),
    ],
    timeline=[
        Cue(id="show_title", op=SemanticOp.SHOW, targets=["title"],
            at=at_narration("hook"), duration=lasting(1.0)),
        Cue(id="show_phone", op=SemanticOp.SHOW, targets=["phone"],
            at=at_narration("answer"), duration=lasting(1.0)),
        Cue(id="pulse", op=SemanticOp.HIGHLIGHT, targets=["phone"],
            at=at_narration("answer", "end"), duration=lasting(0.8)),
    ],
)

project = Project(id="gps", title="How GPS knows where you are",
                  episodes=[Episode(id="main", title="Main", scenes=[scene])])

assert not validate_project(project).has_errors
project.content_hash()          # '5446673f6e6d...' — identical IR always hashes alike
```

Nothing here says where the title sits, when 1.4 seconds have elapsed, or which
Manim class draws a dot. Every model is frozen, so a compiler pass produces a new
document rather than mutating the one it was given.

### On the wire

The models *are* the schema. `manorem_ir.schema` exports JSON Schema for `Project`
and `Scene`, digests it for drift detection, and is the intended source for the
TypeScript IR types and the structured-output request sent to the model. Two type
systems maintained by hand diverge; one generated from the other cannot.

```json
{
  "id": "pulse",
  "op": "highlight",
  "targets": ["phone"],
  "params": {},
  "at": { "at": "narration", "segment": "answer", "edge": "end", "offset": 0.0 },
  "duration": { "kind": "seconds", "seconds": 0.8 },
  "easing": null,
  "why": null
}
```

Cue parameters are restricted to flat JSON scalars — a structural security
boundary, not a procedural one. A parameter cannot be a nested structure or an
expression, so nothing can smuggle behaviour toward the renderer. A skill that
needs richer configuration declares a new object kind instead.

## Validation

Three tiers, each reporting at the level where a fault is actually detectable:

- **T1 structural** — the shape of the document. Pydantic covers types, ranges and
  discriminators; this tier adds what a schema cannot express: duplicate ids, empty
  scenes, durations that quantize to zero frames at the target rate (the same IR is
  fine at 60fps and degenerate at 15fps).
- **T2 referential / semantic** — whether the document *means* anything. Every
  reference resolves, every operation signature is satisfied, the timeline is
  acyclic, nothing is used before it is shown.
- **T3 pacing and geometry** — well-formed but questionable: dead air, overcrowded
  stage, overlapping or off-stage objects, narration overflowing its scene.
  Warnings by default, promotable to errors by policy.

All three are computed from the IR and the solved plan, never from pixels. They
establish that a plan is *well-formed*, which is a different claim from *looks
good* — perceptual judgement belongs to the Visual QA stage and its `VQA6xx` codes.

A finding names a code, a severity and a pointer into the offending document. Given
the scene above with the `pulse` cue mistyped to target `"phones"`:

```python
>>> for d in validate_scene(broken):
...     print(d)
error: IR201_UNKNOWN_OBJECT_REF [intro] at /timeline/2/targets/0: cue 'pulse' targets unknown object 'phones'
```

Codes are namespaced by the stage that raises them:

| Range | Stage |
| --- | --- |
| `IR1xx` | structural |
| `IR2xx` | referential / semantic |
| `IR3xx` | pacing and geometry lints |
| `CMP4xx` | compile |
| `RND5xx` | render |
| `VQA6xx` | visual quality (reserved) |
| `MUX7xx` | compositing |
| `RES8xx` | research provenance |

Every `IR2xx` code is in `SEMANTIC_ERROR_CODES`, and deterministic autofix is
forbidden from touching that set — it escalates to the bounded repair agent
instead. Silently "fixing" a dangling reference discards authorial intent and hides
a real planner defect behind a plausible-looking render. `Diagnostic.autofixable`
derives from that set rather than being stored, so whoever constructs a diagnostic
cannot relabel a semantic error as harmless.

Timing resolution lives in `manorem_ir.resolve` rather than the compiler because two
consumers need it and must not disagree: the T2/T3 validators and the compiler pass
that quantizes the same numbers to frames. Resolution iterates to a fixpoint rather
than sorting topologically, so a partially broken timeline still yields useful times
for the cues that are well-formed — which keeps diagnostics specific instead of
collapsing into one "the timeline is broken".

## Getting started

Requires Python ≥ 3.13 (the repo pins 3.14) and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --all-packages
```

```bash
make test
```

Configuration is environment-driven with the `MANOREM_` prefix; copy `.env.example`
to `.env` and edit. Defaults are chosen to work offline: the LLM provider defaults
to `cassette` (replays recorded responses, no API key), render quality to `draft`,
and the repair loop to at most 2 attempts.

## Using the CLI

`manorem` is five verbs over one pipeline. `validate` and `compile` operate on a
Visual IR project, `render` on a compiled `RenderPlan`, `schema` exports the JSON
Schema, and `build` runs the whole idea-to-video pipeline offline.

```bash
manorem validate examples/gps/ir.json
manorem compile examples/gps/ir.json --aspect 16:9 -o plan.json
manorem render plan.json --quality draft -o gps.mp4
manorem build "How GPS determines your location." --aspect 16:9 -o out/
```

`build` writes every intermediate artifact — `brief.json`, `outline.json`,
`script.json`, `plan/plan_*.json`, `ir.json`, `renderplan.json` — beside the final
`gps.mp4` and its `.srt` / `.vtt` sidecars, so each stage is inspectable and
content-addressed. `render` accepts `--engine stub` for solid-colour frames when
you want the pipeline exercised without invoking Manim.

A semantically broken IR fails loudly and renders nothing — the guardrail the whole
design turns on:

```bash
manorem validate examples/gps/ir_broken_ref.json   # exits 1 with an IR2xx error, no video
```

## Development

`make` with no target lists everything. Each of these also runs in CI:

| Target | What it does |
| --- | --- |
| `make install` | sync all workspace packages and dev dependencies |
| `make fmt` | apply formatting and import sorting |
| `make lint` | check formatting and lint rules, no writes |
| `make typecheck` | `mypy --strict` over packages and tests |
| `make test` | fast tests — excludes real renders and anything needing a live API key |
| `make test-slow` | golden render tests (real Manim, minutes) |
| `make check` | lint + typecheck + test |

Test conventions that are load-bearing rather than stylistic:

- **`tests/support/ir_builders.valid_scene()` must validate with zero diagnostics at
  every tier.** If a newly added check fires on it, the check is wrong — not the
  fixture. A validator that flags ordinary well-formed IR is worse than useless,
  because the repair loop will burn its bounded attempts rewriting correct IR.
- **Assert on codes and pointers, never message wording.** The message is for
  humans and may be reworded freely; the code and the JSON Pointer are the machine
  contract the repair agent and inspector depend on.
- **A fault produces exactly one finding.** `tests/support/diag.only` fails when a
  check fires twice, because duplicate findings spam the repair loop.
- Tests state their own tier exactly (`error_codes` / `warning_codes`) so a semantic
  test is not held hostage by an incidental pacing warning.

## Design rules

Most of the non-obvious choices in this repository follow from a handful of
positions:

- **Closed vocabularies.** Object kinds, operations, layouts and easings are all
  enums. The model picks from a menu the compiler is guaranteed to understand;
  widening the menu is a deliberate act — add the member, add its compiler handling,
  add its test.
- **Table-driven validation.** Operations declare their signatures
  (`CORE_OPERATIONS`), so adding one means adding a declaration, not another branch.
  The generation prompt is built from the same declarations, so the model's menu and
  the validator's rules cannot drift apart.
- **Content addressing everywhere.** Artifacts are keyed by the sha256 of their
  canonical JSON, which buys deduplication, cheap versioning and byte-exact
  determinism checks. Layout solvers with a randomized component take a fixed seed
  for the same reason.
- **Reject, don't sanitize.** Malformed storage keys and invalid ids raise instead of
  being quietly rewritten — a caller producing one has a bug, and repairing it
  silently hides that bug. `slugify` exists for machine-generated names only.
- **Persisted schemas get a version.** `Project.ir_version` means older stored IR is
  recognized and migrated rather than mis-parsed.
