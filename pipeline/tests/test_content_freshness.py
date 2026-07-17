from types import SimpleNamespace
from unittest.mock import patch

from pipeline.core.football_intelligence import FootballStory
from pipeline.core.media_discovery import CandidateClip
from pipeline.editing.content_freshness import (
    SourceVideoHistory,
    filter_fresh_candidates,
)
from pipeline.editing.media_verification import verify_candidate


def _story():
    return FootballStory(
        title="Lionel Messi penalty saved against France",
        summary="Argentina faced France in a FIFA World Cup penalty incident.",
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


def _candidate(video_id, title=None):
    return CandidateClip(
        title or "Lionel Messi penalty saved - Argentina vs France",
        "youtube",
        f"https://www.youtube.com/watch?v={video_id}",
        20,
        95,
        0.95,
        "thumb",
        "Lionel Messi penalty save replay from Argentina vs France at the FIFA World Cup.",
    )


def test_reused_video_is_rejected_by_freshness_gate(tmp_path):
    history = SourceVideoHistory(tmp_path / "history.json")
    stale = _candidate("used-video")
    fresh = _candidate("fresh-video")
    history.record_published(
        source_video_id="used-video",
        source_url=stale.url,
        source_title=stale.title,
        published_video_id="published-short",
        published_url="https://www.youtube.com/watch?v=published-short",
    )

    fresh_candidates, rejected = filter_fresh_candidates([stale, fresh], history)

    assert fresh_candidates == [fresh]
    assert rejected[0].video_id == "used-video"
    assert rejected[0].reason == (
        "rejected: source video used in the last 30 published Shorts"
    )


def test_next_fresh_candidate_is_selected_after_reused_video(tmp_path):
    # Verification now happens once inside MediaDiscovery.discover() (Sprint
    # C): run_football_mvp reads media_discovery.verification_results instead
    # of re-verifying, so the mock provides that dict directly rather than a
    # verify_candidates side_effect.
    story = _story()
    stale = _candidate("used-video")
    fresh = _candidate("fresh-video")
    history = SourceVideoHistory(tmp_path / "history.json")
    history.record_published(
        source_video_id="used-video",
        source_url=stale.url,
        source_title=stale.title,
        published_video_id="published-short",
        published_url="https://www.youtube.com/watch?v=published-short",
    )
    verified_fresh = verify_candidate(story, fresh, {"tags": ["FIFA World Cup"]})

    with (
        patch("pipeline.orchestrator.FootballIntelligence") as intelligence,
        patch("pipeline.orchestrator.MediaDiscovery") as discovery,
        patch("pipeline.orchestrator.assess_candidates") as usability,
        patch("pipeline.orchestrator.rank_candidates") as ranker,
        patch("pipeline.orchestrator.run") as render_and_publish,
    ):
        intelligence.return_value.discover.return_value = [story]
        discovery.return_value.diagnostics = {}
        discovery.return_value.discover.return_value = [stale, fresh]
        discovery.return_value.verification_results = {fresh.url: verified_fresh}
        usability.return_value = [
            SimpleNamespace(
                candidate=fresh,
                usable=True,
                score=100.0,
                local_path=None,
                report=lambda: {
                    "url": fresh.url,
                    "motion_usability_score": 100.0,
                    "usable": True,
                },
            )
        ]
        ranker.return_value = [
            SimpleNamespace(candidate=fresh, report=lambda: {"score": 100.0}),
        ]
        render_and_publish.return_value = {
            "final_duration": 20.0,
            "clip_timeline": [],
            "video_path": "/tmp/final.mp4",
            "youtube_url": "https://www.youtube.com/watch?v=new-short",
            "video_id": "new-short",
            "upload_status": "published",
            "upload_error": None,
            "narration": {},
        }
        from pipeline.orchestrator import run_football_mvp

        result = run_football_mvp(source_history=history)

    assert result["selected_media_candidate"]["url"] == fresh.url
    assert result["source_video_id"] == "fresh-video"
    assert any(
        item.get("video_id") == "used-video"
        and "last 30 published Shorts" in item.get("reason", "")
        for item in result["rejected_candidates"]
    )
    render_and_publish.assert_called_once()
