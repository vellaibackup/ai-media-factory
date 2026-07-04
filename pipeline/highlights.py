from pathlib import Path
import subprocess
import random


class HighlightError(Exception):
    pass


def extract_highlights(video_path: Path, out_dir: Path, num_clips: int = 3):
    """
    Extracts 'highlight-style' segments from a football video.
    (Heuristic version for MVP — no ML yet)
    """

    out_dir.mkdir(parents=True, exist_ok=True)

    # ⚠️ SIMPLE HEURISTIC:
    # We randomly sample "high-energy" moments (future: real detection)
    clips = []

    for i in range(num_clips):
        start_time = random.randint(5, 60)  # skip intro / dead time
        duration = random.randint(3, 6)     # TikTok-style short clips

        out_path = out_dir / f"highlight_{i}.mp4"

        cmd = [
            "ffmpeg",
            "-y",
            "-ss", str(start_time),
            "-i", str(video_path),
            "-t", str(duration),
            "-vf", "scale=640:360",
            "-r", "30",
            out_path
        ]

        subprocess.run(cmd, check=True)
        clips.append(out_path)

    return clips