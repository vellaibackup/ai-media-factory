"""Freshness gate for football source media."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse


DEFAULT_HISTORY_LIMIT = 30
DEFAULT_HISTORY_PATH = Path("output/football/source_video_history.json")


def youtube_video_id(url: str) -> str:
    parsed = urlparse(url)
    if parsed.netloc.endswith("youtu.be"):
        return parsed.path.strip("/")
    return parse_qs(parsed.query).get("v", [""])[0].strip()


@dataclass(frozen=True)
class FreshnessRejection:
    title: str
    url: str
    video_id: str
    reason: str

    def report(self) -> dict[str, str]:
        return {
            "title": self.title,
            "url": self.url,
            "video_id": self.video_id,
            "reason": self.reason,
        }


class SourceVideoHistory:
    def __init__(
        self,
        path: Path | str = DEFAULT_HISTORY_PATH,
        limit: int = DEFAULT_HISTORY_LIMIT,
    ) -> None:
        self.path = Path(path)
        self.limit = limit

    def recent_video_ids(self) -> tuple[str, ...]:
        if not self.path.exists():
            return ()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ()
        if not isinstance(payload, list):
            return ()
        ids = [
            str(item.get("source_video_id", "")).strip()
            for item in payload
            if isinstance(item, dict)
        ]
        return tuple(video_id for video_id in ids if video_id)[-self.limit :]

    def is_recent(self, video_id: str) -> bool:
        return video_id in set(self.recent_video_ids())

    def record_published(
        self,
        *,
        source_video_id: str,
        source_url: str,
        source_title: str,
        published_video_id: str,
        published_url: str,
    ) -> None:
        source_video_id = source_video_id.strip()
        if not source_video_id:
            return
        entries = self._entries()
        entries.append(
            {
                "source_video_id": source_video_id,
                "source_url": source_url,
                "source_title": source_title,
                "published_video_id": published_video_id,
                "published_url": published_url,
            }
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(entries[-self.limit :], indent=2),
            encoding="utf-8",
        )

    def _entries(self) -> list[dict[str, str]]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(payload, list):
            return []
        return [item for item in payload if isinstance(item, dict)]


def filter_fresh_candidates(
    candidates: list[object],
    history: SourceVideoHistory,
) -> tuple[list[object], list[FreshnessRejection]]:
    recent = set(history.recent_video_ids())
    fresh = []
    rejected = []
    for candidate in candidates:
        url = str(getattr(candidate, "url", ""))
        video_id = youtube_video_id(url)
        if video_id and video_id in recent:
            rejected.append(
                FreshnessRejection(
                    title=str(getattr(candidate, "title", "")),
                    url=url,
                    video_id=video_id,
                    reason="rejected: source video used in the last 30 published Shorts",
                )
            )
        else:
            fresh.append(candidate)
    return fresh, rejected


__all__ = [
    "DEFAULT_HISTORY_LIMIT",
    "DEFAULT_HISTORY_PATH",
    "FreshnessRejection",
    "SourceVideoHistory",
    "filter_fresh_candidates",
    "youtube_video_id",
]
