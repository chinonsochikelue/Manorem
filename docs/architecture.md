# Architecture

`manorem` turns an idea into a narrated, captioned explainer video without ever
letting a language model write animation code. The premise: an LLM is good at
deciding *what a scene should mean* and bad at deciding *where things go*. So the
model emits **Visual IR** — a strongly typed, validated, versioned document — and a
deterministic compiler turns that into concrete render instructions.

```
idea ─► research ─► story ─► script ─► visual plan ─► Visual IR ─► validate ─► compile ─► render ─► composite ─► video
                                                          ▲            │
                                                          └── repair ◄─┘   (bounded, diagnostic-driven)
```

## Two layers, one rule

The whole design turns on one rule: **invalid IR never reaches the renderer.**

| Layer | Who writes it | Contains | Never contains |
| --- | --- | --- | --- |
| **Visual IR** (authoring) | AI or a human editor | semantic object kinds, semantic ops, layout *intent*, *relative* timing, narration links | coordinates, absolute times, aspect assumptions, Manim concepts |
| **RenderPlan** (lowered) | the compiler only | absolute stage→world coordinates, frame-quantized times, concrete primitive + animation ops, camera keyframes | anything symbolic, any expression, any code |

Because the RenderPlan is machine-generated from validated IR, the renderer's input
is never model output. And because a `RenderPlan` is a hashable JSON artifact, the
primary regression gate is a fast snapshot test, not a slow render.

## The packages

Every unit of code lives in `packages/*` so the sandboxed render worker can install
the engine without dragging in API or service dependencies. Relative imports across
package boundaries are banned by lint, so the dependency graph stays acyclic.

| Package | Responsibility |
| --- | --- |
| `manorem-core` | settings, structured logging, the `Diagnostic` vocabulary, object storage, canonical JSON + sha256 |
| `manorem-ir` | the Visual IR: Pydantic models, three-tier validation, JSON Schema export, symbolic timing resolution |
| `manorem-skills` | domain vocabulary packs: extra object kinds, operations, layout solvers, constraints, prompt fragments |
| `manorem-compiler` | passes P0–P8: normalize, resolve, expand, layout, schedule, camera, frame, lower, verify |
| `manorem-renderer` | the `Renderer` protocol, the fixed Manim plan interpreter, a stub renderer, subprocess sandbox |
| `manorem-compositor` | FFmpeg argv builder, scene concatenation, audio timeline, SRT/VTT subtitles |
| `manorem-ai` | `LLMProvider` (Gemini / cassette / stub), the planning agents, the content-addressed pipeline, bounded repair |
| `manorem-cli` | the `manorem` command line and the integration-test entry point |

## Security boundary, expressed structurally

Treat all AI-generated content as untrusted input. The renderer never executes
model-authored Python: the only executable code on the render path is one fixed
interpreter over two lookup tables (object factories, animation factories). A
`RenderPlan`'s animation args are numbers, enum strings and validated paths only —
never expressions or code. This is the security boundary written into the types
rather than enforced by policy. Renders run in a subprocess with a timeout so a
runaway or crashing render is contained.

## What Milestone 1 does *not* claim

- **Render succeeded ≠ visual quality succeeded.** M1 renders are not assessed for
  visual quality; `RenderResult.quality` is `None` (not "assumed good"). The Visual
  QA stage (`VQA6xx`) is designed into the pipeline but not implemented.
- **Provenance ≠ correctness.** Provenance validation proves a cited URL was
  actually retrieved; it does not prove the source supports the claim.
- **No TTS.** Narration timings are estimated from a words-per-minute model, so the
  video is silent-but-timed with synced subtitles. The retime seam is in place.

See [visual-ir.md](visual-ir.md), [compiler.md](compiler.md), [skills.md](skills.md),
[ai-pipeline.md](ai-pipeline.md), [testing.md](testing.md), and [env.md](env.md).
