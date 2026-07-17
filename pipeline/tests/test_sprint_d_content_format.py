"""Regression tests for Sprint D (Broadcast Footage Intelligence content-
format gate).

Reproduces today's failure -- an official-broadcaster prediction/studio clip
outranking genuine match highlights -- with four fixtures: official
broadcaster prediction video, official broadcaster studio show, genuine
match highlight, genuine broadcast footage. Verifies the official-broadcaster
bonus does not apply to low-value-format content, and that genuine highlight/
broadcast content always ranks ahead of prediction/studio content in final
ranking when other quality factors are held equal.
"""

from dataclasses import replace

from pipeline.core.content_format_gate import classify_low_value_format, is_low_value_format
from pipeline.core.media_discovery import CandidateClip, _relevance
from pipeline.core.football_intelligence import FootballStory
from pipeline.editing.professional_sports_editor import rank_candidates, score_candidate


def _story(**overrides):
    defaults = dict(
        title="Top 5 Best Goals of the 2026 FIFA World Cup",
        summary="A countdown of the best individual goals scored so far at the 2026 FIFA World Cup.",
        category="Goals",
        competition="FIFA World Cup",
        teams=(),
        players=(),
        importance_score=85,
        trend_score=80,
        novelty_score=70,
        confidence=0.9,
        recommended_video_type="goal breakdown",
        search_queries=("FIFA World Cup 2026 goals",),
        recommended_duration=24,
        recommended_hook="These are the strikes nobody saw coming.",
    )
    defaults.update(overrides)
    return FootballStory(**defaults)


# ---------------------------------------------------------------------------
# Fixtures reproducing today's failure
# ---------------------------------------------------------------------------

def _official_broadcaster_prediction_video():
    return CandidateClip(
        "Who's Scoring the First Goal for the USMNT? | Score Predictions | FIFA World Cup 2026",
        "youtube",
        "https://www.youtube.com/watch?v=prediction1",
        90,
        90,
        0.95,
        "thumb",
        "Our studio team makes their score predictions ahead of kickoff.",
        channel="FIFA",
    )


def _official_broadcaster_studio_show():
    return CandidateClip(
        "World Cup Tonight: Studio Show Reaction and Tactical Breakdown",
        "youtube",
        "https://www.youtube.com/watch?v=studio1",
        600,
        90,
        0.95,
        "thumb",
        "Live in the studio, our panel breaks down every match.",
        channel="FOX Soccer",
    )


def _genuine_match_highlight():
    return CandidateClip(
        "Best Goals of the Group Stage | FIFA World Cup 2026 Official Highlights",
        "youtube",
        "https://www.youtube.com/watch?v=highlight1",
        185,
        90,
        0.95,
        "thumb",
        "Watch the best goals from the opening stage of the FIFA World Cup 2026.",
        channel="FIFA",
    )


def _genuine_broadcast_footage():
    return CandidateClip(
        "Argentina 3-1 Switzerland | Full Match Highlights",
        "youtube",
        "https://www.youtube.com/watch?v=broadcast1",
        240,
        90,
        0.95,
        "thumb",
        "Broadcast footage from Argentina's FIFA World Cup 2026 win over Switzerland.",
        channel="Sky Sports Football",
    )


# ---------------------------------------------------------------------------
# 1 & 2. Deterministic content-format gate; strongly penalizes each category
# ---------------------------------------------------------------------------

def test_classifies_prediction_format():
    candidate = _official_broadcaster_prediction_video()
    assert classify_low_value_format(candidate.title, candidate.description) == "prediction"


def test_classifies_studio_format():
    candidate = _official_broadcaster_studio_show()
    # Title/description match both "studio" and "breakdown" patterns; the
    # classifier returns the first category in its fixed check order.
    category = classify_low_value_format(candidate.title, candidate.description)
    assert category in ("studio", "breakdown")


def test_each_required_category_is_detected():
    cases = {
        "prediction": "Who will score first? Score Predictions for tonight's match",
        "preview": "Match Preview: Predicted Lineup and Team News",
        "studio": "In the studio with our pundits before kickoff",
        "breakdown": "Tactical Breakdown: how the match was won",
        "recap": "Matchday Recap: everything you missed",
        "discussion": "Full discussion: was that really a red card?",
        "meme": "Best football memes of the tournament",
        "analysis": "In-depth Analysis: tactical patterns from the semi-final",
    }
    for expected_category, title in cases.items():
        assert classify_low_value_format(title) == expected_category, title


def test_genuine_highlight_and_broadcast_titles_are_not_flagged():
    assert not is_low_value_format(
        _genuine_match_highlight().title, _genuine_match_highlight().description
    )
    assert not is_low_value_format(
        _genuine_broadcast_footage().title, _genuine_broadcast_footage().description
    )


def test_score_candidate_strongly_penalizes_prediction_format():
    candidate = _official_broadcaster_prediction_video()
    metadata = {"width": 1920, "height": 1080, "fps": 60, "tbr": 5000}
    quality = score_candidate(candidate, lambda _url: metadata)
    assert "low_value_format=prediction" in quality.reason
    assert quality.score < 50.0  # heavily reduced from what raw technical quality would give


def test_score_candidate_does_not_penalize_genuine_highlight():
    candidate = _genuine_match_highlight()
    metadata = {"width": 1920, "height": 1080, "fps": 60, "tbr": 5000}
    quality = score_candidate(candidate, lambda _url: metadata)
    assert "low_value_format" not in quality.reason


# ---------------------------------------------------------------------------
# 3 & 4. Official broadcaster bonus only applies to eligible content
# ---------------------------------------------------------------------------

def test_official_channel_prediction_video_gets_no_source_quality_bonus():
    story = _story()
    prediction = _official_broadcaster_prediction_video()
    highlight = _genuine_match_highlight()

    prediction_relevance = _relevance(
        story, prediction.title, prediction.description, prediction.duration, channel=prediction.channel,
    )
    highlight_relevance = _relevance(
        story, highlight.title, highlight.description, highlight.duration, channel=highlight.channel,
    )
    # Both are on the same official channel (FIFA); only the genuine
    # highlight should benefit from the official-broadcaster bonus.
    assert highlight_relevance > prediction_relevance


def test_official_channel_studio_show_gets_no_source_quality_bonus():
    story = _story()
    studio = _official_broadcaster_studio_show()
    broadcast = _genuine_broadcast_footage()

    studio_relevance = _relevance(
        story, studio.title, studio.description, studio.duration, channel=studio.channel,
    )
    broadcast_relevance = _relevance(
        story, broadcast.title, broadcast.description, broadcast.duration, channel=broadcast.channel,
    )
    assert broadcast_relevance > studio_relevance


def test_non_official_channel_low_value_format_also_gets_no_bonus():
    # The gate applies regardless of channel -- it isn't only stripping the
    # bonus conditionally on being flagged as official; a non-official
    # prediction video simply never had a bonus to begin with, so the score
    # must not exceed what a plain unofficial-channel candidate would get.
    from pipeline.core.media_discovery import _source_quality_score

    prediction = _official_broadcaster_prediction_video()
    assert _source_quality_score(prediction.title, prediction.channel, prediction.description) == 0.0
    assert _source_quality_score(prediction.title, "RandomUploader123", prediction.description) == 0.0


# ---------------------------------------------------------------------------
# 6. Genuine highlight/broadcast content ranks ahead of prediction/studio
#    content when all other quality factors are similar
# ---------------------------------------------------------------------------

def test_genuine_highlight_ranks_ahead_of_prediction_with_equal_quality_factors():
    prediction = _official_broadcaster_prediction_video()
    highlight = replace(_genuine_match_highlight(), url="https://www.youtube.com/watch?v=highlight-equal")

    # Identical technical quality metadata for both -- the only difference
    # is content format.
    metadata = {
        prediction.url: {"width": 1920, "height": 1080, "fps": 60, "tbr": 5000},
        highlight.url: {"width": 1920, "height": 1080, "fps": 60, "tbr": 5000},
    }
    # Equal verification/relevance/motion scores -- isolating the format
    # gate as the deciding factor, per the "all other quality factors are
    # similar" requirement.
    verification_scores = {prediction.url: 100.0, highlight.url: 100.0}
    motion_scores = {prediction.url: 100.0, highlight.url: 100.0}
    prediction = replace(prediction, relevance_score=90)
    highlight = replace(highlight, relevance_score=90)

    ranked = rank_candidates(
        (prediction, highlight),
        lambda url: metadata[url],
        verification_scores=verification_scores,
        motion_scores=motion_scores,
    )

    assert ranked[0].candidate == highlight
    assert ranked[0].score > ranked[1].score


def test_genuine_broadcast_ranks_ahead_of_studio_show_with_equal_quality_factors():
    studio = _official_broadcaster_studio_show()
    broadcast = replace(_genuine_broadcast_footage(), url="https://www.youtube.com/watch?v=broadcast-equal")

    metadata = {
        studio.url: {"width": 1920, "height": 1080, "fps": 60, "tbr": 5000},
        broadcast.url: {"width": 1920, "height": 1080, "fps": 60, "tbr": 5000},
    }
    verification_scores = {studio.url: 100.0, broadcast.url: 100.0}
    motion_scores = {studio.url: 100.0, broadcast.url: 100.0}
    studio = replace(studio, relevance_score=90)
    broadcast = replace(broadcast, relevance_score=90)

    ranked = rank_candidates(
        (studio, broadcast),
        lambda url: metadata[url],
        verification_scores=verification_scores,
        motion_scores=motion_scores,
    )

    assert ranked[0].candidate == broadcast
    assert ranked[0].score > ranked[1].score
