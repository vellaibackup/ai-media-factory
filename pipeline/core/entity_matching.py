"""Shared player-alias matching for footage discovery and verification.

Candidate footage titles rarely use a player's full name the way news
headlines do ("Lionel Messi" vs. "Messi", "Cristiano Ronaldo" vs. "CR7").
A plain substring check misses these routinely, which was the main gap in
player matching. This module centralises the fix (alias table + accent
normalisation + last-name fallback) so discovery relevance and story
verification agree on what counts as "this player is in this footage".
"""

from __future__ import annotations

import re
import unicodedata

from pipeline.core.bfi_config import PLAYER_ALIASES


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return stripped.casefold().strip()


_ALIAS_LOOKUP: dict[str, tuple[str, ...]] = {
    _normalize(name): tuple(_normalize(alias) for alias in aliases)
    for name, aliases in PLAYER_ALIASES.items()
}


def player_mentioned(player: str, text: str) -> bool:
    """Return True if `player` (a canonical full name) is referenced in `text`.

    Tries, in order: exact (accent-insensitive) match, known alias match,
    and a last-name-only fallback (safe for football because a player's
    surname alone is almost always how footage titles refer to them, and
    ambiguity is rare within a single story's candidate pool).
    """
    if not player:
        return False
    normalized_text = _normalize(text)
    normalized_player = _normalize(player)
    if re.search(rf"\b{re.escape(normalized_player)}\b", normalized_text):
        return True
    for alias in _ALIAS_LOOKUP.get(normalized_player, ()):
        if re.search(rf"\b{re.escape(alias)}\b", normalized_text):
            return True
    last_name = normalized_player.rsplit(" ", 1)[-1]
    if len(last_name) >= 3 and re.search(rf"\b{re.escape(last_name)}\b", normalized_text):
        return True
    return False


__all__ = ["player_mentioned"]
