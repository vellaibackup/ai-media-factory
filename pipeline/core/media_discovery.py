"""Read-only candidate video discovery for football stories."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable, Iterable

from pipeline.core.football_intelligence import FootballStory


_WORD_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+)D)?T?(?:(?P<hours>\d+)H)?"
    r"(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?$"
)
_STOP_WORDS = frozenset(
    {
        "a",
        "after",
        "and",
        "at",
        "for",
        "from",
        "in",
        "of",
        "on",
        "the",
        "to",
        "vs",
        "with",
    }
)


@dataclass(frozen=True)
class CandidateClip:
    title: str
    source: str
    url: str
    duration: int
    relevance_score: float
    confidence: float
    thumbnail: str
    description: str


class MediaDiscovery:
    """Discover and rank video metadata without downloading media."""

    def __init__(
        self,
        candidate_fetcher: Callable[[tuple[str, ...]], Iterable[dict[str, Any]]]
        | None = None,
    ) -> None:
        self._candidate_fetcher = candidate_fetcher or _youtube_candidates

    def discover(self, story: FootballStory) -> list[CandidateClip]:
        if not isinstance(story, FootballStory):
            raise TypeError("story must be a FootballStory")

        raw_candidates = list(self._candidate_fetcher(story.search_queries))[:20]
        candidates = [
            _candidate_clip(story, candidate)
            for candidate in _deduplicate(raw_candidates)
        ]
        ranked = sorted(
            candidates,
            key=lambda candidate: (
                -candidate.relevance_score,
                -candidate.confidence,
                candidate.title.casefold(),
                candidate.url,
            ),
        )
        return ranked[:5]


def _candidate_clip(
    story: FootballStory,
    candidate: dict[str, Any],
) -> CandidateClip:
    title = str(candidate.get("title", "")).strip()
    description = str(candidate.get("description", "")).strip()
    video_id = str(candidate.get("video_id", "")).strip()
    duration = int(candidate.get("duration", 0) or 0)
    thumbnail = str(candidate.get("thumbnail", "")).strip()
    if not title or not video_id:
        raise ValueError("candidate title and video_id are required")

    return CandidateClip(
        title=title,
        source="youtube",
        url=f"https://www.youtube.com/watch?v={video_id}",
        duration=duration,
        relevance_score=_relevance(story, title, description, duration),
        confidence=_confidence(description, duration, thumbnail),
        thumbnail=thumbnail,
        description=description,
    )


def _relevance(
    story: FootballStory,
    title: str,
    description: str,
    duration: int,
) -> float:
    story_text = " ".join(
        (
            story.title,
            story.competition,
            *story.teams,
            *story.players,
        )
    )
    story_terms = _terms(story_text)
    candidate_text = f"{title} {description}"
    candidate_terms = _terms(candidate_text)
    coverage = len(story_terms & candidate_terms) / max(1, len(story_terms))

    phrase_bonus = 0.0
    folded_candidate = candidate_text.casefold()
    for phrase in (*story.players, *story.teams):
        if phrase and phrase.casefold() in folded_candidate:
            phrase_bonus += 7.5
    if story.competition.casefold() in folded_candidate:
        phrase_bonus += 5.0

    duration_bonus = 0.0
    if duration > 0:
        target = max(1, story.recommended_duration)
        duration_bonus = max(0.0, 10.0 - abs(duration - target) / target * 5.0)

    score = coverage * 70.0 + min(20.0, phrase_bonus) + duration_bonus
    return round(min(100.0, score), 2)


def _confidence(description: str, duration: int, thumbnail: str) -> float:
    confidence = 0.65
    confidence += 0.1 if description else 0.0
    confidence += 0.1 if duration > 0 else 0.0
    confidence += 0.1 if thumbnail else 0.0
    return round(min(0.95, confidence), 2)


def _terms(value: str) -> set[str]:
    return {
        term
        for term in _WORD_RE.findall(value.casefold())
        if len(term) > 1 and term not in _STOP_WORDS
    }


def _deduplicate(candidates: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        video_id = str(candidate.get("video_id", "")).strip()
        if video_id and video_id not in selected:
            selected[video_id] = candidate
    return list(selected.values())


def _youtube_candidates(queries: tuple[str, ...]) -> list[dict[str, Any]]:
    from pipeline.sources.youtube_football_source import get_youtube_client

    youtube = get_youtube_client()
    snippets: dict[str, dict[str, Any]] = {}
    for query in queries:
        response = youtube.search().list(
            q=query,
            part="id,snippet",
            maxResults=5,
            type="video",
            order="relevance",
        ).execute()
        for item in response.get("items", []):
            video_id = item.get("id", {}).get("videoId")
            if video_id and video_id not in snippets and len(snippets) < 20:
                snippets[video_id] = item.get("snippet", {})

    if not snippets:
        return []

    details = youtube.videos().list(
        part="contentDetails,snippet",
        id=",".join(snippets),
    ).execute()
    candidates = []
    for item in details.get("items", []):
        video_id = item.get("id", "")
        snippet = item.get("snippet", {}) or snippets.get(video_id, {})
        thumbnails = snippet.get("thumbnails", {})
        thumbnail = (
            thumbnails.get("high")
            or thumbnails.get("medium")
            or thumbnails.get("default")
            or {}
        ).get("url", "")
        candidates.append(
            {
                "video_id": video_id,
                "title": snippet.get("title", ""),
                "description": snippet.get("description", ""),
                "thumbnail": thumbnail,
                "duration": _duration_seconds(
                    item.get("contentDetails", {}).get("duration", "")
                ),
            }
        )
    return candidates


def _duration_seconds(value: str) -> int:
    match = _DURATION_RE.fullmatch(value)
    if not match:
        return 0
    parts = {key: int(number or 0) for key, number in match.groupdict().items()}
    return (
        parts["days"] * 86400
        + parts["hours"] * 3600
        + parts["minutes"] * 60
        + parts["seconds"]
    )


__all__ = ["CandidateClip", "MediaDiscovery"]
