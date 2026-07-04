import subprocess
from pathlib import Path


def cut_highlight_clip(input_video: str, output_path: str, start: float, duration: float = 8):

    """
    Cuts a small highlight segment from a football video.
    """

    subprocess.run([
        "ffmpeg",
        "-y",
        "-ss", str(start),
        "-i", input_video,
        "-t", str(duration),
        "-vf", "scale=1080:1920",  # Shorts format
        "-r", "30",
        "-an",
        output_path
    ], check=True)

    return output_path