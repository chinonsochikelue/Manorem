# The Compiler

`manorem-compiler` lowers a validated Visual IR `Project` to a `RenderPlan`. It is a
pure function of `(IR, CompileOptions)`, which makes its output deterministic and
snapshot-testable — the same IR always compiles to byte-identical JSON.

```python
from manorem_compiler import CompileOptions, compile_project
from manorem_ir.enums import Aspect

plan, diagnostics = compile_project(project, CompileOptions(aspect=Aspect.WIDESCREEN))
```

## The passes

Each pass is `run(ctx: CompileContext) -> None`, accumulating diagnostics into the
context. The driver runs them in order and halts at the first stage after which the
context holds an error, so a broken IR never lowers.

| Pass | Responsibility |
| --- | --- |
| **P0 Normalize** | apply style tokens and skill defaults, canonicalize ids |
| **P1 Resolve** | build the symbol table (objects / groups / cues / narration), resolve references, build the timeline DAG |
| **P2 Expand** | skill macro expansion: a semantic op becomes an explicit list of primitive ops with per-child offsets |
| **P3 Layout** | solve stage positions per the scene's `LayoutSpec` |
| **P4 Schedule** | resolve `TimeExpr` / `DurationExpr` to absolute times, detect conflicts, quantize to `1/fps` |
| **P5 Camera** | turn semantic camera requests into frame center / width keyframes from resolved bounds |
| **P6 Frame** | map stage space to Manim world units for the target aspect; clamp to the safe area; size text by role |
| **P7 Lower** | emit the `RenderPlan`: tracks of frame-quantized primitive ops with concrete numeric args |
| **P8 Verify** | plan invariants: no NaN, every op in the allowlist, durations > 0, bounds inside the frame |

Scenes are compiled independently, one workspace each, with the skill vocabulary
resolved once up front so validation and the passes see the same answer.

## Autofix is mechanically safe only

`autofix.py` runs before any LLM, but its mandate is deliberately narrow.

**Permitted:** normalization and canonicalization (id casing, style-token defaults,
enum aliasing), harmless duration padding (clamp a non-positive `run_time` to one
frame, extend a scene to fit its narration), formatting, frame-quantization
rounding.

**Forbidden — these stay errors and go to the bounded repair agent:** unknown object
references, missing required objects, invalid or unsatisfiable semantic
relationships, cues whose targets don't exist, ops whose signature isn't satisfied.

Silently dropping a dangling cue or synthesizing a missing `show` would discard
authorial intent *and* hide a real planner defect behind a plausible render. The
guarantee is enforced by invariant rather than convention: **autofix must not change
the set of object / cue / relationship / narration-segment ids**, and a property
test asserts exactly that over the whole example corpus.

## The RenderPlan

```
RenderPlan(plan_version, project_id, format{w,h,fps,aspect}, style, scenes[ScenePlan])
ScenePlan(id, duration_frames, background, mobjects[MobjectSpec], tracks[Track], camera, audio_cues[])
MobjectSpec(id, primitive, args{numbers | enums | validated paths ONLY}, position, z_index, initial_visible)
Track(target_id, events[PlanEvent])
PlanEvent(start_frame, duration_frames, anim: PlanAnim, easing: rate_fn_name)
```

`args` and every `PlanAnim` field are numbers, enum strings and validated paths
only — never expressions or code. That is the security boundary expressed
structurally: nothing symbolic survives lowering, so nothing executable can reach
the renderer. Timing is resolved and quantized before P6 ever touches pixels, which
is why the same IR produces the same number of frames in every aspect.
