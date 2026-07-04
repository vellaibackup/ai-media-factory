# manifest.json Schema

Written by Stage 6 into `output/<topic-slug>/manifest.json` for every run.

| Field | Type | Description |
|---|---|---|
| `topic` | string | The input topic exactly as provided to the CLI |
| `generated_at_utc` | string (ISO 8601) | When the run completed |
| `pipeline_version` | string | Pipeline build tag (`mvp-day1` today) |
| `script_source` | string | `"gemini"` \| `"groq"` \| `"openrouter"` \| `"local_template"` — which script generator actually produced the beats |
| `beats` | array | The script beats used, each `{ "text": string, "seconds": number }` |
| `voice_engine` | string | Which TTS engine produced the narration (`"flite"` today) |
| `video_format` | string | Output resolution, e.g. `"1080x1920"` |
| `stage_timings_seconds` | object | Wall-clock seconds per stage, keyed by stage name |
| `total_runtime_seconds` | number | Total wall-clock time for the whole run |
| `warnings` | array of strings | Non-fatal issues surfaced during the run (e.g. fallback used) |
| `known_limitations` | array of strings | Static list matching `LIMITATIONS.md`, included so the manifest is self-explanatory without needing the repo |
