from pathlib import Path
import subprocess


def fetch_football_clips(query: str, out_dir: Path, max_videos: int = 5) -> list[Path]:
    """
    Downloads MULTIPLE football clips (TikTok-style source material).
    """

    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "yt-dlp",
        f"ytsearch{max_videos}:{query}",
        "-f", "mp4",
        "-o", str(out_dir / "%(title)s.%(ext)s")
    ]

    subprocess.run(cmd, check=True)

    return sorted(out_dir.glob("*.mp4"), key=lambda x: x.stat().st_mtime, reverse=True)