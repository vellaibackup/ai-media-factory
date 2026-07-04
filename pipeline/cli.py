import argparse
from dataclasses import asdict
import json
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
    parser.add_argument("inputs", nargs="+", help="topic or: batch topic1,topic2")
    args = parser.parse_args(argv)

    from pipeline.orchestrator import run, run_batch

    if args.inputs[0] == "batch":
        if len(args.inputs) != 2:
            parser.error("batch mode requires one comma-separated topic list")
        topics = [topic.strip() for topic in args.inputs[1].split(",") if topic.strip()]
        if not topics:
            parser.error("batch mode requires at least one topic")

        from pipeline.core.content_strategy import ContentStrategy

        result = run_batch(
            ContentStrategy(
                niche=topics[0] if len(topics) == 1 else "mixed",
                topics=topics,
            )
        )
        serialisable = dict(result)
        serialisable["video_specs"] = [
            asdict(spec) for spec in result["video_specs"]
        ]
        print(json.dumps(serialisable, indent=2))
    else:
        run(" ".join(args.inputs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
