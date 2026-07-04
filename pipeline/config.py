"""
Shared configuration for the AFOS end-to-end pipeline.

Day 1 note: LLM provider keys are read from environment variables if present.
If none are configured, Stage 1 falls back to a local template-based script
generator so the full pipeline still runs end-to-end with zero API keys.
See pipeline/LIMITATIONS.md for what's real vs. stubbed today.
"""
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "output"

# --- Video format ---
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920  # 9:16 short-form vertical
FPS = 30

# --- Script generation (Stage 1) ---
TARGET_SCRIPT_SECONDS = 30          # target spoken length of the whole video
MAX_BEATS = 4                        # intro + up to 3 body beats (no separate outro beat)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")

# --- Voice synthesis (Stage 2) ---
# Day 1: ffmpeg's built-in `flite` filter (libflite), fully offline, zero network,
# zero API keys. This is a temporary substitute for Kokoro/Chatterbox-Turbo --
# those need model weights from Hugging Face, which this sandbox can't reach.
# See LIMITATIONS.md.
FLITE_VOICE = "slt"  # built-in flite voice
AUDIO_SAMPLE_RATE = 16000

# --- Visual assets (Stage 3) ---
BACKGROUND_COLORS = [
    "0x1a1a2e",  # dark navy
    "0x16213e",  # deep blue
    "0x0f3460",  # steel blue
    "0x1b262c",  # slate
]
ACCENT_COLOR = "0xe94560"  # accent red/pink for highlight text

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_PATH_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
