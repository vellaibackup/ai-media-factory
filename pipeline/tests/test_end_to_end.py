import subprocess
from pathlib import Path
from pipeline.orchestrator import run


def test_full_pipeline_produces_valid_video(tmp_path):
    result = run("Test end to end topic", output_dir=tmp_path)

    video_path = Path(result["final_video_path"])
    manifest_path = Path(result["manifest_path"])
    assert video_path.exists()
    assert manifest_path.exists()

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=width,height,codec_type",
         "-of", "csv=p=0", str(video_path)],
        capture_output=True, text=True,
    )
    assert probe.returncode == 0
    assert "1080" in probe.stdout and "1920" in probe.stdout
    assert "video" in probe.stdout and "audio" in probe.stdout
