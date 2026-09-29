# Visual QA (VQA6xx)

Compiling and rendering answer *"is this plan well-formed, and did the render
finish?"* They do not answer *"does the finished frame actually read?"* Visual QA
is the stage that does. It runs **after** a successful render, measures concrete
geometric properties of the frame, and emits `VQA6xx` diagnostics that point at the
Visual IR the repair loop can patch.

> Visual QA measures **measurable visual constraints** — text off the stage, two
> objects colliding, copy below a legibility floor, a camera pointed at nothing. It
> does **not** score artistic quality, and there is deliberately no overall "visual
> quality score." A clean VQA report means *no measured defect*, not *good video*.

## Where it sits

```
IR ──validate──▶ compile ──▶ render ──▶ VQA ──▶ composite
                                          │
                        error-severity VQA6xx findings
                                          ▼
                          bounded repair (patch the IR) ──▶ recompile ──▶ rerender ──▶ VQA
```

VQA is a pure, offline, deterministic function of the render plan's geometry. It
decodes no pixels, calls no model, and touches no network — the render manifest the
compiler's P6 pass implies already carries resolved world bounds, a camera track,
and per-frame visibility, so `assess_plan(plan, build_manifest(plan))` is all a full
assessment needs. Because the manifest is a function of the plan alone, the stub and
Manim backends produce identical VQA reports for the same plan.

## The VQA6xx vocabulary

| Code | Severity | What it measures |
| --- | --- | --- |
| `VQA601_TEXT_OVERFLOW` | error | a text/math mobject extends past the framed stage; glyphs would clip |
| `VQA602_OBJECT_OFF_STAGE` | error | a mobject is entirely outside the viewport (or pokes in as stray sub-pixel geometry) and is never seen |
| `VQA603_OBJECT_OVERLAP` | error | two visible, ungrouped, same-`z` mobjects overlap without being layered on purpose |
| `VQA604_TINY_TEXT` | error | rendered text height is below the legibility floor |
| `VQA605_EMPTY_FRAME` | error | a scene's visible mobjects cover less than the minimum scene area — it draws almost nothing |
| `VQA606_BAD_CONTRAST` | error | text foreground vs. the declared scene background is below the WCAG contrast floor |
| `VQA607_CUT_OFF_OBJECT` | error | a mobject with real extent straddles a frame edge and renders cut off |
| `VQA608_EXCESSIVE_DENSITY` | **warning** | too many mobjects, or too much ink coverage, on one frame |
| `VQA609_CAMERA_COMPOSITION` | **warning** | the camera centres on empty space — no visible subject falls under the frame centre |

`VQA_ERROR_CODES` is exactly `VQA601`–`VQA607`: the error-severity codes the repair
loop routes on. `VQA608`/`VQA609` are **warnings** — a note, never a build failure —
because density and composition are subjective enough that a hard failure would be
wrong more often than right. They are reported and logged, and never repaired.

Findings use the shared `Diagnostic` type. Each carries a JSON Pointer into the plan
(`/scenes/<scene_id>/mobjects/<object_id>` for a mobject defect, `/scenes/<scene_id>`
for a scene-level one), `scene_id`, and — for object defects — `object_id`. A
synthetic child's defect (a travelling packet, a highlight ring) is attributed to the
**authored owner** that groups it, because that is the id the repair loop can patch.

## Thresholds

Every check bounds a measurable quantity, and the bounds live in `VQAConfig`
(frozen, in `manorem_renderer.vqa`): `min_text_height`, `max_objects_per_frame`,
`max_ink_per_frame`, `min_scene_area`, `off_stage_min_extent`, `overlap_tolerance`,
`min_contrast_ratio`. Defaults keep M2 honest rather than generous — a scene that is
merely "probably fine" still surfaces. A project may tighten or relax them by passing
a `VQAConfig` to `GeometricVisualQA`/`assess_plan` without changing any check.

## Aspect awareness

Off-stage, overflow and cut-off are judged against **what the camera frames at each
sampled frame**, not a fixed default frame. A zoomed-in or displaced camera
legitimately narrows the stage, and an object outside that narrowed view is genuinely
off screen. The same plan assessed at 16:9, 9:16 and 1:1 uses each aspect's own
viewport, so the checks hold across all three.

## Using it from the CLI

Assess a compiled RenderPlan directly — deterministic and offline:

```bash
uv run manorem vqa renderplan.json
```

It builds the manifest from the plan, runs the geometric checks, and prints findings
through the same reporter every other verb uses. **Error-severity `VQA6xx` findings
set a non-zero exit; warnings are reported but do not fail.** `--sample-rate` overrides
the keyframe sampling rate (defaults to `MANOREM_FRAME_SAMPLE_HZ`).

`render` stays QA-free by design: it promises a rendered MP4 and nothing more. To
assess a render, run `vqa` on its plan, or opt into QA during a full build:

```bash
uv run manorem build "How GPS determines your location." --aspect 16:9 --vqa -o out/
```

`--vqa` (or `MANOREM_VQA_ENABLED=1`) wires `GeometricVisualQA` into the pipeline.
Without it, `build` reports `visual quality: not assessed` — never conflated with
"assessed and fine". With it, the pipeline assesses each render, routes error-severity
findings to bounded repair, and fails loudly if a defect survives the repair cap.

## Repair behaviour and the safety property

Error-severity VQA findings feed the **same bounded repair loop** as semantic errors
(`_render_qa_repair` in the pipeline). Findings are grouped by scene, and each scene is
patched through `RepairAgent` + `apply_scene_patch`, which rejects any patch that adds
or drops an object, cue, relationship, or narration segment. Repair targets the
**Visual IR only** — never Manim, the renderer, the compiler, or the pixels — then
recompiles, rerenders, and reassesses. It is capped at `MANOREM_MAX_REPAIR_ATTEMPTS`
and stops early when a round patches nothing.

**A VQA repair may never make a finding disappear by weakening a check or a
threshold.** The only legitimate fix is to change the IR (reposition, resize,
re-colour, re-layout) so the render genuinely no longer exhibits the defect. A quietly
relaxed threshold would trade a loud, honest failure for a silently bad video — the
exact outcome this whole design exists to prevent.

## Limitations

The manifest carries resolved world geometry, not decoded pixels, so VQA cannot see
what the geometry does not encode: exact rendered glyph shapes, true pixel coverage,
or local background luminance behind a specific mobject. `VQA606_BAD_CONTRAST`
therefore scores against the **declared** scene background for the text kinds where the
compiler knows the foreground colour — a stated limitation, not a hidden one. A
mobject's bounds are its resolved box, not its box mid-`move_to`; a check that needs
swept bounds would integrate the track itself. Perceptual checks over sampled frames
(composition mass, thirds, narration/visual entity mismatch) are designed for but not
implemented in M2.

## Tests

- `tests/unit/renderer/test_vqa.py` — one test per `VQA6xx` code over hand-built
  geometry, plus dedupe, owner attribution, the 601–607 partition, and the
  `GeometricVisualQA` seam.
- `examples/vqa/<defect>/plan.json` — a committed corpus, one RenderPlan per defect
  (`good`, `overflow`, `off-stage`, `overlap`, `tiny-text`, `empty-frame`, `contrast`,
  `cut-off`, `density`, `camera`). RenderPlan JSON, not IR, because the compiler
  safe-area-clamps geometry — a defect is authored at the layer the checks read.
  Regenerate with `uv run python examples/vqa/build_fixtures.py`.
- `tests/unit/renderer/test_vqa_examples.py` — loads the corpus and asserts each
  fixture's code and JSON Pointer (never message wording).
- `tests/unit/ai/test_pipeline_visual_repair.py` — the bounded post-render repair loop:
  clears after one patch, respects the cap, stops on a rejected patch.
