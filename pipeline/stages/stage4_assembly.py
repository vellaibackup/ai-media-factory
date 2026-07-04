"""
Stage 4: Assembly
Input:  visual clip paths (Stage 3, silent), narration audio path (Stage 2)
Output: dict { "assembled_path": str }  -- one video, visuals concatenated,
        narration muxed in as the soundtrack.
"""
from __future__ import annotations
import subprocess
from pathlib import Path


class Stage4Error(Exception):
    pass


def _concat_clips(clip_paths: list[str], out_path: Path) -> None:
    concat_list = out_path.parent / "video_concat_list.txt"
    with open(concat_list, "w") as f:
        for p in clip_paths:
            f.write(f"file '{Path(p).resolve()}'\n")
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_list),
        "-c", "copy",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Stage4Error(f"visual concat failed: {result.stderr[-800:]}")


def _mux_audio(video_path: Path, audio_path: str, out_path: Path) -> None:
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


def run(clip_paths: list[str], audio_path: str, work_dir: Path) -> dict:
    if not clip_paths:
        raise Stage4Error("Stage 4 received no visual clips from Stage 3")
    if not audio_path:
        raise Stage4Error("Stage 4 received no narration audio from Stage 2")

    assembly_dir = work_dir / "assembly"
    assembly_dir.mkdir(parents=True, exist_ok=True)

    silent_path = assembly_dir / "visuals_concat.mp4"
    _concat_clips(clip_paths, silent_path)

    assembled_path = assembly_dir / "assembled.mp4"
    _mux_audio(silent_path, audio_path, assembled_path)

    return {"assembled_path": str(assembled_path)}
