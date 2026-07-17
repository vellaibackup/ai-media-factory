"""Provider-agnostic media discovery platform contracts and wiring."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol

from pipeline.core.football_intelligence import FootballStory


RawCandidate = dict[str, Any]
SearchStrategy = tuple[str, str]


class MediaDiscoveryProvider(Protocol):
    name: str
    priority: int
    cost_tier: str
    enabled_by_default: bool

    def discover(self, story: FootballStory, strategies: tuple[SearchStrategy, ...]) -> "ProviderResult":
        """Return raw candidate metadata for a story."""


@dataclass(frozen=True)
class ProviderResult:
    provider: str
    candidates: tuple[RawCandidate, ...] = ()
    query_counts: tuple[dict[str, Any], ...] = ()
    live_calls: int = 0
    cache_hits: int = 0
    skipped_for_budget: int = 0
    quota_error: str = ""
    reason: str = ""


@dataclass
class DiscoveryRun:
    candidates: list[RawCandidate] = field(default_factory=list)
    query_counts: list[dict[str, Any]] = field(default_factory=list)
    live_search_calls: int = 0
    cache_hits: int = 0
    skipped_for_budget: int = 0
    quota_error: str = ""
    providers_used: list[str] = field(default_factory=list)
    provider_order: list[str] = field(default_factory=list)


class MediaDiscoveryPlatform:
    def __init__(self, providers: Iterable[MediaDiscoveryProvider]) -> None:
        self.providers = tuple(
            sorted(
                (provider for provider in providers if provider.enabled_by_default),
                key=lambda provider: provider.priority,
            )
        )
        _validate_provider_order(self.providers)

    def discover(self, story: FootballStory, strategies: tuple[SearchStrategy, ...]) -> DiscoveryRun:
        run = DiscoveryRun(provider_order=[provider.name for provider in self.providers])
        for provider in self.providers:
            result = provider.discover(story, strategies)
            run.providers_used.append(provider.name)
            run.candidates.extend(result.candidates)
            run.query_counts.extend(result.query_counts)
            run.live_search_calls += result.live_calls
            run.cache_hits += result.cache_hits
            run.skipped_for_budget += result.skipped_for_budget
            if result.quota_error:
                run.quota_error = result.quota_error
        return run


class CacheProvider:
    name = "cache"
    priority = 10
    cost_tier = "zero"
    enabled_by_default = True

    def __init__(self, cache: Any, results_per_query: int) -> None:
        self.cache = cache
        self.results_per_query = results_per_query

    def discover(self, story: FootballStory, strategies: tuple[SearchStrategy, ...]) -> ProviderResult:
        candidates: list[RawCandidate] = []
        counts = []
        hits = 0
        for strategy, query in strategies:
            cached = self.cache.get(query)
            if cached is None:
                continue
            batch = cached[: self.results_per_query]
            batch = [
                {**item, "provider": self.name, "strategy": strategy, "query": query}
                for item in batch
            ]
            hits += 1
            candidates.extend(batch)
            counts.append(
                {
                    "provider": self.name,
                    "strategy": strategy,
                    "query": query,
                    "candidates_found": len(batch),
                    "source": "cache",
                }
            )
        return ProviderResult(
            provider=self.name,
            candidates=tuple(candidates),
            query_counts=tuple(counts),
            cache_hits=hits,
        )


class RSSProvider:
    name = "rss"
    priority = 20
    cost_tier = "zero"
    enabled_by_default = True

    def discover(self, story: FootballStory, strategies: tuple[SearchStrategy, ...]) -> ProviderResult:
        return ProviderResult(provider=self.name, reason="RSS provider wired; no media index configured.")


class OfficialWebsiteProvider:
    name = "official_website"
    priority = 30
    cost_tier = "zero"
    enabled_by_default = True

    def discover(self, story: FootballStory, strategies: tuple[SearchStrategy, ...]) -> ProviderResult:
        return ProviderResult(
            provider=self.name,
            reason="Official website provider wired; no site adapters configured.",
        )


class LocalMediaProvider:
    name = "local_media"
    priority = 40
    cost_tier = "zero"
    enabled_by_default = True

    def __init__(self, loader: Callable[[FootballStory, Path], list[RawCandidate]], media_dir: Path) -> None:
        self.loader = loader
        self.media_dir = media_dir

    def discover(self, story: FootballStory, strategies: tuple[SearchStrategy, ...]) -> ProviderResult:
        candidates = tuple(
            {**item, "provider": self.name, "strategy": "local_media", "query": str(self.media_dir)}
            for item in self.loader(story, self.media_dir)
        )
        return ProviderResult(
            provider=self.name,
            candidates=candidates,
            reason=(
                f"Loaded {len(candidates)} local media candidates."
                if candidates
                else "No local media available."
            ),
        )


class YouTubeProvider:
    name = "youtube"
    priority = 50
    cost_tier = "quota"
    enabled_by_default = True

    def __init__(
        self,
        fetcher: Callable[[tuple[str, ...]], Iterable[RawCandidate]],
        cache: Any,
        results_per_query: int,
        max_live_calls: int,
        quota_error_detector: Callable[[Exception], bool],
    ) -> None:
        self.fetcher = fetcher
        self.cache = cache
        self.results_per_query = results_per_query
        self.max_live_calls = max_live_calls
        self.quota_error_detector = quota_error_detector

    def discover(self, story: FootballStory, strategies: tuple[SearchStrategy, ...]) -> ProviderResult:
        candidates: list[RawCandidate] = []
        counts = []
        live_calls = 0
        skipped = 0
        quota_error = ""
        for strategy, query in strategies:
            if self.cache.get(query) is not None:
                continue
            if live_calls >= self.max_live_calls:
                skipped += 1
                counts.append(
                    {
                        "provider": self.name,
                        "strategy": strategy,
                        "query": query,
                        "candidates_found": 0,
                        "source": "budget_skipped",
                    }
                )
                continue
            try:
                batch = [
                    {**item, "provider": self.name, "strategy": strategy, "query": query}
                    for item in list(self.fetcher((query,)))[: self.results_per_query]
                ]
            except Exception as exc:
                if self.quota_error_detector(exc):
                    quota_error = str(exc)
                    break
                raise
            live_calls += 1
            self.cache.set(query, batch)
            candidates.extend(batch)
            counts.append(
                {
                    "provider": self.name,
                    "strategy": strategy,
                    "query": query,
                    "candidates_found": len(batch),
                    "source": "live",
                }
            )
        return ProviderResult(
            provider=self.name,
            candidates=tuple(candidates),
            query_counts=tuple(counts),
            live_calls=live_calls,
            skipped_for_budget=skipped,
            quota_error=quota_error,
        )


def default_provider_order() -> tuple[str, ...]:
    return ("cache", "rss", "official_website", "local_media", "youtube")


def _validate_provider_order(providers: tuple[MediaDiscoveryProvider, ...]) -> None:
    seen_quota_or_paid = False
    for provider in providers:
        if provider.cost_tier != "zero":
            seen_quota_or_paid = True
        elif seen_quota_or_paid:
            raise ValueError("Zero-cost providers must run before quota or paid providers.")


__all__ = [
    "CacheProvider",
    "DiscoveryRun",
    "LocalMediaProvider",
    "MediaDiscoveryPlatform",
    "MediaDiscoveryProvider",
    "OfficialWebsiteProvider",
    "ProviderResult",
    "RSSProvider",
    "YouTubeProvider",
    "default_provider_order",
]
