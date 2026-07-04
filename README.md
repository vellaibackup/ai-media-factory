# AFOS — AI Media Factory (MVP Pipeline)

One command, one publish-ready short-form video.

```bash
pip install -e .
run_ai_media_factory "England reach the World Cup quarter-finals"
```

Output lands in `output/<topic-slug>/`:
- `video.mp4` — 1080x1920 (9:16), narrated, captioned
- `manifest.json` — full record of what was generated, from what inputs, and how long each stage took

## Configuration (optional)

Script generation will use a real LLM if you provide a key; otherwise it falls back to a local template automatically. No configuration is required to run the pipeline today.

```bash
export GEMINI_API_KEY="..."   # optional
export GROQ_API_KEY="..."     # optional
```

## Status

This is a Day 1 MVP build. See `pipeline/LIMITATIONS.md` for exactly what's real vs. stubbed today, and `docs/DAILY_LOG.md` for build history and what's changing next.

## Architecture

Six stages, run in sequence by `pipeline/orchestrator.py`, each independently swappable:

1. `stage1_script.py` — topic → script beats
2. `stage2_voice.py` — script → narration audio
3. `stage3_visuals.py` — script → visual card clips
4. `stage4_assembly.py` — audio + visuals → one video
5. `stage5_format.py` — enforce final 9:16 platform spec
6. `stage6_output.py` — write final file + manifest

## Tests

```bash
pip install pytest
python3 -m pytest pipeline/tests/ -v
```
