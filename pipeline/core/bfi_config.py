"""Configurable scoring for Broadcast Footage Intelligence (BFI).

Every threshold and weight used to decide which footage is verified,
ranked, or rejected lives here as a single adjustable value (with an
environment-variable override), instead of as a magic number buried in
scoring logic. Nothing here calls a paid service or does computer vision;
all matching is deterministic keyword/regex/text scoring, in keeping with
the zero-cost, lean design of the rest of the pipeline.
"""

from __future__ import annotations

import os


def _float_env(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# Verification gate (pipeline/editing/media_verification.py)
# ---------------------------------------------------------------------------
VERIFICATION_THRESHOLD = _float_env("BFI_VERIFICATION_THRESHOLD", 75.0)
EVENT_MATCH_THRESHOLD = _float_env("BFI_EVENT_MATCH_THRESHOLD", 80.0)
ACCEPTANCE_CONFIDENCE_THRESHOLD = _float_env("BFI_ACCEPTANCE_CONFIDENCE_THRESHOLD", 0.8)

# Weight given to each entity dimension when computing the story-footage
# verification score. event_type dominates on purpose: matching the right
# teams/players but the wrong moment is still the wrong clip.
ENTITY_WEIGHTS = {
    "teams": _float_env("BFI_WEIGHT_TEAMS", 10.0),
    "players": _float_env("BFI_WEIGHT_PLAYERS", 20.0),
    "competition": _float_env("BFI_WEIGHT_COMPETITION", 20.0),
    "event_type": _float_env("BFI_WEIGHT_EVENT_TYPE", 50.0),
}

# ---------------------------------------------------------------------------
# Relevance scoring (pipeline/core/media_discovery.py)
# ---------------------------------------------------------------------------
# Title and source quality dominate; description is a weak, easily-gamed
# signal (keyword-stuffed descriptions are common) and is weighted down
# relative to both title and source quality, per BFI Phase 1 requirements.
# (Old scheme: a single "coverage" term split title+description evenly,
# worth 20 total. This keeps the same 20-point budget but skews it so
# description contributes far less than title or source quality.)
TITLE_COVERAGE_WEIGHT = _float_env("BFI_TITLE_COVERAGE_WEIGHT", 14.0)
DESCRIPTION_COVERAGE_WEIGHT = _float_env("BFI_DESCRIPTION_COVERAGE_WEIGHT", 5.0)
SOURCE_QUALITY_WEIGHT = _float_env("BFI_SOURCE_QUALITY_WEIGHT", 10.0)
PLAYER_WEIGHT = _float_env("BFI_PLAYER_WEIGHT", 20.0)
TEAM_WEIGHT = _float_env("BFI_TEAM_WEIGHT", 20.0)
COMPETITION_WEIGHT = _float_env("BFI_COMPETITION_WEIGHT", 15.0)
EVENT_WEIGHT = _float_env("BFI_EVENT_WEIGHT", 20.0)
DURATION_BONUS_MAX = _float_env("BFI_DURATION_BONUS_MAX", 5.0)

# ---------------------------------------------------------------------------
# Player alias matching
# ---------------------------------------------------------------------------
# Canonical full name (as extracted from headline text) -> known alternate
# forms candidate footage titles commonly use. Hand-maintained on purpose:
# adding a player is a one-line edit, no model/service required.
PLAYER_ALIASES: dict[str, tuple[str, ...]] = {
    "Lionel Messi": ("Messi", "Leo Messi", "La Pulga"),
    "Cristiano Ronaldo": ("Ronaldo", "CR7", "Cristiano"),
    "Kylian Mbappe": ("Mbappe", "Mbappé", "Kylian Mbappé"),
    "Neymar Jr": ("Neymar", "Neymar Junior", "Neymar Santos"),
    "Vinicius Junior": ("Vinicius Jr", "Vini Jr", "Vinícius Júnior", "Vinicius Jr."),
    "Erling Haaland": ("Haaland", "Erling Braut Haaland"),
    "Kevin De Bruyne": ("De Bruyne", "KDB"),
    "Mohamed Salah": ("Mo Salah", "Salah"),
    "Harry Kane": ("Kane", "HK9"),
    "Robert Lewandowski": ("Lewandowski", "Lewy"),
    "Karim Benzema": ("Benzema", "Benzéma"),
    "Jude Bellingham": ("Bellingham",),
    "Bukayo Saka": ("Saka",),
    "Phil Foden": ("Foden",),
    "Luka Modric": ("Modric", "Modrić", "Luka Modrić"),
    "Jamal Musiala": ("Musiala",),
    "Bernardo Silva": ("Bernardo",),
    "Virgil van Dijk": ("Van Dijk", "VVD"),
    "Antoine Griezmann": ("Griezmann",),
    "Son Heung-min": ("Son", "Sonny", "Heung-min Son"),
}

# ---------------------------------------------------------------------------
# Officially trusted broadcast sources (used for the source-quality bonus
# and for "strongly prefer official highlights/broadcast footage").
# ---------------------------------------------------------------------------
OFFICIAL_BROADCAST_CHANNELS = (
    "FIFA",
    "UEFA",
    "Premier League",
    "LALIGA",
    "Bundesliga",
    "Serie A",
    "Ligue 1",
    "Major League Soccer",
    "MLS",
    "ESPN FC",
    "Sky Sports Football",
    "Sky Sports",
    "BBC Sport",
    "CBS Sports Golazo",
    "FOX Soccer",
    "beIN SPORTS",
    "TNT Sports",
    "OneFootball",
    "The Athletic FC",
    "Guardian Football",
)

OFFICIAL_HIGHLIGHT_PHRASES = (
    "official highlights",
    "extended highlights",
    "match highlights",
    "official broadcast",
)

__all__ = [
    "VERIFICATION_THRESHOLD",
    "EVENT_MATCH_THRESHOLD",
    "ACCEPTANCE_CONFIDENCE_THRESHOLD",
    "ENTITY_WEIGHTS",
    "TITLE_COVERAGE_WEIGHT",
    "DESCRIPTION_COVERAGE_WEIGHT",
    "SOURCE_QUALITY_WEIGHT",
    "PLAYER_WEIGHT",
    "TEAM_WEIGHT",
    "COMPETITION_WEIGHT",
    "EVENT_WEIGHT",
    "DURATION_BONUS_MAX",
    "PLAYER_ALIASES",
    "OFFICIAL_BROADCAST_CHANNELS",
    "OFFICIAL_HIGHLIGHT_PHRASES",
]
