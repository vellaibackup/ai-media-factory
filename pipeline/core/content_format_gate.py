"""Content-format penalty gate for Broadcast Footage Intelligence (Sprint D).

Distinct from content_type_filter.py's hard-reject categories (podcast,
interview, reaction video, talking head, news discussion): those are
rejected outright. The formats here -- prediction, preview, studio,
breakdown, recap, discussion, meme, analysis -- are not rejected, since a
studio breakdown might still contain some real footage, but they must never
be allowed to outrank genuine match highlights on the strength of technical
quality or official-broadcaster status alone. This is exactly the failure
Sprint D fixes: an official-channel prediction/studio clip beating genuine
highlight footage of similar technical quality.

classify_low_value_format() names the matched format, or "" if the title/
description reads as ordinary match/highlight content. Used in two places:
  - media_discovery._source_quality_score(): the official-broadcaster
    relevance bonus must not apply to a low-value-format candidate, even if
    it comes from an official channel.
  - professional_sports_editor.score_candidate(): a strong, deterministic
    penalty applied to the final per-candidate quality score.
"""

from __future__ import annotations

import re

_LOW_VALUE_FORMAT_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "prediction": tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            r"\bpredict(?:s|ion|ions|ing)?\b",
            r"\bwho'?s\s+(?:going\s+to\s+)?scor(?:e|ing)\b",
            r"\bwho\s+will\s+score\b",
            r"\bscore\s+predictions?\b",
        )
    ),
    "preview": tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            r"\bmatch\s+preview\b",
            r"\bpredicted\s+lineup\b",
            r"\bpreview\s+show\b",
        )
    ),
    "studio": tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            r"\bstudio\s+(?:show|reaction|breakdown)\b",
            r"\bin\s+the\s+studio\b",
        )
    ),
    "breakdown": tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            r"\btactical\s+breakdown\b",
            r"\bstudio\s+breakdown\b",
            r"\bmatch\s+breakdown\b",
        )
    ),
    "recap": tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            r"\brecap\b",
        )
    ),
    "discussion": tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            r"\bdiscussion\b",
            r"\bdiscuss(?:es|ing)?\b",
        )
    ),
    "meme": tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            r"\bmemes?\b",
        )
    ),
    "analysis": tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            r"\btactical\s+analysis\b",
            r"\bmatch\s+analysis\b",
            r"\bin-depth\s+analysis\b",
        )
    ),
}

_CATEGORY_ORDER = (
    "prediction",
    "preview",
    "studio",
    "breakdown",
    "recap",
    "discussion",
    "meme",
    "analysis",
)


def classify_low_value_format(title: str, description: str = "") -> str:
    """Return the matched low-value-format category name, or "" if none."""
    text = f"{title} {description}"
    for category in _CATEGORY_ORDER:
        if any(pattern.search(text) for pattern in _LOW_VALUE_FORMAT_PATTERNS[category]):
            return category
    return ""


def is_low_value_format(title: str, description: str = "") -> bool:
    return bool(classify_low_value_format(title, description))


__all__ = ["classify_low_value_format", "is_low_value_format"]
