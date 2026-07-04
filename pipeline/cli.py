import argparse
from pathlib import Path
import subprocess
from typing import Sequence

from pipeline.path_utils import (
    output_path,
    path_from,
    require_directory,
    require_file,
    write_concat_file,
)


def run_pipeline(work_dir: Path):

    visuals_dir = output_path(work_dir, "visuals")
    visuals_dir.mkdir(parents=True, exist_ok=True)
    require_directory(visuals_dir, "Visual output")

    clips = sorted(
        (
            clip
            for clip in visuals_dir.glob("clip_*.mp4")
            if clip.stem.removeprefix("clip_").isdigit()
        ),
        key=lambda clip: (
            int(clip.stem.removeprefix("clip_")),
            clip.stem,
        ),
    )

    if not clips:
        raise RuntimeError(f"No indexed clips found in: {visuals_dir}")

    clip_indices = [int(clip.stem.removeprefix("clip_")) for clip in clips]
    if clip_indices != sorted(clip_indices) or len(clip_indices) != len(set(clip_indices)):
        raise RuntimeError(f"Clip ordering is not deterministic: {clip_indices}")

    concat_file = write_concat_file(path_from(visuals_dir, "concat.txt"), clips)
    require_file(concat_file, "FFmpeg concat input")

    final_video = path_from(visuals_dir, "final.mp4")
    require_directory(final_video.parent, "Final video output")

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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_ai_media_factory")
    parser.add_argument("topic", nargs="+", help="video topic")
    args = parser.parse_args(argv)

    from pipeline.orchestrator import run

    run(" ".join(args.topic))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
