from pathlib import Path
import subprocess


class Stage3Error(Exception):
    pass


def run(script: dict, beat_durations: list[float], work_dir: Path):

    beats = script.get("beats")
    if not beats:
        raise Stage3Error("No beats found")

    highlights_dir = work_dir / "highlights"
    visuals_dir = work_dir / "visuals"
    visuals_dir.mkdir(parents=True, exist_ok=True)

    highlights_dir.mkdir(parents=True, exist_ok=True)

    # ----------------------------
    # FIX 1: ENSURE SOURCE VIDEO EXISTS
    # ----------------------------
    base_video = next(highlights_dir.glob("*.mp4"), None)

    if not base_video:
        print("⚠️ No source video found — creating fallback video...")

        base_video = highlights_dir / "fallback.mp4"

        subprocess.run([
            "ffmpeg",
            "-y",
            "-f", "lavfi",
            "-i", "testsrc=duration=20:size=640x360:rate=30",
            str(base_video)
        ], check=True)

    # ----------------------------
    # BUILD VISUAL CLIPS
    # ----------------------------
    outputs = []

    for i, duration in enumerate(beat_durations):

        out_path = visuals_dir / f"clip_{i}.mp4"

        subprocess.run([
            "ffmpeg",
            "-y",
            "-i", str(base_video),
            "-t", str(duration),
            "-vf", "scale=640:360",
            "-r", "30",
            str(out_path)
        ], check=True)

        outputs.append(str(out_path))

    return {
        "clip_paths": outputs
    }