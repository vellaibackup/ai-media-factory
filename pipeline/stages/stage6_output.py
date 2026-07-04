from pathlib import Path
import shutil
import time


def run(result, work_dir: Path, *args, **kwargs):
    """
    FINAL OUTPUT CONTRACT (LOCKED)
    Always returns video_path + manifest_path
    """

    base_output = Path("output/football")

    run_id = time.strftime("run_%Y%m%d_%H%M%S")
    run_dir = base_output / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # -----------------------------
    # FIND VIDEO SAFELY
    # -----------------------------
    video_path = None

    if isinstance(result, dict):
        video_path = (
            result.get("video_path")
            or result.get("assembled_path")
            or result.get("formatted_path")
        )

    if isinstance(video_path, str) and Path(video_path).exists():
        shutil.copy(video_path, run_dir / "video.mp4")

    # -----------------------------
    # FIND MANIFEST SAFELY
    # -----------------------------
    manifest_path = None

    if isinstance(result, dict):
        manifest_path = result.get("manifest_path")

    if isinstance(manifest_path, str) and Path(manifest_path).exists():
        shutil.copy(manifest_path, run_dir / "manifest.json")

    # -----------------------------
    # ALWAYS RETURN SAME STRUCTURE
    # -----------------------------
    return {
        "video_path": str(run_dir / "video.mp4"),
        "manifest_path": str(run_dir / "manifest.json"),
    }