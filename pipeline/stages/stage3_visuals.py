from pathlib import Path
import subprocess

from pipeline.core.video_spec import VideoSpec, ensure_video_spec
from pipeline.core.media_discovery import CandidateClip
from pipeline.stages.media_provider import MediaCandidate
from pipeline.stages.media_provider import YouTubeFootballMediaProvider
from urllib.parse import parse_qs, urlparse


class Stage3Error(Exception):
    pass


def run(
    script: dict,
    beat_durations: list[float],
    work_dir: Path,
    viral_plan: dict | None = None,
    video_spec: VideoSpec | dict | str | None = None,
    media_candidate: CandidateClip | None = None,
):
    spec = ensure_video_spec(video_spec or script.get("topic", "football"))

    beats = script.get("beats")
    if not beats:
        raise Stage3Error("No beats found")

    highlights_dir = work_dir / "highlights"
    visuals_dir = work_dir / "visuals"
    visuals_dir.mkdir(parents=True, exist_ok=True)

    highlights_dir.mkdir(parents=True, exist_ok=True)

    # ----------------------------
    # FIX 1: ENSURE SOURCE VIDEO EXISTS
    # ----------------------------
    provider = YouTubeFootballMediaProvider()
    base_video = next(iter(sorted(highlights_dir.glob("*.mp4"))), None)

    if not base_video:
        try:
            if media_candidate is not None:
                video_id = parse_qs(
                    urlparse(media_candidate.url).query
                ).get("v", [""])[0]
                if media_candidate.source != "youtube" or not video_id:
                    raise Stage3Error("Unsupported media candidate source or URL")
                ranked = [
                    MediaCandidate(
                        video_id=video_id,
                        title=media_candidate.title,
                        rank=0,
                        query=spec.topic,
                    )
                ]
            else:
                query = f"{spec.topic} football highlights"
                candidates = provider.search(query)
                ranked = sorted(
                    candidates,
                    key=lambda candidate: (
                        -provider.score(candidate),
                        candidate.video_id,
                    ),
                )
            if ranked:
                base_video = provider.download(
                    ranked[0],
                    highlights_dir / "source.mp4",
                )
        except Exception as exc:
            if media_candidate is not None:
                raise Stage3Error(
                    f"Selected media candidate could not be loaded: {exc}"
                ) from exc
            print(f"⚠️ Football media provider unavailable: {exc}")

    if not base_video:
        print("⚠️ No source video found — creating fallback video...")

        base_video = highlights_dir / "fallback.mp4"

        subprocess.run([
            "ffmpeg",
            "-y",
            "-f", "lavfi",
            "-i", "testsrc=duration=20:size=640x360:rate=30",
            str(base_video)
        ], check=True)

    # ----------------------------
    # BUILD VISUAL CLIPS
    # ----------------------------
    outputs = []

    start_seconds = 0.0
    for i, duration in enumerate(beat_durations):

        out_path = visuals_dir / f"clip_{i}.mp4"
        clip_start = start_seconds
        if (
            media_candidate is not None
            and media_candidate.duration > 0
            and clip_start + duration > media_candidate.duration
        ):
            clip_start = 0.0
        provider.trim(
            base_video,
            out_path,
            clip_start,
            duration,
        )

        outputs.append(str(out_path))
        start_seconds = round(clip_start + duration, 3)

    return {
        "clip_paths": outputs,
        "viral_plan": viral_plan,
    }
