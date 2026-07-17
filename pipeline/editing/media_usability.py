"""Decoded-frame motion gate for football footage."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Iterable
import subprocess

from pipeline.core import bfi_config
from pipeline.core.media_discovery import CandidateClip
from pipeline.stages.media_provider import MediaCandidate, YouTubeFootballMediaProvider


_YDIF_RE = re.compile(r"lavfi\.signalstats\.YDIF=([0-9.]+)")


@dataclass(frozen=True)
class UsabilityResult:
    candidate: CandidateClip
    score: float
    usable: bool
    average_motion: float
    active_frame_ratio: float
    still_frame_ratio: float
    reason: str
    local_path: Path | None = None

    def report(self) -> dict:
        return {
            "title": self.candidate.title,
            "url": self.candidate.url,
            "motion_usability_score": self.score,
            "average_motion": self.average_motion,
            "active_frame_ratio": self.active_frame_ratio,
            "still_frame_ratio": self.still_frame_ratio,
            "usable": self.usable,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class DurationRejection:
    title: str
    url: str
    duration: int
    reason: str

    def report(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "duration": self.duration,
            "reason": self.reason,
        }


def filter_candidates_by_duration(
    candidates: Iterable[CandidateClip],
    min_duration: float,
    max_duration: float = bfi_config.MAX_CANDIDATE_DURATION_SECONDS,
) -> tuple[list[CandidateClip], list[DurationRejection]]:
    """Reject candidates whose known duration rules them out before any
    usability download: too short to ever satisfy the retention editor's
    no-repeated-footage rule, or implausibly long (a full match/broadcast
    rather than a highlight). A candidate with unknown duration (0 or
    missing) is passed through rather than penalised -- this is a
    conservative pre-download gate, not a replacement for the usability
    check itself.
    """
    kept: list[CandidateClip] = []
    rejected: list[DurationRejection] = []
    for candidate in candidates:
        duration = candidate.duration
        if duration <= 0:
            kept.append(candidate)
        elif duration < min_duration:
            rejected.append(
                DurationRejection(
                    candidate.title,
                    candidate.url,
                    duration,
                    f"rejected: candidate duration {duration}s is shorter than the "
                    f"required output duration {min_duration:.0f}s",
                )
            )
        elif duration > max_duration:
            rejected.append(
                DurationRejection(
                    candidate.title,
                    candidate.url,
                    duration,
                    f"rejected: candidate duration {duration}s exceeds the maximum "
                    f"allowed {max_duration:.0f}s (likely a full match/broadcast, not a highlight)",
                )
            )
        else:
            kept.append(candidate)
    return kept, rejected


def analyze_video(candidate: CandidateClip, video_path: Path) -> UsabilityResult:
    result = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "info", "-i", str(video_path),
            "-t", "30", "-vf", "fps=2,scale=160:-2,signalstats,metadata=print",
            "-an", "-f", "null", "-",
        ],
        capture_output=True,
        text=True,
        timeout=45,
    )
    values = [float(value) for value in _YDIF_RE.findall(result.stderr)][1:]
    if result.returncode != 0 or not values:
        reason = result.stderr.strip()[-300:] or "no decoded motion samples"
        return UsabilityResult(candidate, 0.0, False, 0.0, 0.0, 1.0, reason, local_path=video_path)

    average_motion = sum(values) / len(values)
    active_ratio = sum(value >= 1.0 for value in values) / len(values)
    still_ratio = sum(value < 0.5 for value in values) / len(values)
    score = round(min(100.0, average_motion * 10.0) * 0.5 + active_ratio * 50.0, 2)
    usable = average_motion >= 1.5 and active_ratio >= 0.5 and still_ratio <= 0.6
    reason = (
        "accepted: sustained decoded-frame motion consistent with moving footage"
        if usable
        else "rejected: slideshow, image-only, zoom-only, or predominantly still footage"
    )
    return UsabilityResult(
        candidate,
        score,
        usable,
        round(average_motion, 3),
        round(active_ratio, 3),
        round(still_ratio, 3),
        reason,
        local_path=video_path,
    )


def assess_candidates(
    candidates: Iterable[CandidateClip],
    work_dir: Path,
    stop_after_usable: int | None = None,
) -> list[UsabilityResult]:
    """Download + motion-check candidates in order, stopping early once
    `stop_after_usable` usable candidates are found. Defaults to None
    (process every candidate), preserving prior behaviour for any caller
    that doesn't opt into early-exit.

    Deliberately no single-candidate "excellent score" short-circuit: motion
    score measures decoded-frame movement, not broadcast-footage editorial
    quality, so a prediction/studio/reaction-style clip with moving graphics
    can score as high as genuine match footage. Stopping on one candidate's
    score alone let such a clip win by default before a better candidate in
    the shortlist was ever assessed (Sprint C.1). Requiring at least
    `stop_after_usable` (>= 2) usable candidates -- or exhausting the
    shortlist -- ensures ranking always has more than one option to compare,
    when more than one is available.
    """
    provider = YouTubeFootballMediaProvider()
    results = []
    usable_count = 0
    for index, candidate in enumerate(candidates):
        destination = work_dir / f"candidate_{index}.mp4"
        try:
            if candidate.source == "local":
                result = analyze_video(candidate, Path(candidate.url))
            else:
                video_id = candidate.url.partition("v=")[2].partition("&")[0]
                provider.download(
                    MediaCandidate(video_id, candidate.title, index, "usability gate"),
                    destination,
                )
                result = analyze_video(candidate, destination)
        except Exception as exc:
            result = UsabilityResult(
                candidate, 0.0, False, 0.0, 0.0, 1.0,
                f"rejected: candidate could not be decoded for motion analysis: {exc}",
                local_path=Path(candidate.url) if candidate.source == "local" else destination,
            )
        results.append(result)
        if result.usable:
            usable_count += 1
            if stop_after_usable is not None and usable_count >= stop_after_usable:
                break
    return sorted(results, key=lambda item: (-item.score, item.candidate.url))


__all__ = [
    "DurationRejection",
    "UsabilityResult",
    "analyze_video",
    "assess_candidates",
    "filter_candidates_by_duration",
]
