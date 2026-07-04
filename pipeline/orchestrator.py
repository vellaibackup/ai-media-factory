from pipeline.stages import (
    stage1_script,
    stage2_voice,
    stage3_visuals,
    stage4_assembly,
    stage5_format,
    stage6_output,
)
from pathlib import Path
from datetime import datetime
import shutil
import tempfile
import time

from pipeline.core.content_strategy import ContentStrategy
from pipeline.path_utils import canonical_path, output_path, path_from, write_concat_file
from pipeline.stages.stage2_5_viral_intelligence import run as viral_intelligence_run
from pipeline.core.video_spec import VideoSpec, ensure_video_spec


class PipelineError(Exception):
    def __init__(self, stage: str, original: Exception):
        self.stage = stage
        self.original = original
        super().__init__(f"[{stage}] {original}")


def run(
    video_spec: VideoSpec | dict | str,
    output_dir: Path | None = None,
) -> dict:
    spec = ensure_video_spec(video_spec)
    t_start = time.time()
    warnings = []

    with tempfile.TemporaryDirectory(prefix="afos_run_") as tmp:
        work_dir = canonical_path(tmp)

        for directory in (
            path_from(work_dir, "assembly"),
            output_path(work_dir, "visuals"),
        ):
            directory.mkdir(parents=True, exist_ok=True)

        # -------------------
        # Stage 1
        # -------------------
        script_data = stage1_script.run(spec)
        if script_data.get("source") == "local_template":
            warnings.append("Stage 1 fallback used")

        # -------------------
        # Stage 2
        # -------------------
        voice = stage2_voice.run(script_data, work_dir, spec)

        try:
            viral_plan = viral_intelligence_run(script_data, spec)
        except Exception:
            viral_plan = None

        # -------------------
        # Stage 3
        # -------------------
        visuals = stage3_visuals.run(
            script_data,
            voice["beat_durations"],
            work_dir,
            viral_plan=viral_plan,
            video_spec=spec,
        )

        # -------------------
        # Stage 4
        # -------------------
        concat_file = write_concat_file(
            output_path(work_dir, "visuals", "video_concat_list.txt"),
            visuals["clip_paths"],
        )
        assembly = stage4_assembly.run(
            concat_file,
            voice["audio_path"],
            work_dir,
            spec,
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


def run_batch(strategy: ContentStrategy) -> dict:
    if not isinstance(strategy, ContentStrategy):
        raise TypeError("strategy must be a ContentStrategy")

    specs = strategy.generate_video_specs()
    batch_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    batch_dir = output_path(
        Path.cwd(),
        "batches",
        batch_id,
        strategy.niche,
    )
    video_paths = []

    for index, spec in enumerate(specs, start=1):
        result = run(spec)
        source = Path(result["video_path"])
        if not source.is_file():
            raise PipelineError("batch", FileNotFoundError(source))

        video_dir = path_from(batch_dir, f"video_{index}")
        video_dir.mkdir(parents=True, exist_ok=True)
        destination = path_from(video_dir, "final.mp4")
        shutil.copy2(source, destination)
        video_paths.append(str(destination))

    return {
        "batch_id": batch_id,
        "batch_dir": str(batch_dir),
        "video_paths": video_paths,
        "video_specs": specs,
        "variation_summary": {
            "varied_fields": ["topic", "hook_type", "emotional_curve"],
            "fixed_fields": [
                "duration_seconds",
                "platform",
                "beat_count",
            ],
            "monetisation_goal": strategy.monetisation_goal,
        },
    }
