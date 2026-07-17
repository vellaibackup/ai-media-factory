from pipeline.core.football_intelligence import FootballStory
from pipeline.core.media_discovery import CandidateClip
from pipeline.editing.media_verification import extract_primary_event, verify_candidate, verify_candidates
from unittest.mock import patch


def _story():
    return FootballStory(
        title="Messi penalty saved for Argentina against France",
        summary="A decisive World Cup penalty save.",
        category="Saves",
        competition="FIFA World Cup",
        teams=("Argentina", "France"),
        players=("Lionel Messi",),
        importance_score=90,
        trend_score=90,
        novelty_score=80,
        confidence=0.9,
        recommended_video_type="decisive-save replay",
        search_queries=("Lionel Messi penalty save",),
        recommended_duration=20,
        recommended_hook="The save changed everything.",
    )


def _candidate(title, description=""):
    return CandidateClip(title, "youtube", f"https://example.com/{title}", 20, 80, 0.95, "thumb", description)


def test_matching_footage_is_accepted():
    candidate = _candidate(
        "Lionel Messi penalty saved - Argentina vs France",
        "FIFA World Cup goalkeeper save replay",
    )
    result = verify_candidate(_story(), candidate, {"tags": ["World Cup", "France"]})
    assert result.accepted is True
    assert result.score == 100.0
    assert result.matched_entities["event_type"] == ["penalty save"]
    assert result.event_score == 100.0


def test_same_player_wrong_event_is_rejected():
    candidate = _candidate(
        "Lionel Messi goal - Argentina vs France",
        "FIFA World Cup goal highlights",
    )
    result = verify_candidate(_story(), candidate)
    assert result.accepted is False
    assert result.score < 75
    assert result.missing_entities["event_type"] == ["penalty save"]
    assert result.event_score == 0.0


def test_extracts_supported_primary_event():
    assert extract_primary_event(_story()) == "penalty save"


def test_goal_title_cannot_be_rescued_by_save_metadata():
    candidate = _candidate(
        "Lionel Messi goals - Argentina vs France",
        "FIFA World Cup goal highlights",
    )
    result = verify_candidate(
        _story(),
        candidate,
        {"tags": ["Lionel Messi", "FIFA World Cup", "penalty save"]},
    )
    assert result.candidate_events == ("goal",)
    assert result.event_score == 0.0
    assert result.accepted is False


def test_generic_highlights_cannot_be_rescued_by_event_description():
    candidate = _candidate(
        "Lionel Messi Argentina vs France FIFA World Cup highlights",
        "Includes the decisive Lionel Messi penalty save.",
    )
    result = verify_candidate(_story(), candidate)
    assert result.accepted is False
    assert result.event_score == 0.0
    assert result.missing_entities["event_type"] == ["penalty save"]


def test_all_failed_candidates_produce_no_acceptance():
    candidates = (_candidate("Unrelated football compilation"),)
    results = verify_candidates(_story(), candidates, lambda _url: {})
    assert not any(item.accepted for item in results)


def test_all_failed_candidates_skip_editing_and_publishing():
    # Verification now happens once, inside MediaDiscovery.discover() (see
    # Sprint C: run_football_mvp no longer re-verifies candidates itself --
    # it reuses media_discovery.verification_results). A candidate that
    # fails verification is therefore never among discover()'s returned
    # candidates; its rejection surfaces via diagnostics, same as any other
    # discovery-time rejection.
    story = _story()
    candidate = _candidate("Unrelated football compilation")
    failed = verify_candidate(story, candidate)
    with (
        patch("pipeline.orchestrator.FootballIntelligence") as intelligence,
        patch("pipeline.orchestrator.MediaDiscovery") as discovery,
        patch("pipeline.orchestrator.run") as render_and_publish,
    ):
        intelligence.return_value.discover.return_value = [story]
        discovery.return_value.discover.return_value = []
        discovery.return_value.diagnostics = {"rejected_candidates": [failed.report()]}
        discovery.return_value.verification_results = {}
        from pipeline.orchestrator import run_football_mvp

        result = run_football_mvp()

    render_and_publish.assert_not_called()
    assert result["upload_status"] == "not_published"
    assert result["accepted_candidate"] is None
    assert any(item["verification_score"] == 0.0 for item in result["rejected_candidates"])
