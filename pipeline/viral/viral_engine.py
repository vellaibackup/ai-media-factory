"""
VIRAL ENGINE (AFOS)
Turns normal clips → high-retention short-form structure
"""

from pathlib import Path
import random


class ViralError(Exception):
    pass


# ----------------------------
# HOOK GENERATION (CRITICAL)
# ----------------------------
def generate_hook(topic: str) -> str:
    hooks = [
        f"You missed this in {topic} 😳",
        f"This moment changed everything in {topic}",
        f"Nobody noticed this in {topic}...",
        f"This is why {topic} went crazy 🔥",
        f"The most insane part of {topic}..."
    ]
    return random.choice(hooks)


# ----------------------------
# VIRAL SCORE (future ML hook)
# ----------------------------
def score_clip(clip_path: str) -> float:
    """
    Placeholder scoring system (later upgrade to ML)
    """
    return random.uniform(0.5, 1.0)


# ----------------------------
# BUILD VIRAL STRUCTURE
# ----------------------------
def build_viral_sequence(topic: str, clips: list[str]) -> dict:
    """
    Reorders clips into viral format:
    HOOK → FAST CUTS → PAYOFF
    """

    if not clips:
        raise ViralError("No clips provided")

    hook = generate_hook(topic)

    # score clips
    scored = [(clip, score_clip(clip)) for clip in clips]

    # sort by "importance"
    scored.sort(key=lambda x: x[1], reverse=True)

    ordered_clips = [c[0] for c in scored]

    return {
        "hook_text": hook,
        "clips": ordered_clips,
        "structure": "viral_v1"
    }