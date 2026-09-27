# Configuration

Configuration is environment-driven with the `MANOREM_` prefix, read once into a
frozen `Settings` (`manorem_core.settings`) via `get_settings()` (an `lru_cache` of
one). Copy `.env.example` to `.env` and edit; every value has a default chosen to
**work offline**, so a fresh checkout runs with no configuration at all.

`get_settings()` is cached — a test that changes the environment must
`get_settings.cache_clear()` around the change.

## Variables

| Variable | Default | What it does |
| --- | --- | --- |
| `MANOREM_WORKSPACE_ROOT` | `out` | where `build` writes artifacts when `-o` is omitted |
| `MANOREM_LOG_LEVEL` | `INFO` | structlog level |
| `MANOREM_LOG_JSON` | `false` | JSON logs for workers; console rendering for humans |
| `MANOREM_LLM_PROVIDER` | `cassette` | `cassette` \| `gemini` \| `stub` |
| `MANOREM_GEMINI_API_KEY` | *(unset)* | required only when the provider is `gemini` |
| `MANOREM_GEMINI_MODEL` | `gemini-3.8-flash` | model for research, script, IR generation, repair |
| `MANOREM_GEMINI_MODEL_HEAVY` | `gemini-3.8-flash` | model for story and visual planning |
| `MANOREM_LLM_TEMPERATURE` | `0.4` | sampling temperature (0–2) |
| `MANOREM_LLM_MAX_TOKENS` | `8192` | per-call output cap |
| `MANOREM_AI_RECORD` | `false` | `1` refreshes cassettes from live calls |
| `MANOREM_AI_CASSETTE_DIR` | `tests/fixtures/cassettes` | record/replay location |
| `MANOREM_MAX_REPAIR_ATTEMPTS` | `2` | bounded repair-loop cap (0–5) |
| `MANOREM_RENDER_QUALITY` | `draft` | `draft` (854×480@15) \| `medium` (1280×720@30) \| `final` (1920×1080@60) |
| `MANOREM_RENDER_TIMEOUT_S` | `600` | per-render subprocess timeout |
| `MANOREM_FRAME_SAMPLE_HZ` | `1.0` | keyframe sampling rate the Visual QA seam will read |
| `MANOREM_NARRATION_WPM` | `150.0` | placeholder pacing model until TTS lands |

Model ids live here, never inline at a call site, so switching models is a config
change. Because the defaults keep the provider on `cassette`, render quality on
`draft`, and the repair loop at two attempts, `make test` and `manorem build` both
run with no API key.
