"""Deterministic batch content strategy for AFOS media production."""

from __future__ import annotations

from dataclasses import dataclass, field

from pipeline.core.video_spec import VideoSpec, ensure_video_spec


_HOOK_TYPES = (
    "curiosity-gap",
    "contrarian",
    "high-stakes",
    "question",
    "reveal",
)
_EMOTIONAL_CURVES = (
    ("curiosity", "anticipation", "tension", "surprise", "resolution"),
    ("intrigue", "discovery", "urgency", "reveal", "confidence"),
    ("surprise", "context", "escalation", "clarity", "engagement"),
)
_CTA_BY_GOAL = {
    "engagement": "comment",
    "followers": "follow",
    "traffic": "learn-more",
}


@dataclass
class ContentStrategy:
    niche: str
    topics: list[str]
    video_specs: list[VideoSpec] = field(default_factory=list)
    batch_size: int = 5
    platform: str = "youtube_shorts"
    monetisation_goal: str = "engagement"
    duration_seconds: int = 20
    beat_count: int = 5

    def __post_init__(self) -> None:
        self.niche = self.niche.strip()
        self.topics = [topic.strip() for topic in self.topics if topic.strip()]
        if not self.niche:
            raise ValueError("ContentStrategy.niche must not be empty")
        if not self.topics and not self.video_specs:
            raise ValueError("ContentStrategy requires topics or video_specs")
        if not 5 <= self.batch_size <= 10:
            raise ValueError("ContentStrategy.batch_size must be between 5 and 10")
        if self.monetisation_goal not in _CTA_BY_GOAL:
            raise ValueError(
                "ContentStrategy.monetisation_goal must be engagement, followers, or traffic"
            )

    def generate_video_specs(self) -> list[VideoSpec]:
        if self.video_specs:
            specs = [ensure_video_spec(spec) for spec in self.video_specs]
            if len(specs) != self.batch_size:
                raise ValueError("video_specs length must match batch_size")
            if len({spec.duration_seconds for spec in specs}) != 1:
                raise ValueError("all batch VideoSpecs must use the same duration")
            if len({spec.beat_count for spec in specs}) != 1:
                raise ValueError("all batch VideoSpecs must use the same beat_count")
            self.video_specs = specs
            return list(specs)

        cta_type = _CTA_BY_GOAL[self.monetisation_goal]
        specs = []
        for index in range(self.batch_size):
            topic = self.topics[index % len(self.topics)]
            specs.append(
                VideoSpec(
                    topic=topic,
                    duration_seconds=self.duration_seconds,
                    platform=self.platform,
                    style=f"{self.niche} {self.monetisation_goal}",
                    hook_type=_HOOK_TYPES[index % len(_HOOK_TYPES)],
                    emotional_curve=list(
                        _EMOTIONAL_CURVES[index % len(_EMOTIONAL_CURVES)]
                    ),
                    beat_count=self.beat_count,
                    avg_clip_length=min(
                        4.0,
                        self.duration_seconds / self.beat_count,
                    ),
                    max_clip_length=4.0,
                    cta_type=cta_type,
                )
            )
        self.video_specs = specs
        return list(specs)


__all__ = ["ContentStrategy"]
