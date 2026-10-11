# M4 Final Report: Per-Tool Gemini Credentials, the Scene 400, and the Recording

21 topics. Status: architecture implemented, all five code gates green
(1193 passed + 1 slow), first-ever `Scene` cassette recorded live,
remaining recording quota-paced (free tier 20/day, rolling window).

---

## 1. What was asked

A configurable, per-tool Gemini API-key architecture for the Manorem repo: one
centralized resolver, per-tool env-var naming, no hardcoded keys, no key values
in logs/errors/UI, all existing tests and behaviour preserved -- plus the M4
DoD: record the missing cassettes and run two literal offline `manorem build`
CLI runs.

## 2. The architecture (shipped)

- `GeminiKeyMode` (`shared`/`dedicated`) and `GeminiTool` (8 tools: cassette,
  evidence, repair, research, scene, script, story, visual_plan) live in
  `packages/core/src/manorem_core/settings.py`, so there is no
  settings↔resolver import cycle.
- `GeminiTool.env_var` = `MANOREM_<TOOL>_GEMINI_APIKEY`.
- `PIPELINE_GEMINI_TOOLS` = all tools except `CASSETTE` (the recorder draws its
  own credential).
- `GeminiCredentialResolver.key(tool)` / `.validate(*tools)` in
  `packages/core/src/manorem_core/gemini.py`: shared mode serves every tool
  from one key; dedicated mode reads each tool's own variable; missing means a
  `ConfigError` naming the variable, never a silent substitution. Opt-in
  `MANOREM_GEMINI_ALLOW_SHARED_FALLBACK` (default false).
- Legacy `MANOREM_GEMINI_API_KEY` still honoured by `gemini_key_or_raise`.
- `GeminiProvider` takes exactly one of `api_key=` / `resolver=` (else
  `ValueError`); per-call tool from `TOOL_BY_SCHEMA` or a pinned `tool=`
  (recording bills every stage to its own tool); unregistered schema in resolver
  mode raises `ProviderError` rather than billing another tool.
- Startup validation is gated to live paths only (gemini → all pipeline tools;
  cassette-record → `CASSETTE`); offline/replay validates nothing.
- `MANOREM_GEMINI_MODEL` / `MANOREM_GEMINI_MODEL_HEAVY` preserved
  (`gemini-3.8-flash`).
- Keys issued by one Gemini project share that project's quota; keys from
  separate projects carry separate quotas. Recording bills each stage to its
  own tool, so a per-project key set spreads a full recording across every
  budget instead of concentrating it on one: dedicated mode isolates workloads,
  it does not multiply quota within a project. Documented in `.env.example`
  and `docs/env.md`.

## 3. The 429 policy (shipped, proven live twice)

- At most 2 rate-limit retries; a named `Retry-After` past 60 s raises
  immediately; shorter waits are slept once; jittered backoff (0.5–1.5×, 30 s
  cap) otherwise.
- The SDK's own 5-attempt retry is disabled via
  `HttpRetryOptions(attempts=1)`: SDK-5 × policy-6 ≈ 30 requests per call
  against a 20/day quota -- that flooding, not successful calls, is what
  emptied the budget on Oct 6.
- `RateLimitError` is re-raised unwrapped (key-pool failover) and names only
  tool + variable (`... the backend asked to retry in 18h41m ... No credential
  value is reported here.`). Observed live Oct 8 and Oct 9.

## 4. The Scene 400: elimination record

Symptom: `Scene` (and only `Scene`) → bare `400 INVALID_ARGUMENT` on
`gemini-3.8-flash`, while four smaller stages succeeded. Every hypothesis was
tested live, most on a quota-free bucket (`gemini-3.1-flash-lite`):

| # | Hypothesis | Result |
|---|-----------|--------|
| 1 | Prompt too large (~11 KB) | Reconstructed offline; tiny. Rejected. |
| 2 | `max_output_tokens` (8192 for all stages) | Same for passing stages. Rejected. |
| 3 | `minItems` (11×, Scene-heavy) | Present in passing stages too. Rejected alone. |
| 4 | `const` / `not` in schema | False positives (substring matches in prose). Rejected. |
| 5 | Schema size (~20 KB) | 15 KB-minus-descriptions still 400s; small-with-all-constructs passes. Rejected as sole cause. |
| 6 | `nullable` / `minLength` / `maxLength` under strict validation | Stripped → still 400. Rejected as sole cause. |
| 7 | `responseJsonSchema` field itself | Bare object → OK on 3.8. Field fine, content at fault. |
| 8 | `anyOf` nesting / branch count / bounds-in-union | Single nested branch OK; 10 branches OK; minItems branch OK; full 21-branch union alone OK (8.5 KB). Only the full schema in context fails. |
| 9 | SDK-injected `property_ordering` | **Confirmed.** Bisect: wire-minus-ordering → OK; full/seeded orderings → 400 in both spellings on both models. |

## 5. Root cause

`google-genai`'s `process_schema` injects `property_ordering` (full property
lists) into every multi-property object on the `response_schema` path
(`order_properties=True`, no public toggle). The backend rejects any ordering
key on a schema of Scene's scale with a bare 400. Small schemas survive the
injection, which is why only Scene failed. Seeding the documented camelCase
spelling does not help (both spellings fatal); seeding it **empty** makes the
SDK skip its injection and the backend reads the vacuous list as a no-op.

## 6. The fix (shipped, proven live)

- `schema_shim.to_gemini_schema` seeds `"propertyOrdering": []` on every
  object with >1 property, mirroring the SDK's injection condition. Pinned by
  `test_multi_property_objects_carry_an_empty_property_ordering`.
- Provider stays on `response_schema` (the `responseJsonSchema` detour was
  measured and abandoned: its strict subset rejects the full schema for
  structural reasons).
- Cassette keys hash the **raw** `model_json_schema`, so shim changes never
  invalidate recordings.
- Proven live Oct 8: full seeded Scene schema → OK on 3.8-flash; SDK wire
  intercept confirms 58 empty orderings on the wire; first-ever `Scene`
  cassette recorded and validated.

## 7. What the 07:14 bulk revert took, and what was restored

Twelve tracked files were reverted to HEAD mid-session, discarding the
credential architecture, the provider rewrite, CLI wiring, the record script,
docs, and the user's research codes. Restored or rebuilt:

- Credential architecture (`settings.py`, `manorem_core/__init__.py`,
  `manorem_core/gemini.py`, `_support.py` gemini/cassette branches,
  `record_cassettes.py` resolver preflight + `--research` example, docs).
- Provider rewrite (`TOOL_BY_SCHEMA`, routing, 429/5xx policy, retry-option
  pin) -- re-derived from the surviving test spec, all 13 tests green.
- `enums.py` tail (my rewrite had truncated `NarrationRole`/`Easing`/`Aspect`
  and replaced the real `ClaimKind`); `diagnostics.py` RES802–RES814;
  `UnsafePathError` re-export.
- Not reverts but the seam of the in-progress research refactor, fixed
  minimally: M1 `Document` survives as a `RetrievedSource` subclass plus an
  M1 `retrieve()` seam on the new providers, so HEAD's pipeline/CLI/test
  callers typecheck and run unchanged.
- Migrated `test_pipeline.py` off the removed `gps_document()` helper.

## 8. Pipeline research stage (rebuilt from test specs)

The reverted stage was rewritten against `test_pipeline_research.py` (8 tests,
all green): `research_enabled` gating (M1 flow byte-identical when off),
`_research_request` / `_retrieve` (TTL cache in the run's store, recorded
fallback with `RES809` warning, `PipelineError` without one), bounded brief
repair loop (`research_attempts`, `PipelineError` naming the bound loop at the
cap), evidence assessment only when spans exist, artifacts before validation,
`ResearchValidator` + provenance errors fail loudly, traceability `RES807`
refuses unknown claim ids (`claims that do not exist`), INFO/WARNING findings
merge into run diagnostics. Judgment calls (repair-cap source, validation
error policy, manifest provider naming) are documented in code comments.

## 9. CLI research wiring (restored to its test spec)

`ResearchProviderName`, six `research_*` settings fields,
`_resolve_build_settings(..., research, research_provider)` (naming a backend
implies the stage; unknown backend exits 2), `build_research_provider`
(offline never constructs live backends; live always carries a recorded
fallback; recording offline is refused), `load_corpus` content-hash
validation, `--research/--no-research` + `--research-provider` flags, and a
carried-through (not yet consumed) `research_fallback` on `Pipeline`.

## 10. Recording state

- 13 cassettes on disk: 7 stale (Oct 5–8, superseded prompts) + 6 recorded
  Oct 8 evening, including the first `Scene`.
- Temperature 0.4 makes briefs nondeterministic, so each run cascades new keys;
  the completion run is pinned to `MANOREM_LLM_TEMPERATURE=0`.
- A full set is ~11 calls per example × 2 examples ≈ 22 > 20/day: plain and
  research record in separate windows with a replay-if-missing driver (the
  committed script always re-records; the driver resumes).
- Plain-example recording is scheduled for the next quota window (~01:05
  local); research follows in the one after.

## 11. DoD builds

Blocked on recording: both literal runs currently die at the first missing
`Scene` cassette (`ProviderError: no cassette for Scene at ...`). They run
unchanged once the set completes; the research variant needs no
`EvidenceAssessment` cassette (empty-corpus extraction yields no rows, so the
assessment stage is correctly skipped).

## 12. Gate status

- `ruff format` / `ruff check`: clean.
- `mypy --strict packages`: clean, 112 files.
- `pytest -m "not slow and not network"`: **1193 passed**, 1 skipped,
  1 deselected.
- `pytest -m slow`: 1 passed.
- Test runs herein move `.env` aside: the operator's real keys would otherwise
  break the credential suite's hermeticity (documented suite assumption, not a
  product issue).

## 13. Quota forensics

Free tier: 20 `generate_content` requests/day/model/project (rolling). 429s
carry `retryDelay` (seen: 2h15m, 3h53m, 17h–18h41m) and are honoured by
immediate failure, never sleep. Empirically only answered calls consume budget
(400/503/429s never triggered exhaustion); the Oct 6 exhaustion was SDK-retry
flooding (since disabled). Next window opens ~01:00 local.

## 14. Files changed (product)

`core/settings.py` (enums, key fields, mode, research fields),
`core/gemini.py` (resolver), `core/__init__.py` + `diagnostics.py` (exports,
RES codes), `ai/gemini.py` (routing, retry policy, retry-option pin),
`ai/schema_shim.py` (maxItems drop, ordering seed), `ai/pipeline.py`
(research stage, fallback seam, traceability gate), `ai/research/*` (Document
shim, retrieve seam), `cli/_support.py` (credential wiring, research
provider builder, corpus validation), `cli/app.py` (research flags),
`scripts/record_cassettes.py` (resolver preflight, research example),
`.env.example` + `docs/env.md` + `docs/ai-pipeline.md`.

## 15. Files changed (tests)

New: `test_gemini_credentials.py` (16), `test_gemini_provider.py` (13),
`test_schema_shim.py` +1 (ordering seed). Migrated: `test_pipeline.py`
(`gps_document` → `gps_retrieved`).

## 16. Deliberately not done

- Authoring the user's content-intelligence internals beyond the
  test-specified pipeline stage.
- `record_cassettes.py` resume semantics (driver covers the one-time need).
- `MANOREM_GEMINI_API_KEYS` (plural) remains dead config (`extra="ignore"`).
- Committing cassettes / deleting the 7 stale files: after the full set
  verifies offline.

## 17. Risks and watch-items

- Greedy (temp-0) briefs must reproduce byte-identically across windows or the
  split recording cascades again (fits anyway: ~11 calls/window).
- Model-declared brief statuses with no evidence links fail research
  validation loudly by design.
- 503 outages are retried 6× (~2 min); longer outages abort loudly.
- `Scene` with zero objects recorded once (valid per schema; narration-only
  beat) -- eyeball it on verify.

## 22. DoD blocker: generation quality, not infrastructure (Oct 10)

With cassettes complete through authoring, the plain build reaches compile and
dies honestly: `compilation left semantic errors the repair loop could not
clear` (~60 errors: `IR104_EMPTY_SCENE` ×2, `IR201_UNKNOWN_OBJECT_REF` ×~58).
Measured across sampling temperatures:

- temp 0 / 0.4: scenes validate but are **empty** (`objects: []`,
  `timeline: []`) -- the model fills camera/layout and skips content.
- temp 0.7: scenes have content but **dangling references** (cues target ids
  never declared) plus kind/props-union mismatches the boundary refuses.

The repair agent is checkmated by design for exactly this defect class: its
prompt forbids adding objects ("a patch that fabricates the missing object
will be rejected"), so with near-empty `objects[]` there is nothing sane to
retarget dangling cues onto -- it emits empty patches (`operations=0`) or
propless additions the boundary rejects, the bounded loop exhausts, and the
build refuses rather than rendering lies. Retargeting 7 distinct semantic
targets onto 1-2 existing objects would be nonsense video anyway: the scenes
are unrecoverable post-hoc, so generation itself must be fixed. Vocabulary is
exonerated (all packs resolve; 6 KB vocabulary present in the prompt).

Fix directions (owner's call -- prompts and IR are not this workstream):
(a) generator prompt: enforce declare-before-target harder, with a complete
`objects[]` few-shot showing kind-matching `props`; (b) relax repair's
no-new-entities rule for objects (real fabrication tradeoff); (c) simplify
the 21-kind props union the model consistently fails to satisfy;
(d) stronger scene/repair model (re-keys every cassette → full re-record).
The guardrails behaved flawlessly throughout: boundary refusals, bounded
loops, no silent renders. No further quota should be spent re-sampling until
one of (a)-(d) lands -- systematic confusion, not noise.

## 18. Reproduction

1. `uv run ruff format packages tests scripts && uv run ruff check packages tests scripts`
2. `uv run mypy --strict packages`
3. Move `.env` aside; `uv run pytest -m "not slow and not network"`; `uv run pytest -m slow`; restore.
4. `MANOREM_LLM_TEMPERATURE=0 uv run python scripts/record_cassettes.py` (fresh quota).
5. The two literal `manorem build ... --offline` runs.

## 19. Decision log (judgment calls)

- Empty ordering over SDK upgrade/patch, REST transport, or union redesign:
  smallest diff, backend-verified, zero re-records.
- `response_schema` kept over `responseJsonSchema`: strict-subset rejects the
  full schema for structural reasons; OpenAPI mode accepts it.
- Repair loop triggers on extraction errors only; validation errors fail
  loudly (no test exercises validation-driven repair).
- Manifest names the backend that produced the result (`_retrieve` returns
  both).
- `research_fallback` accepted-and-stored before its consumer stage lands.
- Temperature pinned to 0 for recording determinism (env, not code).

## 20. Open threads for the user

- Review the rebuilt pipeline stage against the lost original (behaviors are
  test-pinned; internals are mine).
- `test_pipeline_research.py` non-ffmpeg tests now pass; confirm intent.
- Commit/refresh cadence for cassettes after prompt edits.
- Whether `MANOREM_GEMINI_API_KEYS` (plural) should warn instead of silently
  ignoring.

## 21. Bottom line

M4's architecture, policy, gates, and root-cause work are complete and green;
the first `Scene` exists; what remains is quota-paced mechanical recording
(scheduled), the two literal builds, stale-cassette deletion, and committing
the set.
