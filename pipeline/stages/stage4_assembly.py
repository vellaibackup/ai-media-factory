"""
Stage 4: Assembly
Input:  visual clip paths (Stage 3, silent), narration audio path (Stage 2)
Output: dict { "assembled_path": str }  -- one video, visuals concatenated,
        narration muxed in as the soundtrack.
"""
from __future__ import annotations
import subprocess
from pathlib import Path

from pipeline.path_utils import require_directory, require_file
from pipeline.core.video_spec import VideoSpec, ensure_video_spec


class Stage4Error(Exception):
    pass


def _concat_clips(concat_file: Path, out_path: Path) -> None:
    require_file(concat_file, "FFmpeg concat input")
    require_directory(out_path.parent, "Stage 4 output")
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-c", "copy",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Stage4Error(f"visual concat failed: {result.stderr[-800:]}")


def _mux_audio(video_path: Path, audio_path: str, out_path: Path) -> None:
    require_directory(out_path.parent, "Stage 4 output")
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(video_path),
        "-i", str(audio_path),
        "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
        "-shortest",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Stage4Error(f"audio mux failed: {result.stderr[-800:]}")


def run(
    concat_file: Path,
    audio_path: str,
    work_dir: Path,
    video_spec: VideoSpec | dict | str | None = None,
) -> dict:
    if video_spec is not None:
        ensure_video_spec(video_spec)
    if not concat_file:
        raise Stage4Error("Stage 4 received no concat file")
    if not audio_path:
        raise Stage4Error("Stage 4 received no narration audio from Stage 2")

    assembly_dir = work_dir / "assembly"

    silent_path = assembly_dir / "visuals_concat.mp4"
    _concat_clips(concat_file, silent_path)

    assembled_path = assembly_dir / "assembled.mp4"
    _mux_audio(silent_path, audio_path, assembled_path)

    return {"assembled_path": str(assembled_path)}
