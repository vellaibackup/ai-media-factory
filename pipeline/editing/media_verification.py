"""Verify that discovered footage describes the selected football story."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable, Iterable

from pipeline.core import bfi_config
from pipeline.core.content_type_filter import classify_rejected_content
from pipeline.core.entity_matching import player_mentioned
from pipeline.core.football_intelligence import FootballStory
from pipeline.core.media_discovery import CandidateClip
from pipeline.editing.professional_sports_editor import youtube_metadata


VERIFICATION_THRESHOLD = bfi_config.VERIFICATION_THRESHOLD
_GENERIC_CONTAINER_RE = re.compile(
    r"\b(?:highlights?|compilation|full match|all goals|best moments|top\s+\d+|skills?)\b",
    re.IGNORECASE,
)
_EVENT_PATTERNS = (
    ("penalty save", re.compile(r"\b(?:penalty(?:\s+\w+){0,3}\s+sav(?:e|ed)|sav(?:e|ed)(?:\s+\w+){0,3}\s+penalty)\b")),
    ("penalty goal", re.compile(r"\b(?:penalty(?:\s+\w+){0,2}\s+(?:goal|scor(?:e|ed))|scor(?:e|ed)(?:\s+\w+){0,2}\s+penalty)\b")),
    ("own goal", re.compile(r"\bown goal\b")),
    ("free kick", re.compile(r"\bfree[ -]?kick\b")),
    ("red card", re.compile(r"\b(?:red card|sent off|sending off)\b")),
    ("yellow card", re.compile(r"\byellow card\b")),
    ("assist", re.compile(r"\bassist(?:ed|s)?\b")),
    ("celebration", re.compile(r"\bcelebrat(?:e|es|ed|ion|ions|ing)\b")),
    ("injury", re.compile(r"\b(?:injury|injured)\b")),
    ("substitution", re.compile(r"\b(?:substitution|substitute[ds]?|subbed)\b")),
    ("save", re.compile(r"\b(?:goalkeeper|keeper|shot)?\s*sav(?:e|es|ed|ing)\b")),
    ("goal", re.compile(r"\b(?:goal|goals|scores|scored|equaliser|equalizer)\b")),
)
_CATEGORY_EVENT = {
    "Goals": "goal",
    "Red cards": "red card",
    "Saves": "save",
    "Celebrations": "celebration",
}


@dataclass(frozen=True)
class VerificationResult:
    candidate: CandidateClip
    score: float
    accepted: bool
    matched_entities: dict[str, list[str]]
    missing_entities: dict[str, list[str]]
    reason: str
    metadata: dict[str, Any]
    primary_event: str
    candidate_events: tuple[str, ...]
    event_score: float
    match_report: dict[str, Any]

    def report(self) -> dict[str, Any]:
        return {
            "title": self.candidate.title,
            "url": self.candidate.url,
            "verification_score": self.score,
            "extracted_event": self.primary_event,
            "candidate_events": list(self.candidate_events),
            "event_verification_score": self.event_score,
            **self.match_report,
            "matched_entities": self.matched_entities,
            "missing_entities": self.missing_entities,
            "reason": self.reason,
        }


def _metadata_text(candidate: CandidateClip, metadata: dict[str, Any]) -> str:
    values = [
        candidate.title,
        candidate.description,
        str(metadata.get("title") or ""),
        str(metadata.get("description") or ""),
        " ".join(str(item) for item in metadata.get("tags") or []),
        " ".join(str(item) for item in metadata.get("categories") or []),
    ]
    return " ".join(values).casefold()


def _extract_events(text: str) -> tuple[str, ...]:
    folded = text.casefold()
    return tuple(event for event, pattern in _EVENT_PATTERNS if pattern.search(folded))


def extract_primary_event(story: FootballStory) -> str:
    story_text = " ".join(
        (story.title, story.summary, story.category, story.recommended_video_type)
    )
    events = _extract_events(story_text)
    return events[0] if events else _CATEGORY_EVENT.get(story.category, "")


def _candidate_events(candidate: CandidateClip, metadata: dict[str, Any]) -> tuple[str, ...]:
    title_events = _extract_events(candidate.title)
    if title_events:
        return title_events
    supporting_text = " ".join(
        (
            candidate.description,
            str(metadata.get("description") or ""),
            " ".join(str(item) for item in metadata.get("tags") or []),
            " ".join(str(item) for item in metadata.get("categories") or []),
        )
    )
    return _extract_events(supporting_text)


def _entity_match(entity: str, text: str) -> bool:
    folded = entity.casefold()
    if folded in text:
        return True
    aliases = {
        "fifa world cup": ("world cup",),
        "uefa champions league": ("champions league", "ucl"),
        "uefa europa league": ("europa league", "uel"),
        "premier league": ("epl",),
    }
    return any(alias in text for alias in aliases.get(folded, ()))


def _player_entity_match(player: str, text: str) -> bool:
    """Player matching with alias/nickname and accent-insensitive fallback.

    A plain substring check on the full name ("Lionel Messi") misses the
    common case where footage titles use a short form ("Messi", "Leo
    Messi", "CR7"). See pipeline/core/entity_matching.py.
    """
    return player_mentioned(player, text)


def _event_score(primary_event: str, candidate: CandidateClip, metadata: dict[str, Any]) -> float:
    if not primary_event:
        return 0.0
    title_events = _extract_events(candidate.title)
    if primary_event in title_events:
        return 100.0
    if title_events:
        return 0.0
    if _GENERIC_CONTAINER_RE.search(candidate.title):
        return 0.0
    supporting_events = _extract_events(
        " ".join(
            (
                candidate.description,
                str(metadata.get("title") or ""),
                str(metadata.get("description") or ""),
                " ".join(str(item) for item in metadata.get("tags") or []),
                " ".join(str(item) for item in metadata.get("categories") or []),
            )
        )
    )
    return 80.0 if primary_event in supporting_events else 0.0


def verify_candidate(
    story: FootballStory,
    candidate: CandidateClip,
    metadata: dict[str, Any] | None = None,
    threshold: float = VERIFICATION_THRESHOLD,
) -> VerificationResult:
    metadata = metadata or {}
    text = _metadata_text(candidate, metadata)
    primary_event = extract_primary_event(story)
    candidate_events = _candidate_events(candidate, metadata)
    event_score = _event_score(primary_event, candidate, metadata)
    event_match = event_score >= bfi_config.EVENT_MATCH_THRESHOLD
    content_type_rejection = classify_rejected_content(candidate.title, candidate.description)
    expected = {
        "teams": list(story.teams),
        "players": list(story.players),
        "competition": [] if story.competition == "Football" else [story.competition],
        "event_type": [primary_event] if primary_event else [],
    }
    matched = {
        "teams": [item for item in expected["teams"] if _entity_match(item, text)],
        "players": [item for item in expected["players"] if _player_entity_match(item, text)],
        "competition": [item for item in expected["competition"] if _entity_match(item, text)],
        "event_type": [primary_event] if event_match else [],
    }
    missing = {
        dimension: [item for item in values if item not in matched[dimension]]
        for dimension, values in expected.items()
    }
    weights = bfi_config.ENTITY_WEIGHTS
    available_weight = sum(weights[key] for key, values in expected.items() if values)
    earned_weight = sum(
        weights[key] * len(matched[key]) / len(values)
        for key, values in expected.items()
        if values
    )
    score = round(100.0 * earned_weight / available_weight, 2) if available_weight else 0.0
    required_dimensions_match = all(
        len(matched[key]) == len(values)
        for key, values in expected.items()
        if values and key in {"teams", "players", "competition", "event_type"}
    )
    accepted = (
        not content_type_rejection
        and score >= threshold
        and event_match
        and required_dimensions_match
    )
    match_report = {
        "player_match": {
            "expected": expected["players"],
            "matched": matched["players"],
            "score": round(100 * len(matched["players"]) / len(expected["players"]), 2)
            if expected["players"] else None,
        },
        "team_match": {
            "expected": expected["teams"],
            "matched": matched["teams"],
            "score": round(100 * len(matched["teams"]) / len(expected["teams"]), 2)
            if expected["teams"] else None,
        },
        "competition_match": {
            "expected": expected["competition"],
            "matched": matched["competition"],
            "score": 100.0 if matched["competition"] else (None if not expected["competition"] else 0.0),
        },
        "event_match": {
            "expected": primary_event,
            "candidate_events": list(candidate_events),
            "matched": event_match,
            "score": event_score,
        },
    }
    reason = (
        f"accepted: exact story-footage verification {score:.2f} >= {threshold:.2f}"
        if accepted
        else (
            f"rejected: content type '{content_type_rejection}' is not eligible footage"
            if content_type_rejection
            else "rejected: candidate does not match all required story entities/events"
            if score >= threshold
            else f"rejected: story-footage verification {score:.2f} < {threshold:.2f}"
        )
    )
    return VerificationResult(
        candidate, score, accepted, matched, missing, reason, metadata,
        primary_event, candidate_events, event_score, match_report,
    )


def verify_candidates(
    story: FootballStory,
    candidates: Iterable[CandidateClip],
    metadata_fetcher: Callable[[str], dict[str, Any]] = youtube_metadata,
    threshold: float = VERIFICATION_THRESHOLD,
) -> list[VerificationResult]:
    results = []
    for candidate in candidates:
        try:
            metadata = metadata_fetcher(candidate.url)
        except Exception as exc:
            metadata = {"verification_metadata_error": str(exc)}
        results.append(verify_candidate(story, candidate, metadata, threshold))
    return sorted(
        results,
        key=lambda item: (
            not item.accepted,
            -item.event_score,
            -item.score,
            -item.candidate.relevance_score,
            item.candidate.url,
        ),
    )


__all__ = [
    "VERIFICATION_THRESHOLD",
    "VerificationResult",
    "extract_primary_event",
    "verify_candidate",
    "verify_candidates",
]
