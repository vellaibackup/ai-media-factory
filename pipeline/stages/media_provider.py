"""Media provider contract and the MVP YouTube football implementation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
import subprocess


@dataclass(frozen=True)
class MediaCandidate:
    video_id: str
    title: str
    rank: int
    query: str


class MediaProvider(ABC):
    @abstractmethod
    def search(self, query: str) -> list[MediaCandidate]:
        """Return playable-video candidates in deterministic source order."""

    @abstractmethod
    def download(self, candidate: MediaCandidate, destination: Path) -> Path:
        """Download a candidate to a local playable video file."""

    @abstractmethod
    def score(self, candidate: MediaCandidate) -> float:
        """Return a deterministic, non-learning candidate score."""

    @abstractmethod
    def trim(
        self,
        source: Path,
        destination: Path,
        start_seconds: float,
        duration_seconds: float,
    ) -> Path:
        """Create one playable visual clip from a source video."""


class YouTubeFootballMediaProvider(MediaProvider):
    """MVP provider backed by the repository's existing YouTube source client."""

    def search(self, query: str) -> list[MediaCandidate]:
        from pipeline.sources.youtube_football_source import search_football_videos

        results = search_football_videos(query=query, max_results=5)
        return [
            MediaCandidate(
                video_id=result["video_id"],
                title=result["title"],
                rank=rank,
                query=query,
            )
            for rank, result in enumerate(results)
        ]

    def download(self, candidate: MediaCandidate, destination: Path) -> Path:
        from pipeline.sources.youtube_football_source import download_video

        destination.parent.mkdir(parents=True, exist_ok=True)
        download_video(candidate.video_id, str(destination))
        if not destination.is_file():
            raise FileNotFoundError(f"Downloaded media was not created: {destination}")
        return destination

    def score(self, candidate: MediaCandidate) -> float:
        query_terms = set(candidate.query.casefold().split())
        title_terms = set(candidate.title.casefold().split())
        relevance = len(query_terms & title_terms) / max(1, len(query_terms))
        return round(relevance + (1.0 / (candidate.rank + 1)), 6)

    def trim(
        self,
        source: Path,
        destination: Path,
        start_seconds: float,
        duration_seconds: float,
    ) -> Path:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss", str(start_seconds),
                "-i", str(source),
                "-t", str(duration_seconds),
                "-vf",
                (
                    "scale=1080:1920:force_original_aspect_ratio=increase,"
                    "crop=1080:1920,setsar=1"
                ),
                "-r", "30",
                str(destination),
            ],
            check=True,
        )
        return destination


__all__ = [
    "MediaCandidate",
    "MediaProvider",
    "YouTubeFootballMediaProvider",
]
