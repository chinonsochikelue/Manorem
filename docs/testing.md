# Testing

The suite is built around one idea: **the fast gate is a snapshot of a JSON
artifact, not a render.** Because a `RenderPlan` is a deterministic function of
`(IR, CompileOptions)`, compiling an example and diffing it against a committed
golden catches almost every regression in milliseconds. Real renders are a separate,
slow, nightly gate.

## Kinds of test

| Kind | Scope | Speed |
| --- | --- | --- |
| **Unit** | one test per `Diagnostic` code; each layout solver; the scheduler (`TimeExpr` resolution, cycle detection, quantization); each skill expansion; the FFmpeg argv builder; the Gemini schema shim; autofix — the permitted rules *and* a rejection test per forbidden class; `ProvenanceValidator` (an unretrieved URL is rejected; a retrieved-but-unsupported claim **passes**, documenting the deliberate limit) | fast |
| **Snapshot** | `compile(example_ir) → RenderPlan` against committed JSON goldens, **including 16:9 / 9:16 / 1:1 variants of the same IR** to lock the aspect contract | fast — the primary gate |
| **Property** | Hypothesis over generated IR: never a NaN; every mobject inside the safe area; no event past scene end; the scheduler stays topologically consistent; **autofix preserves the object / cue / relationship / narration id sets exactly** | fast |
| **Fixture corpus** | `examples/vqa/<defect>/plan.json` — one committed RenderPlan per Visual QA defect, assessed offline through `assess_plan(plan, build_manifest(plan))`; each asserts its `VQA6xx` code and JSON Pointer (see [Visual QA](vqa.md)) | fast |
| **Golden render** | 2–3 short scenes at 480p15, per-frame perceptual hash with tolerance | `@pytest.mark.slow`, nightly |
| **Integration** | cassette-driven `idea → … → MP4` with `StubRenderer` on every commit; one real-Manim run under the slow marker | mixed |
| **Contract** | generated TS types match the Pydantic JSON Schema (CI fails on drift); a `RenderResult` with `quality=None` is never reported as quality-verified | fast |

## Conventions that are load-bearing, not stylistic

- **`tests/support/ir_builders.valid_scene()` must validate with zero diagnostics at
  every tier.** If a newly added check fires on it, the check is wrong — not the
  fixture. A validator that flags ordinary well-formed IR is worse than useless,
  because the repair loop will burn its bounded attempts rewriting correct IR.
- **Assert on codes and pointers, never message wording.** The message is for humans
  and may be reworded freely; the code and the JSON Pointer are the machine contract
  the repair agent and inspector depend on.
- **A fault produces exactly one finding.** `tests/support/diag.only` fails when a
  check fires twice, because duplicate findings spam the repair loop.
- **Tests state their own tier** (`error_codes` / `warning_codes`), so a semantic
  test is not held hostage by an incidental pacing warning.

## The gates

Each also runs in CI; `make check` runs all three of the last group:

```bash
make fmt         # apply formatting and import sorting
make lint        # ruff format --check + ruff check, no writes
make typecheck   # mypy --strict over packages and tests
make test        # pytest -m "not slow and not network"
make test-slow   # golden renders (real Manim, minutes)
```

Determinism is the through-line: layout solvers with a randomized component take a
fixed seed, artifacts are keyed by the sha256 of their canonical JSON, and re-running
`build` against the same cassettes yields a byte-identical `renderplan.json`.
