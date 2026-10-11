# Configuration

Configuration is environment-driven with the `MANOREM_` prefix, read once into a
frozen `Settings` (`manorem_core.settings`) via `get_settings()` (an `lru_cache` of
one). Copy `.env.example` to `.env` and edit; every value has a default chosen to
**work offline**, so a fresh checkout runs with no configuration at all.

`get_settings()` is cached — a test that changes the environment must
`get_settings.cache_clear()` around the change.

`tests/fixtures/cassettes/` ships empty, so replaying needs no key but *recording*
does. `uv run python scripts/record_cassettes.py` fills the directory for each
documented example (plain and `--research`) and then replays them under
`--offline` to prove the recordings need no network.

## Variables

| Variable | Default | What it does |
| --- | --- | --- |
| `MANOREM_WORKSPACE_ROOT` | `out` | where `build` writes artifacts when `-o` is omitted |
| `MANOREM_LOG_LEVEL` | `INFO` | structlog level |
| `MANOREM_LOG_JSON` | `false` | JSON logs for workers; console rendering for humans |
| `MANOREM_LLM_PROVIDER` | `cassette` | `cassette` \| `gemini` \| `stub` |
| `MANOREM_GEMINI_KEY_MODE` | `shared` | `shared` = one credential for every tool; `dedicated` = one per tool |
| `MANOREM_GEMINI_APIKEY` | *(unset)* | the shared credential; required for a live Gemini run in `shared` mode |
| `MANOREM_GEMINI_API_KEY` | *(unset)* | legacy spelling of the shared credential, still accepted |
| `MANOREM_GEMINI_ALLOW_SHARED_FALLBACK` | `false` | `dedicated` mode only: let a tool with no key of its own borrow the shared one |
| `MANOREM_<TOOL>_GEMINI_APIKEY` | *(unset)* | one credential per tool in `dedicated` mode; see [Gemini credentials](#gemini-credentials) |
| `MANOREM_GEMINI_MODEL` | `gemini-3.8-flash` | model for research, script, IR generation, repair |
| `MANOREM_GEMINI_MODEL_HEAVY` | `gemini-3.8-flash` | model for story and visual planning |
| `MANOREM_LLM_TEMPERATURE` | `0.4` | sampling temperature (0–2) |
| `MANOREM_LLM_MAX_TOKENS` | `8192` | per-call output cap |
| `MANOREM_AI_RECORD` | `false` | `1` refreshes cassettes from live calls |
| `MANOREM_AI_CASSETTE_DIR` | `tests/fixtures/cassettes` | record/replay location |
| `MANOREM_RESEARCH_ENABLED` | `false` | record sources, evidence and claims (`build --research` overrides) |
| `MANOREM_RESEARCH_PROVIDER` | `stub` | `stub` \| `cassette` \| `brave` — only `brave` can reach the network |
| `MANOREM_RESEARCH_API_KEY` | *(unset)* | required only when the provider is `brave`; never hashed, cached or persisted |
| `MANOREM_RESEARCH_BASE_URL` | *(unset)* | optional gateway URL for the `brave` backend |
| `MANOREM_RESEARCH_CASSETTE_DIR` | `tests/fixtures/research_cassettes` | research record/replay location |
| `MANOREM_RESEARCH_RECORD` | `false` | `1` refreshes research cassettes from live calls (never under `--offline`) |
| `MANOREM_RESEARCH_MAX_SOURCES` | `6` | upper bound on retrieved sources |
| `MANOREM_RESEARCH_CACHE` | `true` | reuse a prior retrieval for the same request and provider |
| `MANOREM_RESEARCH_CACHE_TTL_S` | `86400` | how long a cached retrieval stays fresh (`0` = until deleted) |
| `MANOREM_MAX_REPAIR_ATTEMPTS` | `2` | bounded repair cap (0–5), shared by IR repair and research repair |
| `MANOREM_RENDER_QUALITY` | `draft` | `draft` (854×480@15) \| `medium` (1280×720@30) \| `final` (1920×1080@60) |
| `MANOREM_RENDER_TIMEOUT_S` | `600` | per-render subprocess timeout |
| `MANOREM_FRAME_SAMPLE_HZ` | `1.0` | keyframe sampling rate the Visual QA seam will read |
| `MANOREM_NARRATION_WPM` | `150.0` | placeholder pacing model until TTS lands |

Model ids live here, never inline at a call site, so switching models is a config
change. Because the defaults keep the provider on `cassette`, research on `stub`
and switched **off**, render quality on `draft`, and the repair loop at two
attempts, `make test` and `manorem build` both run with no API key. Selecting
`brave` without `--offline` and a `MANOREM_RESEARCH_API_KEY` is the one way to
put a request on the network; under `--offline` the live backend is never even
constructed, and `MANOREM_RESEARCH_RECORD` is forced off.

## Gemini credentials

Gemini keys are resolved in exactly one place,
`manorem_core.gemini.GeminiCredentialResolver`, and every live Gemini request
routes through it:

```
schema -> tool -> GeminiProvider -> resolver -> environment variable -> Gemini API
```

No call site reads a Gemini key. A request's **tool** is implied by the schema it
asks for — each pipeline stage produces exactly one — except in a recording run,
which pins `cassette` so a recording is charged to the recorder's own credential.

**`MANOREM_GEMINI_KEY_MODE=shared` (the default)** — every tool draws
`MANOREM_GEMINI_APIKEY`. This is the original behaviour, so an existing setup
changes nothing; `MANOREM_GEMINI_API_KEY` keeps working as a legacy alias.

**`MANOREM_GEMINI_KEY_MODE=dedicated`** — each tool draws its own
`MANOREM_<TOOL>_GEMINI_APIKEY`. A missing one fails *at startup*, naming the
variable, rather than partway through a build:

| Tool | Variable | Used by |
| --- | --- | --- |
| `cassette` | `MANOREM_CASSETTE_GEMINI_APIKEY` | the record-mode backend (`MANOREM_AI_RECORD`) |
| `research` | `MANOREM_RESEARCH_GEMINI_APIKEY` | the `ResearchBrief` stage |
| `evidence` | `MANOREM_EVIDENCE_GEMINI_APIKEY` | the `EvidenceAssessment` stage |
| `story` | `MANOREM_STORY_GEMINI_APIKEY` | the `StoryOutline` stage |
| `script` | `MANOREM_SCRIPT_GEMINI_APIKEY` | the `Script` stage |
| `visual_plan` | `MANOREM_VISUAL_PLAN_GEMINI_APIKEY` | the `VisualPlan` stage |
| `scene` | `MANOREM_SCENE_GEMINI_APIKEY` | `Scene` generation |
| `repair` | `MANOREM_REPAIR_GEMINI_APIKEY` | the `JsonPatch` repair stage |

A tool is never silently billed to another tool's key. The one substitution that
can be enabled is spelled out and off by default:
`MANOREM_GEMINI_ALLOW_SHARED_FALLBACK=true` lets a tool with no dedicated
credential borrow the shared one.

What a run needs is validated before any client is built: a live `gemini` run
needs every stage's credential, a recording run needs only `cassette`. Offline
and replay runs construct no client, so they never ask for a Gemini key. For a
round-robin pool over one backend there is already
`MANOREM_LLM_PROVIDER=keypool` with `MANOREM_KEYPOOL_KEY_POOL`; a plural
`MANOREM_GEMINI_API_KEYS` list is *not* read by anything.

Credentials isolate workloads - they do not multiply quota. Keys issued by one
Gemini project share that project's rate limits, so a second key from the same
project buys no extra capacity. Keys from separate projects carry separate
quotas -- and recording bills each stage to its own tool, so a per-project key
set spreads a full recording across every budget instead of one. On a 429 the provider honours the backend's
`retryDelay` when it is short enough to wait out, retries a bounded number of
times with jittered backoff, and otherwise fails at once with a `RateLimitError`
naming the tool and its variable — never the value, and never in a loop against
a quota that will not clear. The Gemini SDK's own five-attempt retry is switched
off when the client is built, so one attempt of that budget is one HTTP request:
bounded work per call, rather than a retry nested inside a retry.
