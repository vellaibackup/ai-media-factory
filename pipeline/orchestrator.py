from pipeline.stages import (
    stage1_script,
    stage2_voice,
    stage3_visuals,
    stage4_assembly,
    stage5_format,
    stage6_output,
)
from pipeline import config
from pathlib import Path
from datetime import datetime
from dataclasses import asdict, replace
import shutil
import tempfile
import time

from pipeline.core import bfi_config
from pipeline.core.content_strategy import ContentStrategy
from pipeline.core.football_intelligence import FootballIntelligence
from pipeline.core.media_discovery import CandidateClip, MediaDiscovery
from pipeline.path_utils import canonical_path, output_path, path_from, write_concat_file
from pipeline.stages.stage2_5_viral_intelligence import run as viral_intelligence_run
from pipeline.core.video_spec import VideoSpec, ensure_video_spec
from pipeline.editing.professional_sports_editor import rank_candidates
from pipeline.editing.media_usability import assess_candidates, filter_candidates_by_duration
from pipeline.editing.content_freshness import (
    SourceVideoHistory,
    filter_fresh_candidates,
    youtube_video_id,
)


class PipelineError(Exception):
    def __init__(self, stage: str, original: Exception):
        self.stage = stage
        self.original = original
        super().__init__(f"[{stage}] {original}")


def run(
    video_spec: VideoSpec | dict | str,
    output_dir: Path | None = None,
    media_candidate: CandidateClip | None = None,
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
            media_candidate=media_candidate,
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
        # Saves the video locally, writes manifest.json, and advances the
        # workflow state to "pending_review". This is where the pipeline
        # stops: nothing past this point runs without an explicit human
        # approve() + publish() action (see pipeline/core/workflow.py and
        # pipeline/publish.py). There is no publish flag here on purpose.
        # -------------------
        manifest_data = {
            "topic": spec.topic,
            "pipeline_version": "mvp-day1",
            "script_source": script_data.get("source"),
            "beats": script_data.get("beats"),
            "voice_engine": voice.get("engine"),
            "video_format": f"{config.VIDEO_WIDTH}x{config.VIDEO_HEIGHT}",
            "total_runtime_seconds": round(time.time() - t_start, 2),
            "warnings": warnings,
            "final_duration": visuals.get("final_duration"),
            "clip_timeline": visuals.get("clip_timeline", []),
            "narration": {
                "engine": voice.get("engine"),
                "voice": voice.get("voice"),
                "language": voice.get("language"),
                "language_verified": voice.get("language_verified", False),
            },
            "youtube_url": None,
            "video_id": None,
        }
        result = stage6_output.run(
            {
                "video_path": formatted.get("formatted_path") or assembly.get("assembled_path"),
            },
            work_dir,
            manifest_data=manifest_data,
        )

    pipeline_result = {
        "video_path": result.get("video_path"),
        "manifest_path": result.get("manifest_path"),
        "status": result.get("status"),
        "total_runtime_seconds": round(time.time() - t_start, 2),
        "warnings": warnings,
        "final_duration": visuals.get("final_duration"),
        "clip_timeline": visuals.get("clip_timeline", []),
        "narration": {
            "engine": voice.get("engine"),
            "voice": voice.get("voice"),
            "language": voice.get("language"),
            "language_verified": voice.get("language_verified", False),
        },
    }

    return pipeline_result


def run_football_mvp(source_history: SourceVideoHistory | None = None) -> dict:
    # Persisted timing evidence (Sprint C.1): wall-clock time for the stages
    # that matter for the 5-minute performance target. Included in the
    # returned result dict on every path, so it's captured whenever this
    # pipeline runs (CLI --mvp prints the full result as JSON).
    t_total_start = time.time()
    stage_timings: dict[str, float] = {}

    stories = FootballIntelligence().discover()
    if not stories:
        raise PipelineError("football_intelligence", RuntimeError("No stories found"))
    story = stories[0]

    media_discovery = MediaDiscovery()
    t = time.time()
    candidates = media_discovery.discover(story)
    stage_timings["discovery_seconds"] = round(time.time() - t, 3)
    discovery_rejections = media_discovery.diagnostics.get("rejected_candidates", [])
    if not candidates:
        return {
            "verification_score": 0.0,
            "accepted_candidate": None,
            "rejected_candidates": discovery_rejections,
            "reason": media_discovery.diagnostics.get(
                "reason", "No candidate videos passed event verification."
            ),
            "upload_status": "not_published",
            "youtube_url": None,
            "video_id": None,
            "stage_timings": {**stage_timings, "total_seconds": round(time.time() - t_total_start, 3)},
        }
    external_candidates = [
        item
        for item in candidates
        if "generated by afos media factory" not in item.description.casefold()
    ]
    if not external_candidates:
        best = external_candidates[0] if external_candidates else None
        quality = (
            f"best score={best.relevance_score}, confidence={best.confidence}"
            if best is not None
            else "no external candidates"
        )
        raise PipelineError(
            "media_discovery",
            RuntimeError(
                "No sufficiently relevant media candidate found "
                f"({quality})"
            ),
        )
    source_history = source_history or SourceVideoHistory()
    fresh_candidates, freshness_rejections = filter_fresh_candidates(
        external_candidates,
        source_history,
    )
    freshness_reports = [item.report() for item in freshness_rejections]
    if not fresh_candidates:
        return {
            "verification_score": 0.0,
            "matched_entities": {},
            "rejected_candidates": discovery_rejections + freshness_reports,
            "accepted_candidate": None,
            "reason": "All verified candidate footage was used in the last 30 published Shorts; publishing skipped.",
            "upload_status": "not_published",
            "youtube_url": None,
            "video_id": None,
            "stage_timings": {**stage_timings, "total_seconds": round(time.time() - t_total_start, 3)},
        }
    # Verification already happened once, inside media_discovery.discover()
    # (BFI Phase 1 wiring) -- reuse those results instead of re-verifying
    # candidates that have already passed. See MediaDiscovery.verification_results.
    accepted_verifications = [
        media_discovery.verification_results[item.url]
        for item in fresh_candidates
        if item.url in media_discovery.verification_results
    ]
    if not accepted_verifications:
        return {
            "verification_score": 0.0,
            "matched_entities": {},
            "rejected_candidates": discovery_rejections + freshness_reports,
            "accepted_candidate": None,
            "reason": "All candidate footage failed story verification; editing and publishing skipped.",
            "upload_status": "not_published",
            "youtube_url": None,
            "video_id": None,
            "stage_timings": {**stage_timings, "total_seconds": round(time.time() - t_total_start, 3)},
        }

    # Conservative duration gate, before any usability download: reject
    # candidates too short to satisfy the retention editor's no-repeated-
    # footage rule, and obvious full-match/full-broadcast uploads, using
    # duration metadata already fetched from the YouTube Data API at
    # search time -- no download required to apply this filter.
    duration_filtered, duration_rejections = filter_candidates_by_duration(
        (item.candidate for item in accepted_verifications),
        min_duration=story.recommended_duration,
    )
    duration_reports = [item.report() for item in duration_rejections]
    if not duration_filtered:
        return {
            "verification_score": max(item.score for item in accepted_verifications),
            "matched_entities": accepted_verifications[0].matched_entities,
            "rejected_candidates": discovery_rejections + freshness_reports + duration_reports,
            "accepted_candidate": None,
            "reason": "All verified candidates were filtered out by duration (too short or full-match length); publishing skipped.",
            "upload_status": "not_published",
            "youtube_url": None,
            "video_id": None,
            "stage_timings": {**stage_timings, "total_seconds": round(time.time() - t_total_start, 3)},
        }

    # Rank first using signals already known from search/verification (no
    # download needed), then only usability-check the top-ranked shortlist --
    # not every verified candidate. assess_candidates() itself stops early
    # once enough usable candidates are found.
    verification_score_by_url = {item.candidate.url: item.score for item in accepted_verifications}
    cheap_ranked = sorted(
        duration_filtered,
        key=lambda item: (
            -verification_score_by_url.get(item.url, 0.0),
            -item.relevance_score,
            -item.confidence,
            item.url,
        ),
    )
    top_k = cheap_ranked[: bfi_config.USABILITY_TOP_K]
    skipped_by_topk = [
        {
            "title": item.title,
            "url": item.url,
            "reason": "not in top-ranked shortlist by verification/relevance; usability check skipped",
        }
        for item in cheap_ranked[bfi_config.USABILITY_TOP_K :]
    ]

    usability_dir = Path(tempfile.mkdtemp(prefix="afos_usability_"))
    try:
        t = time.time()
        usability_results = assess_candidates(
            top_k,
            usability_dir,
            stop_after_usable=bfi_config.USABILITY_STOP_AFTER_USABLE_COUNT,
        )
        stage_timings["usability_seconds"] = round(time.time() - t, 3)
        usable_results = [item for item in usability_results if item.usable]
        rejected_usability = [item.report() for item in usability_results if not item.usable]
        if not usable_results:
            return {
                "verification_score": max(item.score for item in accepted_verifications),
                "matched_entities": accepted_verifications[0].matched_entities,
                "accepted_candidate": None,
                "motion_usability_score": max(
                    (item.score for item in usability_results), default=0.0
                ),
                "rejected_candidates": (
                    discovery_rejections
                    + freshness_reports
                    + duration_reports
                    + rejected_usability
                    + skipped_by_topk
                ),
                "reason": "Verified candidates failed decoded-motion usability checks; publishing skipped.",
                "narration": {
                    "language": config.FOOTBALL_TTS_LANGUAGE,
                    "voice": config.FOOTBALL_TTS_VOICE,
                    "language_verified": False,
                    "status": "not_generated",
                },
                "upload_status": "not_published",
                "youtube_url": None,
                "video_id": None,
                "stage_timings": {**stage_timings, "total_seconds": round(time.time() - t_total_start, 3)},
            }
        usable_by_url = {item.candidate.url: item for item in usable_results}
        motion_score_by_url = {
            item.candidate.url: item.score for item in usable_results
        }
        # Real per-video quality probing (resolution/fps/bitrate via yt-dlp)
        # now only runs on this small usable shortlist (<= a few candidates),
        # not the whole verified pool -- rank_candidates' own default
        # metadata_fetcher (youtube_metadata) is used deliberately here.
        t = time.time()
        ranked_quality = rank_candidates(
            (item.candidate for item in usable_results),
            verification_scores=verification_score_by_url,
            motion_scores=motion_score_by_url,
        )
        stage_timings["ranking_seconds"] = round(time.time() - t, 3)
        chosen_quality = ranked_quality[0]
        candidate = chosen_quality.candidate
        chosen_usability = usable_by_url[candidate.url]
        accepted_verification = next(
            item for item in accepted_verifications if item.candidate == candidate
        )

        beat_count = max(5, (story.recommended_duration - 1 + 3) // 4)
        spec = VideoSpec(
            topic=story.title,
            duration_seconds=story.recommended_duration,
            platform="youtube_shorts",
            style=story.recommended_video_type,
            hook_type="high-stakes",
            emotional_curve=[
                "curiosity",
                "anticipation",
                "tension",
                "reveal",
                "resolution",
            ],
            beat_count=beat_count,
            avg_clip_length=(story.recommended_duration - 1) / beat_count,
            max_clip_length=4.0,
            cta_type="comment",
        )
        # Reuse the file already downloaded for the usability check instead
        # of fetching the same source video again for rendering.
        render_candidate = candidate
        if candidate.source != "local" and chosen_usability.local_path is not None:
            render_candidate = replace(
                candidate, source="local", url=str(chosen_usability.local_path)
            )
        t = time.time()
        result = run(spec, media_candidate=render_candidate)
        stage_timings["render_seconds"] = round(time.time() - t, 3)
        source_video_id = youtube_video_id(candidate.url)
        # NOTE: rendering no longer publishes automatically (Human Approval
        # Workflow, Sprint A). source_history is a freshness gate keyed on
        # *published* footage, so recording it here would be premature -- it
        # must move to the explicit publish action (pipeline/publish.py) once
        # that action becomes football-source-aware. Tracked as a Sprint A
        # follow-up; out of scope for this sprint (media-discovery territory).
        return {
            "selected_story": asdict(story),
            "selected_media_candidate": asdict(candidate),
            "verification_score": accepted_verification.score,
            "matched_entities": accepted_verification.matched_entities,
            "accepted_candidate": accepted_verification.report(),
            "verification_reason": accepted_verification.reason,
            "motion_usability": chosen_usability.report(),
            "chosen_candidate_score": chosen_quality.report(),
            "source_video_id": source_video_id,
            "rejected_candidates": (
                discovery_rejections
                + freshness_reports
                + duration_reports
                + rejected_usability
                + skipped_by_topk
                + [
                    {
                        "title": item.candidate.title,
                        "url": item.candidate.url,
                        "score": item.score,
                        "reason": f"lower quality score than selected candidate; {item.reason}",
                    }
                    for item in ranked_quality[1:]
                ]
            ),
            "final_duration": result.get("final_duration"),
            "clip_timeline": result.get("clip_timeline", []),
            "output_video_path": result.get("video_path"),
            "manifest_path": result.get("manifest_path"),
            "status": result.get("status"),
            "narration": result.get("narration"),
            "stage_timings": {**stage_timings, "total_seconds": round(time.time() - t_total_start, 3)},
        }
    finally:
        shutil.rmtree(usability_dir, ignore_errors=True)


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
