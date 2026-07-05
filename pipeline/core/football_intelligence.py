"""Live, deterministic football story discovery and editorial ranking."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as Date, datetime, timezone
from email.utils import parsedate_to_datetime
import html
import json
import re
from typing import Any, Callable, Iterable
from urllib.parse import quote_plus
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


_ESPN_COMPETITIONS = {
    "eng.1": "Premier League",
    "esp.1": "La Liga",
    "ger.1": "Bundesliga",
    "ita.1": "Serie A",
    "fra.1": "Ligue 1",
    "uefa.champions": "UEFA Champions League",
    "fifa.world": "FIFA World Cup",
}
_NEWS_QUERIES = (
    ("Goals", "football goal OR penalty OR winner when:1d"),
    ("Red cards", "football red card dramatic incident when:1d"),
    ("VAR", "football VAR controversy disallowed goal when:1d"),
    ("Saves", "football penalty save goalkeeper when:1d"),
    ("Comebacks", "football comeback last-minute winner when:1d"),
    ("Celebrations", "football goal celebration crowd reaction when:1d"),
    ("World Cup events", "World Cup goal penalty red card winner when:1d"),
)
_CATEGORY_VIDEO_TYPES = {
    "Fixtures": "match preview",
    "Results": "match recap",
    "Goals": "goal breakdown",
    "Red cards": "incident timeline",
    "VAR": "frame-by-frame controversy",
    "Saves": "decisive-save replay",
    "Comebacks": "comeback timeline",
    "Celebrations": "reaction sequence",
    "World Cup events": "tournament moment breakdown",
}
_IMPORTANCE_TERMS = {
    "final": 10,
    "title": 9,
    "champions league": 9,
    "premier league": 8,
    "record": 7,
    "transfer": 6,
    "injury": 5,
    "derby": 5,
}
_ACTION_TERMS = {
    "goal": 14,
    "winner": 14,
    "last-minute": 15,
    "stoppage-time": 15,
    "penalty": 12,
    "red card": 12,
    "sent off": 11,
    "var": 11,
    "comeback": 14,
    "save": 11,
    "equaliser": 10,
    "celebration": 8,
    "dramatic": 7,
    "world cup": 10,
}
_LOW_VALUE_TERMS = {
    "transfer news": 22,
    "transfer target": 18,
    "rumour": 20,
    "signing": 18,
    "pundit": 18,
    "advice": 14,
    "roundup": 20,
    "ins and outs": 20,
    "tracker": 18,
}
_FOOTBALL_TERMS = (
    "football",
    "soccer",
    "fifa",
    "premier league",
    "champions league",
    "la liga",
    "serie a",
    "bundesliga",
    "ligue 1",
    "goal",
    "penalty",
    "goalkeeper",
    "red card",
    "var",
)
_PLAYER_STOPWORDS = {
    "Champions League",
    "Premier League",
    "La Liga",
    "Serie A",
    "Ligue One",
    "World Cup",
    "Football News",
    "Golden Boot",
}
_KNOWN_TEAMS = (
    "Arsenal",
    "Barcelona",
    "Bayern Munich",
    "Chelsea",
    "Inter Milan",
    "Juventus",
    "Liverpool",
    "Manchester City",
    "Manchester United",
    "Man City",
    "Man United",
    "Paris Saint-Germain",
    "PSG",
    "Real Madrid",
    "Tottenham",
)
_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")
_PROPER_NAME_RE = re.compile(
    r"\b(?:[A-Z][a-zÀ-ÖØ-öø-ÿ'’-]+)(?:\s+[A-Z][a-zÀ-ÖØ-öø-ÿ'’-]+){1,2}\b"
)


class FootballIntelligenceError(RuntimeError):
    pass


@dataclass(frozen=True)
class FootballStory:
    title: str
    category: str
    competition: str
    teams: tuple[str, ...]
    players: tuple[str, ...]
    importance_score: float
    trend_score: float
    novelty_score: float
    confidence: float
    recommended_video_type: str
    search_queries: tuple[str, ...]
    recommended_duration: int
    recommended_hook: str
    summary: str = ""

    def __post_init__(self) -> None:
        if not self.title or not self.summary:
            raise ValueError("FootballStory title and summary must not be empty")
        for field_name in ("importance_score", "trend_score", "novelty_score"):
            if not 0 <= getattr(self, field_name) <= 100:
                raise ValueError(f"{field_name} must be between 0 and 100")
        if not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        if self.recommended_duration <= 0 or not self.search_queries:
            raise ValueError("duration and search queries must be populated")

    @property
    def overall_score(self) -> float:
        return round(
            0.5 * self.importance_score
            + 0.3 * self.trend_score
            + 0.2 * self.novelty_score,
            2,
        )


class FootballIntelligence:
    """Discover and rank current football stories without downloading media."""

    def __init__(
        self,
        fetch_json: Callable[[str], dict[str, Any]] | None = None,
        fetch_xml: Callable[[str], bytes] | None = None,
    ) -> None:
        self._fetch_json = fetch_json or _fetch_json
        self._fetch_xml = fetch_xml or _fetch_bytes

    def discover(self, date: Date | str | None = None) -> list[FootballStory]:
        discovery_date = _normalise_date(date)
        stories: list[FootballStory] = []
        failures: list[str] = []

        for competition_id, competition in _ESPN_COMPETITIONS.items():
            try:
                stories.extend(
                    self._discover_matches(
                        competition_id,
                        competition,
                        discovery_date,
                    )
                )
            except Exception as exc:
                failures.append(f"{competition}: {exc}")

        for category, query in _NEWS_QUERIES:
            try:
                stories.extend(self._discover_news(category, query, discovery_date))
            except Exception as exc:
                failures.append(f"{category}: {exc}")

        ranked = sorted(
            _deduplicate(stories),
            key=lambda story: (
                -story.overall_score,
                -story.confidence,
                story.title.casefold(),
            ),
        )
        if len(ranked) < 5:
            detail = "; ".join(failures) or "insufficient live stories"
            raise FootballIntelligenceError(
                f"Live discovery returned {len(ranked)} stories; {detail}"
            )
        return ranked[:5]

    def _discover_matches(
        self,
        competition_id: str,
        competition: str,
        discovery_date: Date,
    ) -> list[FootballStory]:
        day = discovery_date.strftime("%Y%m%d")
        url = (
            "https://site.api.espn.com/apis/site/v2/sports/soccer/"
            f"{competition_id}/scoreboard?dates={day}"
        )
        payload = self._fetch_json(url)
        stories = []
        for event in payload.get("events", []):
            competition_data = (event.get("competitions") or [{}])[0]
            competitors = competition_data.get("competitors") or []
            teams = tuple(
                competitor.get("team", {}).get("displayName", "").strip()
                for competitor in competitors
                if competitor.get("team", {}).get("displayName")
            )
            if len(teams) < 2:
                continue
            completed = bool(competition_data.get("status", {}).get("type", {}).get("completed"))
            category = "Results" if completed else "Fixtures"
            score_text = ""
            if completed:
                scores = [str(item.get("score", "0")) for item in competitors]
                score_text = f" finished {'-'.join(scores)}"
            title = f"{teams[0]} vs {teams[1]}{score_text}"
            summary = (
                f"{competition} {category.lower()} for {discovery_date.isoformat()}: "
                f"{teams[0]} against {teams[1]}{score_text}."
            )
            importance = _importance(title, competition, 76 if completed else 68)
            stories.append(
                _build_story(
                    title=title,
                    summary=summary,
                    category=category,
                    competition=competition,
                    teams=teams,
                    players=(),
                    importance=importance,
                    trend=82 if completed else 70,
                    novelty=58 if completed else 52,
                    confidence=0.97,
                )
            )
        return stories

    def _discover_news(
        self,
        category: str,
        query: str,
        discovery_date: Date,
    ) -> list[FootballStory]:
        url = (
            "https://news.google.com/rss/search?q="
            f"{quote_plus(query)}&hl=en-GB&gl=GB&ceid=GB:en"
        )
        root = ET.fromstring(self._fetch_xml(url))
        stories = []
        for rank, item in enumerate(root.findall("./channel/item")[:10]):
            title = _headline(_clean(item.findtext("title", "")))
            summary = _clean(item.findtext("description", ""))
            published = _published(item.findtext("pubDate"), discovery_date)
            if not title or not summary:
                continue
            if not _video_worthy(f"{title} {summary}", category):
                continue
            age_hours = max(
                0.0,
                (
                    datetime.combine(
                        discovery_date,
                        datetime.max.time(),
                        tzinfo=timezone.utc,
                    )
                    - published
                ).total_seconds()
                / 3600,
            )
            competition = _competition_from_text(f"{title} {summary}")
            teams = _teams_from_text(title)
            players = _players_from_text(title, teams)
            action_score = _action_score(f"{title} {summary}")
            trend = max(
                35.0,
                88.0 - min(48.0, age_hours) - rank * 1.5 + action_score * 0.3,
            )
            importance = _importance(title, competition, 64)
            novelty = _novelty(title, category)
            stories.append(
                _build_story(
                    title=title,
                    summary=summary,
                    category=category,
                    competition=competition,
                    teams=teams,
                    players=players,
                    importance=importance,
                    trend=trend,
                    novelty=novelty,
                    confidence=0.82,
                )
            )
        return stories


def _build_story(
    *,
    title: str,
    summary: str,
    category: str,
    competition: str,
    teams: tuple[str, ...],
    players: tuple[str, ...],
    importance: float,
    trend: float,
    novelty: float,
    confidence: float,
) -> FootballStory:
    subject = players[0] if players else " vs ".join(teams) if teams else title
    subject = subject[:90].strip()
    return FootballStory(
        title=title,
        summary=summary,
        category=category,
        competition=competition,
        teams=teams,
        players=players,
        importance_score=round(min(100.0, importance), 2),
        trend_score=round(min(100.0, trend), 2),
        novelty_score=round(min(100.0, novelty), 2),
        confidence=confidence,
        recommended_video_type=_CATEGORY_VIDEO_TYPES[category],
        search_queries=(
            f"{subject} football",
            f"{subject} highlights",
            f"{subject} reaction",
            f"{subject} analysis",
        ),
        recommended_duration=24 if category in {"Results", "Comebacks", "VAR"} else 20,
        recommended_hook=_hook(title, category, subject),
    )


def _importance(title: str, competition: str, base: float) -> float:
    text = f"{title} {competition}".casefold()
    importance = base
    importance += sum(value for term, value in _IMPORTANCE_TERMS.items() if term in text)
    importance += _action_score(text)
    importance -= sum(value for term, value in _LOW_VALUE_TERMS.items() if term in text)
    return max(0.0, min(100.0, importance))


def _novelty(title: str, category: str) -> float:
    unique_ratio = len(set(title.casefold().split())) / max(1, len(title.split()))
    category_bonus = {
        "Comebacks": 14,
        "VAR": 12,
        "Red cards": 11,
        "Saves": 10,
        "Goals": 9,
        "World Cup events": 9,
        "Celebrations": 7,
    }.get(category, 3)
    return min(100.0, 48 + unique_ratio * 32 + category_bonus)


def _hook(title: str, category: str, subject: str) -> str:
    templates = {
        "Fixtures": f"Why {subject} is today's match to watch.",
        "Results": f"The detail that decided {subject}.",
        "Goals": f"This goal changed the match in seconds.",
        "Red cards": f"One challenge turned the entire match.",
        "VAR": f"This VAR decision changed what everyone thought they saw.",
        "Saves": f"This save mattered as much as any goal.",
        "Comebacks": f"The match looked over—then everything changed.",
        "Celebrations": f"The reaction tells you how much this moment meant.",
        "World Cup events": f"This World Cup moment changed the tournament.",
    }
    return templates.get(category, title[:100])


def _action_score(text: str) -> float:
    folded = text.casefold()
    return float(sum(value for term, value in _ACTION_TERMS.items() if term in folded))


def _video_worthy(text: str, category: str) -> bool:
    folded = text.casefold()
    if not any(term in folded for term in _FOOTBALL_TERMS):
        return False
    if any(term in folded for term in _LOW_VALUE_TERMS):
        return False
    if category == "World Cup events" and "world cup" not in folded:
        return False
    return _action_score(folded) >= 10


def _competition_from_text(text: str) -> str:
    folded = text.casefold()
    if "world cup" in folded:
        return "FIFA World Cup"
    for competition in _ESPN_COMPETITIONS.values():
        if competition.casefold() in folded:
            return competition
    return "Football"


def _teams_from_text(text: str) -> tuple[str, ...]:
    folded = text.casefold()
    return tuple(team for team in _KNOWN_TEAMS if team.casefold() in folded)[:3]


def _players_from_text(text: str, teams: tuple[str, ...]) -> tuple[str, ...]:
    names = []
    for name in _PROPER_NAME_RE.findall(text):
        if name not in _PLAYER_STOPWORDS and name not in teams and name not in names:
            names.append(name)
    return tuple(names[:3])


def _headline(value: str) -> str:
    headline, separator, _source = value.rpartition(" - ")
    return headline.strip() if separator else value


def _clean(value: str) -> str:
    return _SPACE_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", value))).strip()


def _published(value: str | None, discovery_date: Date) -> datetime:
    if not value:
        return datetime.combine(
            discovery_date,
            datetime.min.time(),
            tzinfo=timezone.utc,
        )
    parsed = parsedate_to_datetime(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _deduplicate(stories: Iterable[FootballStory]) -> list[FootballStory]:
    selected: dict[str, FootballStory] = {}
    for story in stories:
        key = re.sub(r"[^a-z0-9]+", " ", story.title.casefold()).strip()
        current = selected.get(key)
        if current is None or story.overall_score > current.overall_score:
            selected[key] = story
    return list(selected.values())


def _normalise_date(value: Date | str | None) -> Date:
    if value is None:
        return Date.today()
    if isinstance(value, Date):
        return value
    if isinstance(value, str):
        try:
            return Date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("date must use YYYY-MM-DD format") from exc
    raise TypeError("date must be a datetime.date, ISO date string, or None")


def _fetch_bytes(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "AFOS-Media-Factory/2.0"})
    with urlopen(request, timeout=15) as response:
        return response.read()


def _fetch_json(url: str) -> dict[str, Any]:
    return json.loads(_fetch_bytes(url).decode("utf-8"))


__all__ = [
    "FootballIntelligence",
    "FootballIntelligenceError",
    "FootballStory",
]
