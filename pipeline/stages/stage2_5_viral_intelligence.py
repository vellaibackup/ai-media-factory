"""Deterministic viral and differentiation planning for short-form video."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from pipeline.core.video_spec import VideoSpec, ensure_video_spec


WORDS_PER_SECOND = 2.7
MIN_BEAT_SECONDS = 1.5
MAX_BEAT_SECONDS = 4.0
HOOK_MAX_WORDS = 12

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+|\n+")
_WORD = re.compile(r"[\w']+", re.UNICODE)
_GENERIC_OPENERS = re.compile(
    r"^(?:today|in this video|welcome|here(?:'s| is)|we(?:'re| are) going to)\b[\s,:-]*",
    re.IGNORECASE,
)
_HIGH_STAKES = frozenset(
    {
        "billion",
        "crash",
        "decisive",
        "final",
        "first",
        "historic",
        "last",
        "record",
        "risk",
        "secret",
        "unexpected",
        "win",
    }
)
_GENERIC_WORDS = frozenset(
    {
        "amazing",
        "best",
        "game",
        "good",
        "great",
        "important",
        "interesting",
        "news",
        "people",
        "thing",
        "things",
        "video",
    }
)
_EMOTION_SEQUENCE = (
    "curiosity",
    "anticipation",
    "tension",
    "surprise",
    "resolution",
)
_NOVELTY_MODES = (
    "counterfactual",
    "hidden-mechanism",
    "micro-detail",
    "myth-reversal",
    "second-order-consequence",
)


def _normalise(value: str, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    normalised = " ".join(value.split()).strip()
    if not normalised:
        raise ValueError(f"{field} must not be empty")
    return normalised


def _extract_script(script_data: dict[str, Any] | str) -> tuple[str, list[str]]:
    if isinstance(script_data, str):
        script = _normalise(script_data, "script_data")
        return script, _sentences(script)
    if not isinstance(script_data, dict):
        raise TypeError("script_data must be a dictionary or string")

    beats = script_data.get("beats")
    if not isinstance(beats, list) or not beats:
        raise ValueError("script_data must contain a non-empty beats list")

    beat_texts: list[str] = []
    for index, beat in enumerate(beats):
        if not isinstance(beat, dict) or "text" not in beat:
            raise ValueError(f"script_data beat {index} must contain text")
        beat_texts.append(_normalise(beat["text"], f"script_data beat {index} text"))
    return " ".join(beat_texts), beat_texts


def _sentences(script: str) -> list[str]:
    sentences = [part.strip() for part in _SENTENCE_BOUNDARY.split(script)]
    return [sentence for sentence in sentences if sentence]


def _words(text: str) -> list[str]:
    return _WORD.findall(text)


def _stable_index(script: str, topic: str, size: int) -> int:
    digest = hashlib.sha256(f"{topic}\0{script}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % size


def _trim_words(text: str, limit: int) -> str:
    words = text.split()
    trimmed = " ".join(words[:limit]).rstrip(".,;:!?")
    return trimmed


def _hook(script: str, spec: VideoSpec) -> str:
    first_sentence = _GENERIC_OPENERS.sub("", _sentences(script)[0]).strip()
    claim = _trim_words(first_sentence, 8)
    topic_label = _trim_words(spec.topic, 4)

    templates = {
        "curiosity-gap": f"The detail everyone missed about {topic_label}: {claim}",
        "contrarian": f"Why the usual {topic_label} story is wrong",
        "high-stakes": f"This changes everything about {topic_label}: {claim}",
        "question": f"What is everyone missing about {topic_label}?",
        "reveal": f"One detail changes the entire {topic_label} story",
    }
    selected = templates.get(
        spec.hook_type,
        f"{spec.hook_type}: the overlooked truth about {topic_label}",
    )
    return _trim_words(selected, HOOK_MAX_WORDS) + "."


def _beat_duration(text: str) -> float:
    spoken_duration = len(_words(text)) / WORDS_PER_SECOND
    return round(min(MAX_BEAT_SECONDS, max(MIN_BEAT_SECONDS, spoken_duration)), 2)


def _retention_structure(
    script: str,
    hook_text: str,
    spec: VideoSpec,
    source_beats: list[str] | None = None,
) -> list[dict[str, Any]]:
    source_beats = source_beats or _sentences(script)
    source_beats = source_beats[: spec.beat_count]
    while len(source_beats) < spec.beat_count:
        source_beats.append(source_beats[-1])
    beats: list[tuple[str, str]] = [("hook", hook_text)]
    roles = ("context", "evidence", "escalation", "reveal", "consequence")
    beats.extend(
        (roles[min(index, len(roles) - 1)], sentence)
        for index, sentence in enumerate(source_beats)
    )

    timeline: list[dict[str, Any]] = []
    cursor = 0.0
    hook_duration = min(1.0, float(spec.duration_seconds))
    content_duration = max(0.0, spec.duration_seconds - hook_duration)
    content_beat_duration = round(content_duration / spec.beat_count, 2)
    for index, (role, text) in enumerate(beats):
        duration = hook_duration if index == 0 else content_beat_duration
        if index == len(beats) - 1:
            duration = round(spec.duration_seconds - cursor, 2)
        end = round(cursor + duration, 2)
        timeline.append(
            {
                "beat": index,
                "role": role,
                "start_seconds": round(cursor, 2),
                "end_seconds": end,
                "duration_seconds": duration,
                "text": text,
                "retention_goal": _retention_goal(role),
            }
        )
        cursor = end
    return timeline


def _retention_goal(role: str) -> str:
    return {
        "hook": "stop the swipe with a specific unresolved claim",
        "context": "supply only the context required to understand the stakes",
        "evidence": "reward attention with concrete proof",
        "escalation": "increase consequence or uncertainty",
        "reveal": "resolve the opening curiosity gap",
        "consequence": "make the reveal personally or culturally relevant",
    }[role]


def _emotional_curve(
    timeline: list[dict[str, Any]],
    emotions: list[str],
) -> list[dict[str, Any]]:
    final_index = max(1, len(timeline) - 1)
    curve: list[dict[str, Any]] = []
    for index, beat in enumerate(timeline):
        position = index / final_index
        emotion_index = min(
            len(emotions) - 1,
            int(position * len(emotions)),
        )
        intensity = 65 + int(30 * (1 - abs(0.72 - position)))
        curve.append(
            {
                "at_seconds": beat["start_seconds"],
                "emotion": emotions[emotion_index],
                "intensity": min(100, intensity),
            }
        )
    return curve


def _differentiation_plan(
    script: str,
    spec: VideoSpec,
    timeline: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    seed = f"{spec.topic}|{spec.style}|{spec.platform}|{spec.hook_type}"
    mode = _NOVELTY_MODES[_stable_index(script, seed, len(_NOVELTY_MODES))]
    novelty = f"For a {spec.style} {spec.platform} treatment: " + {
        "counterfactual": "Frame the story around what would change if the key event had not happened.",
        "hidden-mechanism": "Prioritise the mechanism behind the result instead of repeating the headline.",
        "micro-detail": "Anchor the story to one overlooked visual or factual detail.",
        "myth-reversal": "Open with the common interpretation, then replace it with stronger evidence.",
        "second-order-consequence": "Focus on the consequence that follows the obvious headline impact.",
    }[mode]

    eligible = timeline[1:] or timeline
    contrast_indices = sorted({0, len(eligible) // 2, len(eligible) - 1})
    contrast_types = ("scale-shift", "evidence-snap", "expectation-reversal")
    contrast = [
        {
            "at_seconds": eligible[index]["start_seconds"],
            "type": contrast_types[position],
            "instruction": (
                "Break the current rhythm and introduce a materially different framing."
            ),
        }
        for position, index in enumerate(contrast_indices)
    ]

    distortion = [
        {
            "at_seconds": beat["start_seconds"],
            "source_beat": beat["beat"],
            "shift": "compress context and amplify the causal detail",
            "emphasis_multiplier": 1.35,
        }
        for beat in eligible
        if beat["role"] in {"evidence", "reveal", "consequence"}
    ]
    if not distortion:
        beat = eligible[-1]
        distortion.append(
            {
                "at_seconds": beat["start_seconds"],
                "source_beat": beat["beat"],
                "shift": "treat the final claim as the primary reveal",
                "emphasis_multiplier": 1.25,
            }
        )

    interrupt_styles = ("freeze-frame", "rapid-punch-in", "visual-evidence-overlay")
    interrupts = [
        {
            "at_seconds": point["at_seconds"],
            "style": interrupt_styles[index],
            "duration_seconds": (0.35, 0.25, 0.6)[index],
            "purpose": point["type"],
        }
        for index, point in enumerate(contrast)
    ]
    return novelty, contrast, distortion, interrupts


def _uniqueness_score(script: str, topic: str, novelty_mode: str) -> int:
    words = [word.casefold() for word in _words(script)]
    unique_ratio = len(set(words)) / max(1, len(words))
    specific_tokens = sum(
        token.isdigit() or token in _HIGH_STAKES for token in words
    )
    generic_tokens = sum(token in _GENERIC_WORDS for token in words)
    topic_overlap = len(set(words) & {word.casefold() for word in _words(topic)})

    score = 38
    score += round(unique_ratio * 30)
    score += min(12, specific_tokens * 3)
    score += min(8, topic_overlap * 2)
    score += 8 if novelty_mode else 0
    score -= min(20, generic_tokens * 2)
    return max(0, min(100, score))


def run(
    script_data: dict[str, Any] | str,
    video_spec: VideoSpec | dict[str, Any] | str,
) -> dict[str, Any]:
    """Create a deterministic viral and differentiated content plan."""
    clean_script, source_beats = _extract_script(script_data)
    spec = ensure_video_spec(video_spec)

    hook_text = _hook(clean_script, spec)
    timeline = _retention_structure(clean_script, hook_text, spec, source_beats)
    novelty, contrast, distortion, interrupts = _differentiation_plan(
        clean_script,
        spec,
        timeline,
    )

    return {
        "hook_text": hook_text,
        "retention_structure": timeline,
        "emotional_curve": _emotional_curve(timeline, spec.emotional_curve),
        "novelty_strategy": novelty,
        "contrast_injection_points": contrast,
        "narrative_distortion_points": distortion,
        "visual_pattern_interrupts": interrupts,
        "uniqueness_score": _uniqueness_score(
            clean_script,
            spec.topic,
            novelty,
        ),
    }


__all__ = ["run"]
