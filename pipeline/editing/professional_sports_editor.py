"""Deterministic footage quality ranking for the professional sports editor."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import subprocess
from typing import Any, Callable, Iterable

from pipeline.core import bfi_config
from pipeline.core.content_format_gate import classify_low_value_format
from pipeline.core.media_discovery import CandidateClip


@dataclass(frozen=True)
class CandidateQuality:
    candidate: CandidateClip
    score: float
    resolution: str
    resolution_score: float
    upload_quality_score: float
    aspect_ratio_score: float
    camera_angle_score: float
    replay_score: float
    confidence_score: float
    reason: str

    def report(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("candidate")
        return data


def youtube_metadata(url: str) -> dict[str, Any]:
    path = Path(url)
    if path.is_file():
        return _local_video_metadata(path)
    result = subprocess.run(
        ["yt-dlp", "--dump-single-json", "--skip-download", "--no-warnings", url],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[-400:] or "yt-dlp metadata failed")
    return json.loads(result.stdout)


def _local_video_metadata(path: Path) -> dict[str, Any]:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_streams", "-show_format",
            "-of", "json", str(path),
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[-400:] or "ffprobe metadata failed")
    payload = json.loads(result.stdout)
    video_stream = next(
        (item for item in payload.get("streams", []) if item.get("codec_type") == "video"),
        {},
    )
    fps = _parse_rate(str(video_stream.get("avg_frame_rate") or "0/1"))
    bitrate = float(video_stream.get("bit_rate") or payload.get("format", {}).get("bit_rate") or 0) / 1000
    sidecar = path.with_suffix(".json")
    text_metadata = {}
    if sidecar.is_file():
        try:
            loaded = json.loads(sidecar.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                text_metadata = loaded
        except (OSError, json.JSONDecodeError):
            text_metadata = {}
    return {
        "width": int(video_stream.get("width") or 0),
        "height": int(video_stream.get("height") or 0),
        "fps": fps,
        "tbr": bitrate,
        **text_metadata,
    }


def _parse_rate(value: str) -> float:
    numerator, separator, denominator = value.partition("/")
    try:
        top = float(numerator)
        bottom = float(denominator) if separator else 1.0
    except ValueError:
        return 0.0
    return top / bottom if bottom else 0.0


def _dimensions(metadata: dict[str, Any]) -> tuple[int, int]:
    width = int(metadata.get("width") or 0)
    height = int(metadata.get("height") or 0)
    if width and height:
        return width, height
    formats = metadata.get("formats") or []
    dimensions = [
        (int(item.get("width") or 0), int(item.get("height") or 0))
        for item in formats
        if item.get("vcodec") != "none"
    ]
    return max(dimensions, key=lambda value: value[0] * value[1], default=(0, 0))


def _normalised_text(candidate: CandidateClip, metadata: dict[str, Any]) -> str:
    values = [
        candidate.title,
        candidate.description,
        str(metadata.get("title") or ""),
        str(metadata.get("description") or ""),
        " ".join(str(item) for item in metadata.get("tags") or []),
    ]
    return " ".join(values).casefold()


def score_candidate(
    candidate: CandidateClip,
    metadata_fetcher: Callable[[str], dict[str, Any]] = youtube_metadata,
) -> CandidateQuality:
    try:
        metadata = metadata_fetcher(candidate.url)
        metadata_error = ""
    except Exception as exc:
        metadata = {}
        metadata_error = str(exc)

    width, height = _dimensions(metadata)
    vertical_resolution = max(width, height)
    if vertical_resolution >= 1080:
        resolution_score = 30.0
    elif vertical_resolution >= 720:
        resolution_score = 24.0
    elif vertical_resolution >= 480:
        resolution_score = 12.0
    else:
        resolution_score = 4.0 if vertical_resolution else 0.0

    fps = float(metadata.get("fps") or 0)
    bitrate = float(metadata.get("tbr") or 0)
    upload_quality_score = min(14.0, bitrate / 350.0) + min(6.0, fps / 60.0 * 6.0)

    ratio = width / height if height else 0.0
    target_ratio = 9 / 16
    aspect_ratio_score = max(0.0, 10.0 - abs(ratio - target_ratio) * 8.0)

    text = _normalised_text(candidate, metadata)
    action_terms = (
        "close-up",
        "close up",
        "close angle",
        "pitchside",
        "goal",
        "save",
        "penalty",
        "celebration",
        "reaction",
    )
    stable_terms = ("stable", "broadcast", "official", "clear", "hd", "4k")
    poor_angle_terms = ("distant", "far angle", "stands", "nosebleed", "wide shot")
    camera_angle_score = min(
        15.0,
        4.0
        + sum(2.0 for term in action_terms if term in text)
        + sum(1.5 for term in stable_terms if term in text),
    )
    camera_angle_score -= sum(3.0 for term in poor_angle_terms if term in text)
    camera_angle_score = max(0.0, camera_angle_score)

    replay_terms = ("replay", "slow motion", "slow-mo", "highlights", "angle")
    replay_score = min(15.0, sum(5.0 for term in replay_terms if term in text))
    confidence_score = 10.0 * candidate.confidence
    penalty_terms = {
        "blurry": 10.0,
        "blurred": 10.0,
        "low quality": 8.0,
        "compressed": 8.0,
        "pixelated": 8.0,
        "watermark": 6.0,
        "watermarked": 6.0,
        "border": 6.0,
        "borders": 6.0,
        "black bars": 6.0,
    }
    quality_penalty = sum(value for term, value in penalty_terms.items() if term in text)

    # Sprint D: a deterministic content-format gate, applied here at final
    # ranking. Motion score and technical quality (resolution/bitrate/fps)
    # cannot tell a genuine highlight apart from a prediction/preview/
    # studio/breakdown/recap/discussion/meme/analysis clip with moving
    # graphics -- so this format check is a separate, strong penalty large
    # enough to reliably outrank such content against genuine footage of
    # similar technical quality, regardless of official-channel status.
    low_value_format = classify_low_value_format(candidate.title, candidate.description)
    format_penalty = bfi_config.LOW_VALUE_FORMAT_PENALTY if low_value_format else 0.0

    score = round(
        max(
            0.0,
            resolution_score
            + upload_quality_score
            + aspect_ratio_score
            + camera_angle_score
            + replay_score
            + confidence_score
            - quality_penalty
            - format_penalty,
        ),
        2,
    )
    reasons = [
        f"resolution={width}x{height}" if width and height else "resolution unavailable",
        f"fps={fps:g}",
        f"bitrate={bitrate:g}kbps",
        f"confidence={candidate.confidence:.2f}",
    ]
    if quality_penalty:
        reasons.append(f"quality_penalty={quality_penalty:g}")
    if low_value_format:
        reasons.append(f"low_value_format={low_value_format} (penalty={format_penalty:g})")
    if metadata_error:
        reasons.append(f"metadata error: {metadata_error}")
    return CandidateQuality(
        candidate=candidate,
        score=score,
        resolution=f"{width}x{height}" if width and height else "unknown",
        resolution_score=round(resolution_score, 2),
        upload_quality_score=round(upload_quality_score, 2),
        aspect_ratio_score=round(aspect_ratio_score, 2),
        camera_angle_score=round(camera_angle_score, 2),
        replay_score=round(replay_score, 2),
        confidence_score=round(confidence_score, 2),
        reason=", ".join(reasons),
    )


def rank_candidates(
    candidates: Iterable[CandidateClip],
    metadata_fetcher: Callable[[str], dict[str, Any]] = youtube_metadata,
    verification_scores: dict[str, float] | None = None,
    motion_scores: dict[str, float] | None = None,
) -> list[CandidateQuality]:
    verification_scores = verification_scores or {}
    motion_scores = motion_scores or {}
    scored = [score_candidate(candidate, metadata_fetcher) for candidate in candidates]
    return sorted(
        scored,
        key=lambda item: (
            -verification_scores.get(item.candidate.url, 0.0),
            -item.candidate.relevance_score,
            -motion_scores.get(item.candidate.url, 0.0),
            -item.score,
            -item.candidate.confidence,
            item.candidate.url,
        ),
    )


__all__ = ["CandidateQuality", "rank_candidates", "score_candidate", "youtube_metadata"]
