from pipeline.stages import (
    stage1_script,
    stage2_voice,
    stage3_visuals,
    stage4_assembly,
    stage5_format,
    stage6_output,
)
from pathlib import Path
import tempfile
import time


class PipelineError(Exception):
    def __init__(self, stage: str, original: Exception):
        self.stage = stage
        self.original = original
        super().__init__(f"[{stage}] {original}")


def run(topic: str, output_dir: Path | None = None) -> dict:
    t_start = time.time()
    warnings = []

    with tempfile.TemporaryDirectory(prefix="afos_run_") as tmp:
        work_dir = Path(tmp)

        # -------------------
        # Stage 1
        # -------------------
        script = stage1_script.run(topic)
        if script.get("source") == "local_template":
            warnings.append("Stage 1 fallback used")

        # -------------------
        # Stage 2
        # -------------------
        voice = stage2_voice.run(script, work_dir)

        # -------------------
        # Stage 3
        # -------------------
        visuals = stage3_visuals.run(script, voice["beat_durations"], work_dir)

        # -------------------
        # Stage 4
        # -------------------
        assembly = stage4_assembly.run(
            visuals["clip_paths"],
            voice["audio_path"],
            work_dir
        )

        # -------------------
        # Stage 5
        # -------------------
        formatted = stage5_format.run(
            assembly.get("assembled_path") or assembly.get("video_path"),
            work_dir
        )

        # -------------------
        # Stage 6 (FIXED INPUT)
        # -------------------
        result = stage6_output.run(
            {
                "video_path": formatted.get("formatted_path") or assembly.get("assembled_path"),
                "manifest_path": formatted.get("manifest_path"),
            },
            work_dir
        )

    return {
        "video_path": result.get("video_path"),
        "manifest_path": result.get("manifest_path"),
        "total_runtime_seconds": round(time.time() - t_start, 2),
        "warnings": warnings,
    }