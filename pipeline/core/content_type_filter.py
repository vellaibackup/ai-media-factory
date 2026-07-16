"""Reject non-highlight content formats from footage candidates.

Broadcast Footage Intelligence must reject talking-head videos, podcasts,
interviews, reaction videos, and football news discussions, while strongly
preferring official match highlights and broadcast footage of goals,
assists, saves, celebrations, and dramatic moments.

This is intentionally a deterministic keyword/regex classifier over
title + description text -- no computer vision, no paid service. It is
tuned to avoid false-positives on legitimate highlight framing: bare words
like "celebration" or "reaction" (as in "the crowd's reaction to the goal")
are fine; it is the *produced-format* markers (a creator "reacting to" a
clip, a podcast episode, a press conference) that get rejected.
"""

from __future__ import annotations

import re

# Each category maps to regexes that, if any matches, mean the footage is
# that content format rather than match footage. Order is reject-category
# name -> patterns; the first category with a hit wins (categories are
# checked in a fixed order below so the reason is deterministic).
_REJECT_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "podcast": tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            r"\bpodcast\b",
            r"\bep(?:isode)?\.?\s*#?\d+\b",
        )
    ),
    "interview": tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            r"\binterview\b",
            r"\bpress\s+conference\b",
            r"\bq\s*&\s*a\b",
            r"\bsits?\s+down\s+with\b",
            r"\bspeaks?\s+(?:to|with)\b",
            r"\bone[- ]on[- ]one\b",
            r"\bexclusive\s+chat\b",
        )
    ),
    "reaction_video": tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            r"\breact(?:s|ing)?\s+to\b",
            r"\bmy\s+reaction\b",
            r"\bfan\s+reacts?\b",
            r"\breaction\s+video\b",
            r"\byoutubers?\s+react\b",
        )
    ),
    "talking_head": tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            r"\bpundits?\b",
            r"\bpanel\s+(?:show|discussion)\b",
            r"\bround\s*table\b",
            r"\bin\s+the\s+studio\b",
            r"\bvlog\b",
        )
    ),
    "news_discussion": tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            r"\btransfer\s+talk\b",
            r"\bnews\s+round\s*up\b",
            r"\bdebate[sd]?\b",
            r"\bverdict\b",
            r"\btalking\s+points\b",
        )
    ),
}

# Fixed check order so the first matching category is reported as the reason.
_CATEGORY_ORDER = (
    "podcast",
    "interview",
    "reaction_video",
    "talking_head",
    "news_discussion",
)

_OFFICIAL_HIGHLIGHT_RE = re.compile(
    r"\b(?:official highlights|extended highlights|match highlights|official broadcast)\b",
    re.IGNORECASE,
)


def classify_rejected_content(title: str, description: str = "") -> str:
    """Return the rejected-content category name, or "" if not rejected.

    The title is the primary, trusted signal (it is where a "REACTS TO",
    "Podcast", or "Full Interview" format marker actually lives), and an
    explicit reject marker in the title always wins -- an "Official
    Highlights" label does not excuse a title that also says "Podcast" or
    "full interview". The description is noisier -- boilerplate, sponsor
    blurbs, unrelated links -- so it only gets a vote for the two most
    unambiguous categories (podcast/interview), and only when the title
    itself doesn't already read as an official highlights package.
    """
    for category in _CATEGORY_ORDER:
        if any(pattern.search(title) for pattern in _REJECT_PATTERNS[category]):
            return category
    if _OFFICIAL_HIGHLIGHT_RE.search(title):
        return ""
    for category in ("podcast", "interview"):
        if any(pattern.search(description) for pattern in _REJECT_PATTERNS[category]):
            return category
    return ""


def is_rejected_content(title: str, description: str = "") -> bool:
    return bool(classify_rejected_content(title, description))


__all__ = ["classify_rejected_content", "is_rejected_content"]
