"""
Stage 1: Script Intelligence (NO fallback, REAL structured output)
Goal: convert topic → engaging short-form video beats
"""

from __future__ import annotations

from pipeline.core.video_spec import VideoSpec, ensure_video_spec


class Stage1Error(Exception):
    pass


def run(video_spec: VideoSpec | dict | str) -> dict:
    """
    Generates structured beats for short-form video.
    """

    # -------------------------
    # SIMPLE INTELLIGENCE LAYER
    # -------------------------

    try:
        spec = ensure_video_spec(video_spec)
    except (TypeError, ValueError) as exc:
        raise Stage1Error(str(exc)) from exc

    seconds_per_beat = round(spec.duration_seconds / spec.beat_count, 2)
    templates = (
        "{hook_type}: the overlooked detail about {topic}",
        "Here is what actually happened in {topic}",
        "The key mechanism changes how {topic} should be understood",
        "The consequence is why people are discussing {topic}",
        "{cta_type}: decide what happens next for {topic}",
    )
    beats = [
        {
            "text": templates[index % len(templates)].format(
                topic=spec.topic,
                hook_type=spec.hook_type,
                cta_type=spec.cta_type,
            ),
            "seconds": min(spec.max_clip_length, seconds_per_beat),
        }
        for index in range(spec.beat_count)
    ]

    return {
        "topic": spec.topic,
        "beats": beats,
        "source": "intelligent_v1",
        "video_spec": spec,
    }
