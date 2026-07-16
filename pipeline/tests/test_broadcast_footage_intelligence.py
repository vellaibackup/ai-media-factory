"""Regression tests for Broadcast Footage Intelligence (BFI) Phase 1.

Covers: commentary/talking-head/podcast/interview/reaction/news-discussion
rejection, official-highlight preference, player alias matching, misleading
titles, and that scoring is configurable rather than hard-coded.
"""

import importlib

from pipeline.core import bfi_config
from pipeline.core.content_type_filter import classify_rejected_content, is_rejected_content
from pipeline.core.entity_matching import player_mentioned
from pipeline.core.football_intelligence import FootballStory
from pipeline.core.media_discovery import CandidateClip, MediaDiscovery, SearchResultCache, _relevance
from pipeline.editing.media_verification import verify_candidate


def _ronaldo_story(**overrides):
    defaults = dict(
        title="Cristiano Ronaldo scores a stunning goal",
        summary="A stunning strike from Cristiano Ronaldo wins the match.",
        category="Goals",
        competition="Football",
        teams=(),
        players=("Cristiano Ronaldo",),
        importance_score=80,
        trend_score=80,
        novelty_score=70,
        confidence=0.9,
        recommended_video_type="goal breakdown",
        search_queries=("Cristiano Ronaldo goal",),
        recommended_duration=20,
        recommended_hook="The goal that changed everything.",
    )
    defaults.update(overrides)
    return FootballStory(**defaults)


def _messi_story(**overrides):
    defaults = dict(
        title="Lionel Messi scores a stunning goal",
        summary="Messi nets a wonder strike.",
        category="Goals",
        competition="Football",
        teams=(),
        players=("Lionel Messi",),
        importance_score=80,
        trend_score=80,
        novelty_score=70,
        confidence=0.9,
        recommended_video_type="goal breakdown",
        search_queries=("Messi goal",),
        recommended_duration=20,
        recommended_hook="The goal that changed everything.",
    )
    defaults.update(overrides)
    return FootballStory(**defaults)


def _candidate(title, description="", channel="", url="https://example.com/clip"):
    return CandidateClip(title, "youtube", url, 20, 80, 0.95, "thumb", description, channel)


# ---------------------------------------------------------------------------
# 1. Commentary / talking-head / podcast / interview / reaction / news
#    discussion rejection
# ---------------------------------------------------------------------------

def test_rejects_podcast_titles():
    assert classify_rejected_content(
        "The Football Show Podcast EP245: Are Arsenal title contenders?"
    ) == "podcast"


def test_rejects_interview_titles():
    assert classify_rejected_content(
        "Erling Haaland EXCLUSIVE interview after the final"
    ) == "interview"


def test_rejects_press_conference_as_interview():
    assert classify_rejected_content(
        "Guardiola's post-match press conference in full"
    ) == "interview"


def test_rejects_reaction_video_titles():
    assert classify_rejected_content(
        "Fan REACTS to Ronaldo's incredible free kick"
    ) == "reaction_video"


def test_rejects_talking_head_panel_titles():
    assert classify_rejected_content(
        "Pundits panel discussion: Is City still the best team?"
    ) == "talking_head"


def test_rejects_football_news_discussion_titles():
    assert classify_rejected_content(
        "Transfer Talk: the biggest deals of the window | Talking Points debate"
    ) == "news_discussion"


def test_does_not_reject_legitimate_highlight_titles():
    assert not is_rejected_content(
        "Lionel Messi penalty saved - Argentina vs France | FIFA World Cup Official Highlights"
    )
    assert not is_rejected_content(
        "Manchester City 3-1 Arsenal | Goals, celebration and reaction from the stands"
    )


def test_official_highlight_phrase_does_not_excuse_an_explicit_reject_marker():
    # An "Official Highlights" label in the title must not bypass a genuine
    # podcast/interview marker also present in that same title.
    assert classify_rejected_content(
        "Cristiano Ronaldo goal - Official Highlights Podcast EP12"
    ) == "podcast"
    assert classify_rejected_content(
        "Official Highlights: full interview"
    ) == "interview"


def test_verify_candidate_hard_rejects_commentary_content_types():
    story = _ronaldo_story()
    commentary_candidates = [
        _candidate("Cristiano Ronaldo Podcast EP12: his best goals ranked"),
        _candidate("Cristiano Ronaldo full interview on his career"),
        _candidate("Fan reacts to Cristiano Ronaldo's stunning goal"),
        _candidate("Pundits panel discussion on Cristiano Ronaldo's goal"),
        _candidate("Talking Points debate: was Ronaldo's goal offside?"),
    ]
    for candidate in commentary_candidates:
        result = verify_candidate(story, candidate)
        assert result.accepted is False, candidate.title
        assert "content type" in result.reason


# ---------------------------------------------------------------------------
# 2. Official highlight / broadcast footage preference
# ---------------------------------------------------------------------------

def test_official_broadcast_channel_scores_higher_relevance_than_random_upload():
    story = _ronaldo_story()
    title = "Cristiano Ronaldo scores a stunning goal"
    official = _relevance(story, title, "", 20, channel="Sky Sports Football")
    random_upload = _relevance(story, title, "", 20, channel="randomfan99")
    assert official > random_upload


def test_official_highlight_phrase_beats_generic_title_with_no_source_signal():
    story = _ronaldo_story()
    official_phrase = _relevance(
        story,
        "Cristiano Ronaldo scores a stunning goal - Official Highlights",
        "",
        20,
    )
    plain = _relevance(story, "Cristiano Ronaldo scores a stunning goal", "", 20)
    assert official_phrase > plain


def test_official_broadcast_source_is_ranked_first_end_to_end(tmp_path):
    def fetcher(_queries):
        return [
            {
                "video_id": "random",
                "title": "Cristiano Ronaldo scores a stunning goal",
                "description": "",
                "duration": 20,
                "thumbnail": "thumb",
                "channel": "RandomUploader123",
            },
            {
                "video_id": "official",
                "title": "Cristiano Ronaldo scores a stunning goal",
                "description": "",
                "duration": 20,
                "thumbnail": "thumb",
                "channel": "Sky Sports Football",
            },
        ]

    discovery = MediaDiscovery(
        fetcher,
        lambda story, candidates: [verify_candidate(story, item) for item in candidates],
        SearchResultCache(tmp_path / "cache"),
        max_live_search_calls=100,
    )
    candidates = discovery.discover(_ronaldo_story())

    assert candidates
    assert candidates[0].channel == "Sky Sports Football"


# ---------------------------------------------------------------------------
# 3. Player alias matching
# ---------------------------------------------------------------------------

def test_player_alias_matching_nicknames_short_names_and_accents():
    assert player_mentioned("Lionel Messi", "Messi scores a wonder goal") is True
    assert player_mentioned("Cristiano Ronaldo", "CR7 nets a brace") is True
    assert player_mentioned("Karim Benzema", "Benzéma's header wins it") is True
    assert player_mentioned("Vinicius Junior", "Vini Jr through on goal") is True
    assert player_mentioned("Son Heung-min", "Sonny scores a brilliant solo goal") is True
    assert player_mentioned("Random Player Name", "completely unrelated text") is False


def test_short_alias_does_not_false_positive_on_substring_matches():
    # "Son" is a substring of unrelated words -- alias matching must respect
    # word boundaries, same as the last-name fallback already does.
    assert player_mentioned("Son Heung-min", "Johnson scores a brilliant solo goal") is False
    assert player_mentioned("Son Heung-min", "A season to remember for the club") is False


def test_verification_accepts_short_name_title_via_alias():
    story = _messi_story()
    candidate = _candidate(
        "Messi scores an incredible goal - Official Highlights",
        "Official highlights of the match.",
        channel="FIFA",
    )
    result = verify_candidate(story, candidate)
    assert result.accepted is True
    assert result.matched_entities["players"] == ["Lionel Messi"]


def test_verification_rejects_when_alias_genuinely_absent():
    story = _messi_story()
    candidate = _candidate(
        "Random unrelated football goal - Official Highlights",
        "Nothing to do with the story.",
    )
    result = verify_candidate(story, candidate)
    assert result.accepted is False
    assert result.missing_entities["players"] == ["Lionel Messi"]


# ---------------------------------------------------------------------------
# 4. Misleading titles (keyword overlap but wrong content type)
# ---------------------------------------------------------------------------

def test_misleading_title_with_matching_keywords_is_still_rejected():
    story = _ronaldo_story()
    candidate = _candidate(
        "Cristiano Ronaldo scores a stunning goal - Full Interview reaction afterwards",
        "Ronaldo talks about his stunning goal in this exclusive interview.",
    )
    result = verify_candidate(story, candidate)

    # Entities/event alone would have scored a clean accept -- it is the
    # content-type gate, not entity/event matching, that must reject this.
    assert result.score == 100.0
    assert result.event_score == 100.0
    assert result.accepted is False
    assert "interview" in result.reason


# ---------------------------------------------------------------------------
# 5. Description weighting reduced relative to title (and source quality)
# ---------------------------------------------------------------------------

def test_title_match_outweighs_keyword_stuffed_description():
    story = _ronaldo_story()
    strong_title = _relevance(
        story,
        "Cristiano Ronaldo scores a stunning goal",
        "",
        20,
    )
    stuffed_description = _relevance(
        story,
        "Watch this amazing football clip",
        "Cristiano Ronaldo goal Cristiano Ronaldo stunning goal amazing incredible strike",
        20,
    )
    assert strong_title > stuffed_description


def test_description_weight_is_lower_than_title_and_source_quality_weight():
    assert bfi_config.DESCRIPTION_COVERAGE_WEIGHT < bfi_config.TITLE_COVERAGE_WEIGHT
    assert bfi_config.DESCRIPTION_COVERAGE_WEIGHT < bfi_config.SOURCE_QUALITY_WEIGHT


# ---------------------------------------------------------------------------
# 6. Scoring is configurable, not hard-coded
# ---------------------------------------------------------------------------

def test_verification_threshold_is_configurable_via_environment(monkeypatch):
    monkeypatch.setenv("BFI_VERIFICATION_THRESHOLD", "60")
    try:
        importlib.reload(bfi_config)
        assert bfi_config.VERIFICATION_THRESHOLD == 60.0
    finally:
        monkeypatch.delenv("BFI_VERIFICATION_THRESHOLD", raising=False)
        importlib.reload(bfi_config)


def test_verify_candidate_threshold_is_a_parameter_not_hardcoded():
    story = _ronaldo_story()
    candidate = _candidate("Cristiano Ronaldo scores a stunning goal")

    lenient = verify_candidate(story, candidate, threshold=0.0)
    strict = verify_candidate(story, candidate, threshold=100.01)

    assert lenient.accepted is True
    assert strict.accepted is False
