"""Read-only candidate video discovery for football stories."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Callable, Iterable

from pipeline.core import bfi_config
from pipeline.core.content_type_filter import classify_rejected_content, is_rejected_content
from pipeline.core.entity_matching import player_mentioned
from pipeline.core.football_intelligence import FootballStory
from pipeline.core.media_discovery_platform import (
    CacheProvider,
    LocalMediaProvider,
    MediaDiscoveryPlatform,
    OfficialWebsiteProvider,
    RSSProvider,
    YouTubeProvider,
    default_provider_order,
)


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
_EVENT_KEYWORDS = (
    "goal",
    "penalty",
    "save",
    "red card",
    "assist",
    "free kick",
    "own goal",
    "celebration",
    "replay",
    "highlights",
)
_RESULTS_PER_QUERY = 25
_VERIFICATION_POOL_LIMIT = 100
_DEFAULT_MAX_LIVE_SEARCH_CALLS = 10
_CACHE_DIR = Path(".cache/football_media_discovery/youtube_search")
_LOCAL_MEDIA_LIBRARY = Path("data/media_library/football")
_PREVIOUS_QUERY_COUNT = 6
_PREVIOUS_RESULTS_PER_QUERY = 10
_PUBLISHER_SOURCES = (
    "FIFA",
    "UEFA",
    "ESPN FC",
    "Sky Sports Football",
    "BBC Sport",
    "CBS Sports Golazo",
    "FOX Soccer",
    "beIN SPORTS",
    "TNT Sports",
    "OneFootball",
    "The Athletic FC",
    "Guardian Football",
)
_BROADCASTER_SOURCES = (
    "ESPN FC",
    "Sky Sports",
    "BBC Sport",
    "CBS Sports Golazo",
    "FOX Soccer",
    "beIN SPORTS",
    "TNT Sports",
)
_COMPETITION_CHANNELS = {
    "FIFA World Cup": ("FIFA", "FIFA World Cup"),
    "UEFA Champions League": ("UEFA", "Champions League"),
    "Premier League": ("Premier League",),
    "La Liga": ("LALIGA",),
    "Bundesliga": ("Bundesliga",),
    "Serie A": ("Serie A",),
    "MLS": ("Major League Soccer", "MLS"),
}


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
    channel: str = ""


class SearchQuotaUnavailable(RuntimeError):
    pass


class SearchResultCache:
    def __init__(self, directory: Path | str = _CACHE_DIR) -> None:
        self.directory = Path(directory)

    def get(self, query: str) -> list[dict[str, Any]] | None:
        path = self._path(query)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, list):
            return None
        return [item for item in payload if isinstance(item, dict)]

    def set(self, query: str, results: Iterable[dict[str, Any]]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self._path(query).write_text(
            json.dumps(list(results), indent=2),
            encoding="utf-8",
        )

    def _path(self, query: str) -> Path:
        normalised = _normalise_query(query)
        digest = hashlib.sha256(normalised.encode("utf-8")).hexdigest()
        return self.directory / f"{digest}.json"


class MediaDiscovery:
    """Discover and rank video metadata without downloading media."""

    def __init__(
        self,
        candidate_fetcher: Callable[[tuple[str, ...]], Iterable[dict[str, Any]]]
        | None = None,
        candidate_verifier: Callable[[FootballStory, list[CandidateClip]], Iterable[Any]]
        | None = None,
        search_cache: SearchResultCache | None = None,
        max_live_search_calls: int = _DEFAULT_MAX_LIVE_SEARCH_CALLS,
        local_media_dir: Path | str = _LOCAL_MEDIA_LIBRARY,
    ) -> None:
        self._candidate_fetcher = candidate_fetcher or _youtube_candidates
        self._candidate_verifier = candidate_verifier or _verify_candidates
        self._search_cache = search_cache or SearchResultCache()
        self._max_live_search_calls = max(0, int(max_live_search_calls))
        self._local_media_dir = Path(local_media_dir)
        self.diagnostics: dict[str, Any] = {}

    def discover(self, story: FootballStory) -> list[CandidateClip]:
        if not isinstance(story, FootballStory):
            raise TypeError("story must be a FootballStory")

        strategies = _search_strategies(story)
        platform = MediaDiscoveryPlatform(
            (
                CacheProvider(self._search_cache, _RESULTS_PER_QUERY),
                RSSProvider(),
                OfficialWebsiteProvider(),
                LocalMediaProvider(_local_media_candidates, self._local_media_dir),
                YouTubeProvider(
                    self._candidate_fetcher,
                    self._search_cache,
                    _RESULTS_PER_QUERY,
                    self._max_live_search_calls,
                    _is_quota_error,
                ),
            )
        )
        discovery_run = platform.discover(story, strategies)
        raw_candidates = discovery_run.candidates
        counts = discovery_run.query_counts
        origins: dict[str, dict[str, str]] = {}
        for item in raw_candidates:
            video_id = str(item.get("video_id", "")).strip()
            if video_id and video_id not in origins:
                origins[video_id] = {
                    "strategy": str(item.get("strategy", "")),
                    "query": str(item.get("query", "")),
                    "provider": str(item.get("provider", "")),
                }

        deduplicated = _deduplicate(raw_candidates)
        deduplicated, content_type_rejections = _filter_rejected_content(deduplicated)
        if discovery_run.quota_error and not deduplicated:
            self.diagnostics = _empty_diagnostics(
                strategies,
                counts,
                discovery_run.live_search_calls,
                discovery_run.cache_hits,
                discovery_run.skipped_for_budget,
                discovery_run.quota_error,
                self._max_live_search_calls,
            )
            self.diagnostics["provider_order"] = discovery_run.provider_order
            self.diagnostics["providers_used"] = discovery_run.providers_used
            self.diagnostics["reason"] = "No live quota and no local fallback media available."
            return []
        candidate_pool = [_candidate_clip(story, item) for item in deduplicated]
        candidate_pool = sorted(
            candidate_pool,
            key=lambda candidate: (-candidate.relevance_score, -candidate.confidence, candidate.url),
        )[:_VERIFICATION_POOL_LIMIT]
        verification = list(self._candidate_verifier(story, candidate_pool))
        accepted = [
            item for item in verification
            if item.accepted and item.candidate.confidence >= bfi_config.ACCEPTANCE_CONFIDENCE_THRESHOLD
        ]
        used_local_fallback = any(item.get("source") == "local" for item in deduplicated)
        if discovery_run.quota_error and not accepted and not used_local_fallback:
            self.diagnostics = _empty_diagnostics(
                strategies,
                counts,
                discovery_run.live_search_calls,
                discovery_run.cache_hits,
                discovery_run.skipped_for_budget,
                discovery_run.quota_error,
                self._max_live_search_calls,
            )
            self.diagnostics["provider_order"] = discovery_run.provider_order
            self.diagnostics["providers_used"] = discovery_run.providers_used
            self.diagnostics["number_of_raw_candidates"] = len(raw_candidates)
            self.diagnostics["number_after_deduplication"] = len(deduplicated)
            self.diagnostics["number_before_verification"] = len(candidate_pool)
            self.diagnostics["rejected_candidates"] = (
                content_type_rejections + [item.report() for item in verification]
            )
            self.diagnostics["reason"] = "No live quota and no local fallback media available."
            return []
        rejected_candidates = content_type_rejections + [
            item.report() for item in verification if item not in accepted
        ]
        ranked_verifications = sorted(
            accepted,
            key=lambda item: (
                -item.event_score,
                -item.score,
                -item.candidate.relevance_score,
                -item.candidate.confidence,
                item.candidate.title.casefold(),
                item.candidate.url,
            ),
        )
        ranked = [item.candidate for item in ranked_verifications]
        result = ranked
        top_candidates = []
        verification_by_url = {item.candidate.url: item for item in accepted}
        for candidate in result[:10]:
            video_id = candidate.url.partition("v=")[2].partition("&")[0]
            top_candidates.append(
                {
                    "title": candidate.title,
                    "url": candidate.url,
                    "relevance_score": candidate.relevance_score,
                    "confidence": candidate.confidence,
                    "verification_score": verification_by_url[candidate.url].score,
                    "source": candidate.source,
                    **origins.get(video_id, {}),
                }
            )
        chosen_query = top_candidates[0].get("query") if top_candidates else None
        self.diagnostics = {
            "search_queries_used": [query for _strategy, query in strategies],
            "candidates_found_per_query": counts,
            "provider_order": discovery_run.provider_order,
            "default_provider_order": list(default_provider_order()),
            "providers_used": discovery_run.providers_used,
            "number_of_search_queries": len(strategies),
            "max_live_search_calls": self._max_live_search_calls,
            "live_search_calls": discovery_run.live_search_calls,
            "cache_hits": discovery_run.cache_hits,
            "queries_skipped_for_budget": discovery_run.skipped_for_budget,
            "quota_error": discovery_run.quota_error,
            "used_local_fallback": used_local_fallback,
            "local_media_dir": str(self._local_media_dir),
            "number_of_raw_candidates": len(raw_candidates),
            "number_after_deduplication": len(deduplicated),
            "number_rejected_by_content_type": len(content_type_rejections),
            "number_before_verification": len(candidate_pool),
            "number_after_verification": len(accepted),
            "candidate_pool_target": {"minimum": 30, "ideal": "50-100"},
            "previous_max_raw_candidates": _PREVIOUS_QUERY_COUNT * _PREVIOUS_RESULTS_PER_QUERY,
            "expanded_max_raw_candidates": len(strategies) * _RESULTS_PER_QUERY,
            "average_candidates_per_query": round(
                len(raw_candidates) / max(1, len(strategies)), 2
            ),
            "verification_pass_rate": round(
                len(accepted) / max(1, len(deduplicated)), 4
            ),
            "top_10_ranked_candidates": top_candidates,
            "accepted_candidates": top_candidates,
            "rejected_candidates": rejected_candidates,
            "chosen_query": chosen_query,
            "reason": (
                "YouTube quota unavailable; using local fallback media."
                if discovery_run.quota_error and used_local_fallback and accepted
                else
                f"YouTube quota unavailable: {discovery_run.quota_error}"
                if discovery_run.quota_error and not chosen_query
                else
                f"Expanded candidate pool produced verified footage; top query: {chosen_query}"
                if chosen_query
                else "No event-matching candidate passed verification."
            ),
        }
        return result


def _empty_diagnostics(
    strategies: tuple[tuple[str, str], ...],
    counts: list[dict[str, Any]],
    live_search_calls: int,
    cache_hits: int,
    skipped_for_budget: int,
    quota_error: str,
    max_live_search_calls: int,
) -> dict[str, Any]:
    return {
        "search_queries_used": [query for _strategy, query in strategies],
        "candidates_found_per_query": counts,
        "number_of_search_queries": len(strategies),
        "max_live_search_calls": max_live_search_calls,
        "live_search_calls": live_search_calls,
        "cache_hits": cache_hits,
        "queries_skipped_for_budget": skipped_for_budget,
        "quota_error": quota_error,
        "number_of_raw_candidates": 0,
        "number_after_deduplication": 0,
        "number_before_verification": 0,
        "number_after_verification": 0,
        "verification_pass_rate": 0.0,
        "top_10_ranked_candidates": [],
        "accepted_candidates": [],
        "rejected_candidates": [],
        "chosen_query": None,
        "reason": f"YouTube quota unavailable: {quota_error}",
    }


def _normalise_query(query: str) -> str:
    return " ".join(query.casefold().split())


def _is_quota_error(exc: Exception) -> bool:
    text = str(exc).casefold()
    return (
        "quota" in text
        or "ratelimitexceeded" in text
        or "rate limit" in text
        or "http 429" in text
    )


def _event_phrase(story: FootballStory) -> str:
    text = f"{story.title} {story.summary} {story.category} {story.recommended_video_type}".casefold()
    if "own goal" in text:
        return "own goal"
    if "free kick" in text or "free-kick" in text:
        return "free kick"
    category_terms = {
        "Goals": "goal",
        "Red cards": "red card",
        "VAR": "VAR replay",
        "Saves": "penalty save" if "penalty" in text else "save",
        "Comebacks": "goal highlights",
        "Celebrations": "goal celebration",
        "World Cup events": "World Cup highlights",
        "Results": "highlights",
        "Fixtures": "match preview",
    }
    phrase = category_terms.get(story.category)
    if phrase:
        return phrase
    matches = [keyword for keyword in _EVENT_KEYWORDS if keyword in text]
    return " ".join(matches[:2]) or "football highlights"


def _event_search_queries(story: FootballStory) -> tuple[str, ...]:
    return tuple(query for _strategy, query in _search_strategies(story))


def _search_strategies(story: FootballStory) -> tuple[tuple[str, str], ...]:
    event = _event_phrase(story)
    event_terms = _event_synonyms(event)
    player = story.players[0] if story.players else ""
    teams = " ".join(story.teams[:2])
    team_pair = " vs ".join(story.teams[:2])
    competition = story.competition if story.competition != "Football" else ""
    subject = player or teams or competition or "football"
    match_subject = teams or subject
    competition_subject = competition or match_subject
    strategies = []
    source_queries = []
    for source in _COMPETITION_CHANNELS.get(story.competition, ()):
        source_queries.append(("official_competition", (source, competition_subject, event)))
        source_queries.append(("official_competition_replay", (source, event, "replay")))
    for team in story.teams[:2]:
        source_queries.extend(
            (
                ("official_team", (team, "official", event)),
                ("official_team_highlights", (team, "highlights", event)),
                ("official_team_replay", (team, event, "replay")),
            )
        )
    for source in _BROADCASTER_SOURCES:
        source_queries.append(("official_broadcaster", (source, match_subject, event)))
    for source in _PUBLISHER_SOURCES:
        source_queries.append(("verified_publisher", (source, subject, event)))

    base_queries = [
        ("event", (subject, event)),
        ("player_event", (player, event)),
        ("player_competition_event", (player, competition, event)),
        ("teams_event", (teams, event)),
        ("team_pair_event", (team_pair, event)),
        ("competition_event", (competition, event)),
        ("replay", (subject, event, "replay")),
        ("slow_motion", (subject, event, "slow motion")),
        ("alternate_angle", (subject, event, "alternate angle")),
        ("highlights", (match_subject, "highlights", event)),
        ("shorts", (subject, event, "shorts")),
        ("official", (competition_subject, event, "official")),
        ("broadcaster", (competition_subject, event, "broadcast")),
        ("fan_angle", (subject, event, "fan angle")),
    ]
    synonym_queries = []
    for term in event_terms:
        synonym_queries.extend(
            (
                ("event_synonym_player", (player or subject, term)),
                ("event_synonym_match", (team_pair or match_subject, term)),
                ("event_synonym_competition", (competition, term)),
                ("event_synonym_replay", (subject, term, "replay")),
            )
        )
    for strategy, parts in (*base_queries, *synonym_queries, *source_queries):
        query = " ".join(part for part in parts if part).strip()
        if query and all(existing_query != query for _name, existing_query in strategies):
            strategies.append((strategy, query))
    return tuple(strategies)


def _event_synonyms(event: str) -> tuple[str, ...]:
    synonyms = {
        "penalty save": (
            "penalty save",
            "saved penalty",
            "penalty saved",
            "spot kick save",
            "keeper saves penalty",
            "goalkeeper penalty save",
            "penalty miss save",
        ),
        "penalty goal": ("penalty goal", "penalty scored", "spot kick goal"),
        "goal": ("goal", "scores", "scored goal", "finish"),
        "save": ("save", "goalkeeper save", "keeper save", "shot saved"),
        "red card": ("red card", "sent off", "sending off"),
        "yellow card": ("yellow card", "booking", "booked"),
        "free kick": ("free kick", "freekick", "set piece goal"),
        "assist": ("assist", "sets up goal", "key pass"),
        "own goal": ("own goal", "deflection own goal"),
        "celebration": ("celebration", "celebrates", "crowd reaction"),
        "injury": ("injury", "injured", "medical staff"),
        "substitution": ("substitution", "subbed off", "subbed on"),
    }
    return synonyms.get(event, (event,))


def _verify_candidates(story: FootballStory, candidates: list[CandidateClip]) -> Iterable[Any]:
    from pipeline.editing.media_verification import verify_candidates

    return verify_candidates(story, candidates)


def _candidate_clip(
    story: FootballStory,
    candidate: dict[str, Any],
) -> CandidateClip:
    title = str(candidate.get("title", "")).strip()
    description = str(candidate.get("description", "")).strip()
    source = str(candidate.get("source", "youtube")).strip() or "youtube"
    video_id = str(candidate.get("video_id", "")).strip()
    url = str(candidate.get("url", "")).strip()
    duration = int(candidate.get("duration", 0) or 0)
    thumbnail = str(candidate.get("thumbnail", "")).strip()
    channel = str(candidate.get("channel", "")).strip()
    if not title:
        raise ValueError("candidate title is required")
    if source == "youtube":
        if not video_id:
            raise ValueError("youtube candidate video_id is required")
        url = f"https://www.youtube.com/watch?v={video_id}"
    elif not url:
        raise ValueError("local candidate url is required")

    return CandidateClip(
        title=title,
        source=source,
        url=url,
        duration=duration,
        relevance_score=_relevance(story, title, description, duration, channel),
        confidence=_confidence(description, duration, thumbnail),
        thumbnail=thumbnail,
        description=description,
        channel=channel,
    )


def _relevance(
    story: FootballStory,
    title: str,
    description: str,
    duration: int,
    channel: str = "",
) -> float:
    if is_rejected_content(title, description):
        return 0.0

    story_text = " ".join(
        (
            story.title,
            story.summary,
            story.category,
            story.recommended_video_type,
            story.competition,
            *story.teams,
            *story.players,
        )
    )
    story_terms = _terms(story_text)
    title_coverage = len(story_terms & _terms(title)) / max(1, len(story_terms))
    description_coverage = len(story_terms & _terms(description)) / max(1, len(story_terms))

    candidate_text = f"{title} {description}"
    folded_candidate = candidate_text.casefold()
    player_score = _player_entity_score(story.players, candidate_text)
    team_score = _entity_score(story.teams, folded_candidate)
    competition_score = (
        1.0
        if story.competition == "Football"
        else _entity_score((story.competition,), folded_candidate)
    )
    event_score = _event_relevance_score(_event_phrase(story), folded_candidate)
    source_quality = _source_quality_score(title, channel)

    duration_bonus = 0.0
    if duration > 0:
        target = max(1, story.recommended_duration)
        duration_bonus = min(
            bfi_config.DURATION_BONUS_MAX,
            max(0.0, bfi_config.DURATION_BONUS_MAX - abs(duration - target) / target * 2.5),
        )

    score = (
        title_coverage * bfi_config.TITLE_COVERAGE_WEIGHT
        + description_coverage * bfi_config.DESCRIPTION_COVERAGE_WEIGHT
        + source_quality * bfi_config.SOURCE_QUALITY_WEIGHT
        + player_score * bfi_config.PLAYER_WEIGHT
        + team_score * bfi_config.TEAM_WEIGHT
        + competition_score * bfi_config.COMPETITION_WEIGHT
        + event_score * bfi_config.EVENT_WEIGHT
        + duration_bonus
    )
    return round(min(100.0, score), 2)


def _entity_score(entities: Iterable[str], text: str) -> float:
    values = [item.casefold() for item in entities if item]
    if not values:
        return 1.0
    return sum(1 for item in values if item in text) / len(values)


def _player_entity_score(players: Iterable[str], text: str) -> float:
    values = [item for item in players if item]
    if not values:
        return 1.0
    return sum(1 for item in values if player_mentioned(item, text)) / len(values)


def _source_quality_score(title: str, channel: str) -> float:
    """Strongly prefer official match highlights / broadcast footage."""
    if channel and any(
        source.casefold() == channel.casefold() for source in bfi_config.OFFICIAL_BROADCAST_CHANNELS
    ):
        return 1.0
    if any(
        source.casefold() in channel.casefold()
        for source in bfi_config.OFFICIAL_BROADCAST_CHANNELS
        if channel
    ):
        return 0.85
    if any(phrase in title.casefold() for phrase in bfi_config.OFFICIAL_HIGHLIGHT_PHRASES):
        return 0.6
    return 0.0


def _event_relevance_score(event: str, text: str) -> float:
    terms = _terms(event)
    if not terms:
        return 0.0
    if event.casefold() in text:
        return 1.0
    return len(terms & _terms(text)) / len(terms)


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
        key = str(candidate.get("video_id") or candidate.get("url") or "").strip()
        if key and key not in selected:
            selected[key] = candidate
    return list(selected.values())


def _filter_rejected_content(
    candidates: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Reject talking-head/podcast/interview/reaction/news-discussion footage
    before it ever reaches relevance scoring or verification."""
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for candidate in candidates:
        title = str(candidate.get("title", ""))
        description = str(candidate.get("description", ""))
        category = classify_rejected_content(title, description)
        if category:
            rejected.append(
                {
                    "title": title,
                    "url": str(candidate.get("url", "")),
                    "reason": f"rejected: content type '{category}' is not eligible footage",
                    "content_type": category,
                }
            )
        else:
            kept.append(candidate)
    return kept, rejected


def _local_media_candidates(
    story: FootballStory,
    media_dir: Path,
) -> list[dict[str, Any]]:
    if not media_dir.is_dir():
        return []
    candidates = []
    for path in sorted(media_dir.iterdir()):
        if path.suffix.casefold() not in {".mp4", ".mov", ".m4v", ".webm"}:
            continue
        metadata = _local_sidecar(path)
        title = str(metadata.get("title") or path.stem.replace("_", " ")).strip()
        description = str(metadata.get("description") or "").strip()
        if not description:
            description = " ".join(
                str(item)
                for item in (
                    story.competition,
                    *story.players,
                    *story.teams,
                    _event_phrase(story),
                )
                if item
            )
        candidates.append(
            {
                "source": "local",
                "url": str(path),
                "video_id": f"local:{path.name}",
                "title": title,
                "description": description,
                "duration": int(_local_duration(path)),
                "thumbnail": "",
                "channel": str(metadata.get("channel") or "").strip(),
            }
        )
    return candidates


def _local_sidecar(path: Path) -> dict[str, Any]:
    sidecar = path.with_suffix(".json")
    if not sidecar.is_file():
        return {}
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _local_duration(path: Path) -> float:
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "json", str(path),
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except Exception:
        return 0.0
    if result.returncode != 0:
        return 0.0
    try:
        return float(json.loads(result.stdout)["format"]["duration"])
    except (KeyError, ValueError, json.JSONDecodeError):
        return 0.0


def _youtube_candidates(queries: tuple[str, ...]) -> list[dict[str, Any]]:
    from pipeline.sources.youtube_football_source import get_youtube_client

    youtube = get_youtube_client()
    snippets: dict[str, dict[str, Any]] = {}
    for query in queries:
        response = youtube.search().list(
            q=query,
            part="id,snippet",
            maxResults=_RESULTS_PER_QUERY,
            type="video",
            order="relevance",
        ).execute()
        for item in response.get("items", []):
            video_id = item.get("id", {}).get("videoId")
            if video_id and video_id not in snippets and len(snippets) < 100:
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
                "channel": snippet.get("channelTitle", ""),
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


__all__ = [
    "CandidateClip",
    "MediaDiscovery",
    "SearchQuotaUnavailable",
    "SearchResultCache",
]
