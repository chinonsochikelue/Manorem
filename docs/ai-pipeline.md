# The AI Pipeline

`manorem-ai` turns an idea into a validated project and, from there, a video. Every
stage is a total function from one typed, frozen artifact to the next, and each
artifact is persisted **content-addressed by the sha256 of its canonical JSON** — so
a later edit re-runs only the stages whose inputs actually changed.

```
idea ─► research ─► evidence ─► story ─► script ─► pacing ─► visual plan ─► scene (IR)
     ─► assemble project ─► compile (+ repair) ─► render ─► visual-QA seam ─► composite
                │                              │
                └─ out/research/ (inspectable) └─ every beat/segment must name a claim
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

- **`GeminiProvider`** — `client.models.generate_content(model=…, contents=…,
  config=GenerateContentConfig(response_mime_type="application/json",
  response_json_schema=to_gemini_schema(schema), temperature=…, max_output_tokens=…))`,
  then `schema.model_validate_json(response.text)`. Transient 5xx get capped,
  jittered backoff; a 429 honours a short `retryDelay`, retries a bounded number
  of times, and otherwise raises `RateLimitError` immediately — a daily quota is
  reported, not slept through. The SDK's own five-attempt retry is disabled when
  the client is built, so that budget means one HTTP request per attempt instead
  of five multiplied by it.
- **Credential routing** — no call site reads a Gemini key. A request names the
  *tool* it belongs to — the tool its schema implies, or the one the provider is
  pinned to while recording — and `manorem_core.gemini.GeminiCredentialResolver`
  maps that tool to its variable. Errors name the tool and its variable, never
  the value. See [env.md](env.md#gemini-credentials).
- **`schema_shim`** (`to_gemini_schema`) down-converts a Pydantic JSON Schema to
  Gemini's supported subset, with a round-trip fidelity test. Required: the docs warn
  that deeply nested schemas may be rejected and only syntactic validity is
  guaranteed — which is why IR is generated **per scene**, never whole-project.
  `maxItems` is dropped along the way even though Gemini accepts the keyword: it
  prices an array bound against the schema it repeats and rejects the whole
  request with a bare 400 naming no field, and every such bound originates as
  `Field(max_length=...)` on the IR model, which still validates it on the answer.
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
| `ResearchAgent` | idea + retrieved sources → `ResearchBrief` (claims, entities, visual candidates, open questions) |
| `EvidenceAgent` | brief + retrieved sources → `EvidenceAssessment` — a closed relation per (claim, evidence), never prose |
| `StoryAgent` | brief → `StoryOutline` — `arc` and `rationale` required, so no run silently defaults every subject to one template |
| `ScriptAgent` | outline (+ brief) → `Script` — narration segments only; timings come from deterministic `pacing.py`, never the model |
| `VisualPlannerAgent` | beat + segment + skill menu → `VisualPlan` |
| `IRGeneratorAgent` | plan + segment + scoped vocabulary → **one `Scene`** |
| `RepairAgent` | scene + its semantic diagnostics → a **JSON Patch** (never a rewrite) |

`VisualPlan` makes *what / why / when / how / focus* required fields: a plan that
skipped its reasoning does not validate. Refusing the response is the surest way to
make a model plan rather than free-associate.

## Retrieval, evidence, and what neither of them proves

Research sits behind a provider-neutral seam. The pipeline asks a
`ResearchProvider` for a `ResearchRequest` — a **model**, not a query string, so
persisted artifacts never bake in a vendor's query syntax — and gets back a
`ResearchResult` carrying `Source` metadata plus the bytes actually retrieved.
Three backends ship:

- **`StubResearchProvider`** — the configured fixture corpus, or *nothing*. An
  empty result is a real answer; a plausible-looking invented source is exactly
  what the provenance layer exists to stop.
- **`CassetteResearchProvider`** — record / replay on disk. A miss **raises**;
  it never falls through to a live call, which is what makes offline mode a
  structural guarantee rather than a promise.
- **`BraveResearchProvider`** — the one real, opt-in backend. It searches, then
  fetches each result page and strips it to text; a page it cannot fetch is
  dropped rather than substituted with the search snippet, because the snippet is
  the engine's summary of the page, not the page. The API key is read lazily
  from `Settings`, lives in a `SecretStr`, and is never hashed, cached, persisted
  or put in a URL.

The chain is explicit and inspectable at every hop:

```
ResearchRequest ─► ResearchResult ─► Source ─► Evidence ─► Claim
                                                               └─► ClaimEvidenceLink
```

Three distinctions are load-bearing, and the **types** encode them rather than
prose:

1. **Retrieval is not support.** `ProvenanceValidator` (`RES801`) proves a cited
   URL was genuinely retrieved — and nothing more. Support is a separate,
   explicit `ClaimEvidenceLink` with a `relation`, and `ClaimStatus` records what
   those relations added up to.
2. **Support is not truth.** There is deliberately no factuality score
   anywhere: no `truth_score`, no `confidence` percentage. The system exposes
   claim, evidence, relation, status and source; downstream planning decides
   what to do with them.
3. **A URL is a location, not an identity.** A `Source` is addressed by the
   sha256 of its content (`research/sources/<digest>.json`), so two retrievals of
   "the same URL" cannot silently pool, and a source whose bytes later change is
   reported (`RES808`).

**Evidence is extracted, not asserted.** A claim cites `(url, quote)`;
`locate_quote` finds that quote in the retrieved bytes and records the exact
character range it occupies, and `evidence_id` is a content address of
(source, quote) so citing the same passage twice yields one record. A quote that
cannot be found is `RES803` and is repaired — never approximated. Whether a
located span *supports* the claim is model-judged, but only as a closed enum
(`supports` / `partially_supports` / `contradicts` / `contextualizes`) and only
against ids that already exist: a link naming an unknown claim or evidence is
discarded with `RES807`, never snapped onto the nearest real one.

`derive_status` then computes each claim's status from its surviving links — no
links `unassessed`, any contradiction `contradicted`, partial `partially_supported`,
support `supported`, context only `unsupported`. A claim cannot *claim* support
it has not recorded (`RES804` error), and "nobody looked" (`RES811`, informational)
is not the same statement as "we looked and it is not backed" — which is its own
finding: an `unsupported` claim is a `RES804` warning at the claim *and* at any
script segment that states it as fact, so unsupported factual narration is
detectable rather than merely discouraged.

`validate_traceability` then holds every beat's and segment's claim reference
against the brief: a dangling id is an error (`RES807`), a contradicted claim
stated outright is a warning (`RES814`), a segment that states an unsupported
claim as fact is a warning (`RES804`), and an unused claim (`RES812`) or an
untraced line (`RES813`) is informational — a short explainer legitimately
leaves research behind, and a rhetorical question asserts nothing.

All of it lands in the existing `RES8xx` namespace, which is deliberately
disjoint from `SEMANTIC_ERROR_CODES`, so research diagnostics never reach the
Visual IR repair loop. The research stage runs its own bounded repair loop under
`RESEARCH_REPAIR_CODES` with the same `max_repair_attempts` knob, is **off by
default** (`--research` opts in), and writes `out/research/` *before* validation
runs — a failed build is still inspectable. Retrieved content is handled as
untrusted throughout: it reaches prompts only inside a delimited
`UNTRUSTED RETRIEVED CONTENT` block, with instructions in the same file telling
the model not to follow anything found there.

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
