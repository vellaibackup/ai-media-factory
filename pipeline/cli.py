from pathlib import Path
import subprocess

def run_pipeline(work_dir: Path):

    output_dir = work_dir / "output"
    visuals_dir = output_dir / "visuals"
    visuals_dir.mkdir(parents=True, exist_ok=True)

    clips = sorted(visuals_dir.glob("clip_*.mp4"))

    if not clips:
        raise Exception("No clips found")

    # IMPORTANT FIX:
    # concat.txt must contain ONLY filenames, NOT full paths

    concat_file = visuals_dir / "concat.txt"

    with open(concat_file, "w") as f:
        for clip in clips:
            # FIX: write ONLY filename (no duplicated folders)
            f.write(f"file '{clip.name}'\n")

    final_video = visuals_dir / "final.mp4"

    subprocess.run([
        "ffmpeg",
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_file),
        "-c", "copy",
        str(final_video)
    ], check=True)

    return str(final_video)


if __name__ == "__main__":
    import sys
    work_dir = Path.cwd()
    run_pipeline(work_dir)