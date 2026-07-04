"""Canonical, editable configuration for an AFOS video run."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any, Mapping


@dataclass
class VideoSpec:
    topic: str
    duration_seconds: int = 20
    platform: str = "youtube_shorts"
    aspect_ratio: str = "9:16"
    style: str = "fast-paced"
    hook_type: str = "curiosity-gap"
    emotional_curve: list[str] = field(
        default_factory=lambda: [
            "curiosity",
            "anticipation",
            "tension",
            "surprise",
            "resolution",
        ]
    )
    beat_count: int = 5
    avg_clip_length: float = 3.0
    max_clip_length: float = 4.0
    cta_type: str = "comment"

    def __post_init__(self) -> None:
        self.topic = self.topic.strip()
        if not self.topic:
            raise ValueError("VideoSpec.topic must not be empty")
        if self.duration_seconds <= 0:
            raise ValueError("VideoSpec.duration_seconds must be positive")
        if self.beat_count <= 0:
            raise ValueError("VideoSpec.beat_count must be positive")
        if self.avg_clip_length <= 0 or self.max_clip_length <= 0:
            raise ValueError("VideoSpec clip lengths must be positive")
        if self.avg_clip_length > self.max_clip_length:
            raise ValueError("VideoSpec.avg_clip_length cannot exceed max_clip_length")
        if self.duration_seconds > 1 + self.beat_count * self.max_clip_length:
            raise ValueError(
                "VideoSpec duration exceeds beat_count and max_clip_length capacity"
            )
        if not self.emotional_curve:
            raise ValueError("VideoSpec.emotional_curve must not be empty")


def ensure_video_spec(value: VideoSpec | Mapping[str, Any] | str) -> VideoSpec:
    if isinstance(value, VideoSpec):
        return value
    if isinstance(value, str):
        return VideoSpec(topic=value)
    if isinstance(value, Mapping):
        allowed = {item.name for item in fields(VideoSpec)}
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"Unknown VideoSpec fields: {sorted(unknown)}")
        return VideoSpec(**dict(value))
    raise TypeError("video_spec must be a VideoSpec, mapping, or topic string")


__all__ = ["VideoSpec", "ensure_video_spec"]
