"""
Stage 5: Platform Formatting
Input:  assembled video path (Stage 4)
Output: dict { "formatted_path": str }

Day 1 / MVP note: captions are already burned into each visual card in
Stage 3 (kept together with the card generation for simplicity in this
first pass). This stage's job today is to GUARANTEE the output conforms
to the target short-form spec regardless of what upstream stages produced
(exact 1080x1920, even dimensions, +faststart for platform upload
compatibility) -- it's the pipeline's format safety net, not a no-op.
Per-platform variants (1:1, 16:9) are a listed post-MVP iteration; this
stage is where they'll be added without touching Stages 1-4.
"""
from __future__ import annotations
import subprocess
from pathlib import Path
from pipeline import config


class Stage5Error(Exception):
    pass


def run(assembled_path: str, work_dir: Path) -> dict:
    if not assembled_path:
        raise Stage5Error("Stage 5 received no assembled video from Stage 4")

    format_dir = work_dir / "formatted"
    format_dir.mkdir(parents=True, exist_ok=True)
    out_path = format_dir / "formatted.mp4"

    vf = (
        f"scale={config.VIDEO_WIDTH}:{config.VIDEO_HEIGHT}:"
        f"force_original_aspect_ratio=decrease,"
        f"pad={config.VIDEO_WIDTH}:{config.VIDEO_HEIGHT}:(ow-iw)/2:(oh-ih)/2,"
        f"setsar=1"
    )
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(assembled_path),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "160k",
        "-movflags", "+faststart",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Stage5Error(f"platform formatting failed: {result.stderr[-800:]}")

    return {"formatted_path": str(out_path)}
