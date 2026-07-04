# AFOS Build — Daily Log

## Day 1 — July 3, 2026

### Goal
Get `run_ai_media_factory "<topic>"` working end-to-end, producing one real, valid, publish-format video file, with zero paid dependencies.

### Result: ✅ Working
```
$ run_ai_media_factory "England reach the World Cup quarter-finals"
Done in 20.63s
Video:    output/england-reach-the-world-cup-quarter-finals/video.mp4
Manifest: output/england-reach-the-world-cup-quarter-finals/manifest.json
```
Verified: valid MP4, 1080x1920, h264 video + AAC audio, ~17s runtime, correct duration match between narration and visuals. Full run takes ~21 seconds end-to-end.

3/3 automated tests pass, including a full end-to-end smoke test.

### What was built today
- Full repo scaffold and installable package (`pip install -e .` → real `run_ai_media_factory` command)
- Orchestrator with per-stage timing and specific failure attribution
- All 6 stages implemented and wired:
  - Stage 1 (script): fallback chain architecture for Gemini/Groq is in place; ran on the local template fallback today (no API keys configured in this build environment)
  - Stage 2 (voice): **fully real** — ffmpeg's offline `flite` engine, zero network, zero keys
  - Stage 3 (visuals): **fully real** — FFmpeg-generated animated text cards, per the approved zero-cost/template-based design
  - Stage 4 (assembly): **fully real** — FFmpeg concat + audio mux
  - Stage 5 (format): **fully real** — enforces final 9:16 spec, platform-upload-ready encode
  - Stage 6 (output): **fully real** — writes video.mp4 + full manifest.json
- 3 automated tests (Stage 1 unit tests + one full end-to-end smoke test), all passing
- `LIMITATIONS.md` — explicit, honest list of what's stubbed vs. real today
- `SCHEMA.md` — manifest schema documentation

### Known gaps going into Day 2 (see LIMITATIONS.md for full detail)
1. **Script quality** — today's output uses the deterministic local template, not a real LLM. This is the top priority for Day 2: get a real free-tier LLM key wired in and verified.
2. **Voice quality** — using ffmpeg's built-in `flite` (robotic) as a stand-in for Kokoro, because Kokoro's model weights need a Hugging Face download this build sandbox can't reach. This needs to be resolved on the actual target VM (which will have normal internet access), not in this sandbox.
3. **Visual quality** — template motion graphics, as intentionally scoped. Not a Day 2 priority; correct as-is for MVP.

### Plan for Day 2
- Wire in and verify a real LLM key for Stage 1 (pending Niranjan/CTO providing a free-tier Gemini or Groq key, or confirming Claude Code should self-provision one)
- Attempt Kokoro integration on a network-unrestricted environment; fall back to keeping `flite` documented as the interim engine if blocked again
- Run 3 total sample topics end-to-end and collect them under `/samples/` per the deliverables list
- Tighten Stage 3 visual variety (currently cycles a fixed 4-color palette; low risk, quick polish)

### Open items for the CEO/CTO
- Need a decision on where the real LLM API key comes from (who provisions it, how it's stored/rotated) before Day 2's top priority can close out.
