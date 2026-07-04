"""
Stage 2: Voice Synthesis (CLEAN SAFE VERSION)
No flite. No unsafe ffmpeg filters. Mac compatible.
"""

from __future__ import annotations
import subprocess
import wave
from pathlib import Path
from pipeline import config
from pipeline.path_utils import ffconcat_path
from pipeline.core.video_spec import VideoSpec, ensure_video_spec


class Stage2Error(Exception):
    pass


def _synthesize_beat(text: str, out_path: Path) -> None:
    """
    Safe macOS voice engine using 'say'.
    """

    try:
        aiff_path = out_path.with_suffix(".aiff")

        # macOS built-in TTS
        subprocess.run([
            "say",
            "-v", "Samantha",
            "-o", str(aiff_path),
            text
        ], check=True)

        # convert to wav (safe ffmpeg only)
        subprocess.run([
            "ffmpeg",
            "-y",
            "-i", str(aiff_path),
            "-ar", str(config.AUDIO_SAMPLE_RATE),
            str(out_path)
        ], check=True)

        aiff_path.unlink(missing_ok=True)

    except Exception as e:
        raise Stage2Error(f"Voice synthesis failed: {e}")


def _wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as wf:
        return wf.getnframes() / float(wf.getframerate())


def _concat_wavs(paths: list[Path], out_path: Path) -> None:
    concat_file = out_path.parent / "concat.txt"

    with open(concat_file, "w") as f:
        for p in paths:
            f.write(f"file '{ffconcat_path(p)}'\n")

    subprocess.run([
        "ffmpeg",
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_file),
        "-ar", str(config.AUDIO_SAMPLE_RATE),
        str(out_path)
    ], check=True)


def run(
    script: dict,
    work_dir: Path,
    video_spec: VideoSpec | dict | str | None = None,
) -> dict:
    if video_spec is not None:
        ensure_video_spec(video_spec)
    beats = script.get("beats")
    if not beats:
        raise Stage2Error("No beats found")

    audio_dir = work_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    outputs = []
    durations = []

    for i, beat in enumerate(beats):
        out = audio_dir / f"beat_{i}.wav"
        _synthesize_beat(beat["text"], out)
        outputs.append(out)
        durations.append(_wav_duration(out))

    final_audio = audio_dir / "final.wav"
    _concat_wavs(outputs, final_audio)

    return {
        "audio_path": str(final_audio),
        "beat_audio": [str(p) for p in outputs],
        "beat_durations": durations,
        "engine": "macos-say"
    }
