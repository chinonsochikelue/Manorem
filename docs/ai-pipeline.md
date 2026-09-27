# The AI Pipeline

`manorem-ai` turns an idea into a validated project and, from there, a video. Every
stage is a total function from one typed, frozen artifact to the next, and each
artifact is persisted **content-addressed by the sha256 of its canonical JSON** — so
a later edit re-runs only the stages whose inputs actually changed.

```
idea ─► research ─► story ─► script ─► pacing ─► visual plan ─► scene (IR)
     ─► assemble project ─► compile (+ repair) ─► render ─► visual-QA seam ─► composite
```

## The provider seam

```python
class LLMProvider(Protocol):
    name: str
    def structured[T: BaseModel](self, *, prompt: Prompt, schema: type[T],
                                 model: str, temperature: float, max_tokens: int) -> Completion[T]: ...
```

One protocol sits between the agents and whatever produces JSON. An agent names a
Pydantic `schema` and gets back a parsed, validated instance or a `ProviderError` —
it never sees raw text, a model id, or an SDK. The seam is deliberately narrow:
**structured output only**, no free-text method, because nothing in the pipeline
wants prose it would then have to parse.

It is **synchronous by design in M1**: one scene at a time in one process, so there
is no concurrency for `async` to buy. Per-scene fan-out is a job-queue concern
(Slice 4, `arq`), and that is the layer where an event loop belongs.

`Completion[T]` carries the parsed `value` plus the trace metadata every call needs —
`model`, `usage` (tokens / cost), `latency_ms`, and the backend's own `raw_id` — so
tracing is free.

Three backends implement it:

- **`GeminiProvider`** — `client.interactions.create(model=…, input=…,
  response_format={"type": "text", "mime_type": "application/json", "schema":
  to_gemini_schema(schema)})`, then `schema.model_validate_json(interaction.output_text)`.
- **`schema_shim`** (`to_gemini_schema`) down-converts a Pydantic JSON Schema to
  Gemini's supported subset, with a round-trip fidelity test. Required: the docs warn
  that deeply nested schemas may be rejected and only syntactic validity is
  guaranteed — which is why IR is generated **per scene**, never whole-project.
- **`CassetteProvider`** — record / replay keyed on `prompt_cache_key(prompt, schema,
  model)`. Changing a field of the schema misses the old recording instead of
  replaying a stale answer. Tests are deterministic and offline;
  `MANOREM_AI_RECORD=1` refreshes.
- **`StubProvider`** — hand-written fixtures for CI without cassettes.

## The agents

Each agent has one input type and one output type (`agents/models.py`), so the
pipeline reads as a chain rather than a bag of dicts.

| Agent | In → Out |
| --- | --- |
| `ResearchAgent` | idea + documents → `ResearchBrief` (claims, entities, visual candidates, open questions) |
| `StoryAgent` | brief → `StoryOutline` — `arc` and `rationale` required, so no run silently defaults every subject to one template |
| `ScriptAgent` | outline → `Script` — narration segments only; timings come from deterministic `pacing.py`, never the model |
| `VisualPlannerAgent` | beat + segment + skill menu → `VisualPlan` |
| `IRGeneratorAgent` | plan + segment + scoped vocabulary → **one `Scene`** |
| `RepairAgent` | scene + its semantic diagnostics → a **JSON Patch** (never a rewrite) |

`VisualPlan` makes *what / why / when / how / focus* required fields: a plan that
skipped its reasoning does not validate. Refusing the response is the surest way to
make a model plan rather than free-associate.

## Provenance — and precisely what it does not prove

Everything a research model fills in is *model-asserted*: `Claim.kind` and
`Claim.confidence` are the model's own estimate, not a verified property, and the
field docs say so.

`ProvenanceValidator` enforces the one guarantee this layer can make: **every cited
URL was genuinely retrieved.** It rejects a `SourceRef` whose URL is not in the
retrieved document set (`RES801`), which makes a fabricated citation structurally
impossible. It deliberately does **not** check that the source supports the claim — a
real URL cited for something it never says passes, and that is the documented limit.
Claim-to-evidence verification is a future research-layer capability; nothing here
implies it exists. M1 ships `FixtureResearchProvider` (the GPS corpus) plus the
protocol; a live search backend is a later adapter.

## Compile with bounded repair

`_compile_with_repair` compiles, and while errors remain, patches and recompiles up
to `max_repair_attempts` times. Only diagnostics in `SEMANTIC_ERROR_CODES` reach the
repair agent — a non-semantic compiler fault is not something a scene patch can fix,
so the loop stops and the caller raises. Diagnostics are grouped by `scene_id`, so
each scene is repaired against its own errors and its own vocabulary. Every patch
goes through `apply_scene_patch`, which **rejects any patch that adds or drops an
entity**; a rejected scene is left untouched (it stays an error) rather than forced.
The loop also stops early if an attempt changes nothing.

If semantic errors survive the loop, the pipeline raises `PipelineError` rather than
rendering a plan that dropped a satellite. That is the guardrail the whole design
turns on, enforced by structure.

## The Visual QA seam

"Render succeeded" and "render looks good" are separate outcomes, and the types keep
them apart: `RenderResult` carries `status` (did it run) and `quality` (a
`QualityReport`, or `None` for *not assessed*).

```python
class VisualQA(Protocol):
    name: str
    def assess(self, plan: RenderPlan, result: RenderResult) -> QualityReport | None: ...
```

M1 ships the protocol and `NoopVisualQA` only. It returns `None` — explicitly *not
assessed*, never an empty passing report — so nothing downstream can mistake an
unchecked render for a verified one. The real checks (overlap, unreadable text,
density, composition, framing, hierarchy, narration/visual mismatch, continuity) are
`VQA6xx` diagnostics computable from the `scene_manifest` and `frame_samples` the
renderer already emits on every render; they drop in behind this seam without
touching the pipeline's shape, and their findings route back to IR
repair/regeneration, never to pixel patching.
