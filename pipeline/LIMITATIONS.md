# Known Limitations — Day 1 MVP

This file exists so nobody mistakes today's output quality for the intended end-state. Every item here is a deliberate, isolated stub with a known upgrade path — not a hidden gap.

## 1. Script generation is using the local template fallback, not a real LLM
**Why:** No `GEMINI_API_KEY` / `GROQ_API_KEY` is configured in this build environment.
**What's real:** The fallback chain (Gemini → Groq → local template) is fully wired in `stage1_script.py`. The moment a real key is set as an environment variable, the pipeline will use it automatically — no code change needed.
**What's lost today:** Script quality is deterministic and formulaic, not genuinely written per-topic. This is the single biggest quality gap in today's build and the top priority for Day 2.

## 2. Voice is ffmpeg's offline `flite` engine, not Kokoro/Chatterbox-Turbo
**Why:** Kokoro and Chatterbox-Turbo require downloading model weights from Hugging Face, and this build environment's network allowlist doesn't include `huggingface.co`. `flite` is built into the `ffmpeg` binary already present in this environment, so it was the only voice engine that could produce real, working audio today with zero network dependency.
**What's real:** Full text-to-speech, correctly timed per beat, muxed into the final video.
**What's lost today:** Voice quality is robotic/dated compared to Kokoro or Chatterbox-Turbo. This is a self-contained swap in `stage2_voice.py` only — no other stage needs to change when it's upgraded. This should happen on whatever machine actually has open internet access (the target Oracle Cloud VM, not this sandboxed build environment).

## 3. Visuals are template motion graphics, not AI-generated video
**Why:** This was an explicit decision in the approved Zero-Cost Stack assessment — reliable, automated, free AI video generation isn't achievable yet, so the MVP intentionally substitutes FFmpeg-driven text/stat cards with a slow zoom effect.
**What's real:** Fully automated, on-brand-color, correctly-timed visual cards per beat.
**What's lost today:** No true dynamic video — this is a designed motion graphic, not generated footage. This is the planned first post-MVP upgrade target (Stage 3 swap only).

## 4. Captions are baked into the visual card, not a separate subtitle overlay
**Why:** Simplification for Day 1 — Stage 3 draws the beat text directly onto its background.
**What's lost:** Less flexibility (can't toggle captions independently, no separate styling pass). Fine for MVP; worth revisiting once Stage 5 grows real per-platform variants.

## 5. Single format only (9:16)
As planned — 1:1 and 16:9 variants are an explicit post-MVP iteration, not a Day 1 gap.

## 6. No publishing
As planned and confirmed — this produces a publish-ready file, not an auto-posted one. Postiz integration is a separate future stage.

## What's genuinely solid today
- The orchestrator, CLI, and six-stage contract are real and tested — this is the architecture the team will keep, not throwaway scaffolding.
- Error handling: a broken stage stops the run with a specific, attributable error rather than a silent bad file.
- The manifest is complete and accurate per run, including timing per stage — this is what makes future upgrades measurable rather than a guess.
