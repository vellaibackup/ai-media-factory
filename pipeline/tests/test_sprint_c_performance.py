"""Regression tests for Sprint C (lean performance optimisation).

Covers: no per-candidate yt-dlp call during broad verification, verification
results/metadata preserved and reused (no duplicate verification), long/short
candidates filtered before any usability download, top-K + early-exit
behaviour in the usability gate, and reuse of the usability download during
rendering (no second download of the same source).
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import subprocess

from pipeline.core import bfi_config
from pipeline.core.football_intelligence import FootballStory
from pipeline.core.media_discovery import CandidateClip, MediaDiscovery, SearchResultCache
from pipeline.editing.media_usability import assess_candidates, filter_candidates_by_duration
from pipeline.editing.media_verification import no_deep_metadata_fetch, verify_candidate, verify_candidates


def _story(**overrides):
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


def _candidate(title, url="https://example.com/clip", duration=60, description=""):
    return CandidateClip(title, "youtube", url, duration, 80, 0.95, "thumb", description)


def _local_video(path, duration=5):
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"testsrc2=size=320x240:rate=15:duration={duration}",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


# ---------------------------------------------------------------------------
# 1. No per-candidate yt-dlp call during broad verification
# ---------------------------------------------------------------------------

def test_verify_candidates_default_never_calls_youtube_metadata():
    story = _story()
    candidates = [
        _candidate("Cristiano Ronaldo scores a stunning goal", url=f"https://example.com/{i}")
        for i in range(5)
    ]
    with patch(
        "pipeline.editing.professional_sports_editor.youtube_metadata"
    ) as deep_fetch:
        verify_candidates(story, candidates)
    deep_fetch.assert_not_called()


def test_no_deep_metadata_fetch_performs_no_io():
    # The default fetcher itself must be a pure no-op -- no subprocess call.
    with patch("subprocess.run") as run:
        result = no_deep_metadata_fetch("https://example.com/anything")
    run.assert_not_called()
    assert result == {}


def test_verification_still_works_using_title_and_description_only():
    # _metadata_text() folds candidate.title/description in regardless of the
    # metadata dict, so broad verification with the no-op fetcher must still
    # correctly accept a matching candidate and reject a mismatched one.
    story = _story()
    matching = _candidate("Cristiano Ronaldo scores a stunning goal", url="https://example.com/matching")
    mismatched = _candidate("Unrelated football clip", url="https://example.com/mismatched")
    results = {item.candidate.url: item for item in verify_candidates(story, [matching, mismatched])}
    assert results[matching.url].accepted is True
    assert results[mismatched.url].accepted is False


# ---------------------------------------------------------------------------
# 2. Verification results preserved and reused (no duplicate verification)
# ---------------------------------------------------------------------------

def test_media_discovery_preserves_verification_results_for_reuse(tmp_path):
    story = _story()

    def fetcher(_queries):
        return [
            {
                "video_id": "abc123",
                "title": "Cristiano Ronaldo scores a stunning goal",
                "description": "",
                "duration": 20,
                "thumbnail": "thumb",
                "channel": "FIFA",
            }
        ]

    discovery = MediaDiscovery(
        fetcher,
        None,
        SearchResultCache(tmp_path / "cache"),
        max_live_search_calls=100,
    )
    candidates = discovery.discover(story)

    assert candidates
    winner = candidates[0]
    assert winner.url in discovery.verification_results
    preserved = discovery.verification_results[winner.url]
    assert preserved.accepted is True
    assert preserved.score > 0
    assert preserved.matched_entities["players"] == ["Cristiano Ronaldo"]
    assert preserved.reason


def test_run_football_mvp_does_not_reverify_candidates(tmp_path):
    # run_football_mvp must read media_discovery.verification_results rather
    # than calling verify_candidates a second time -- there is no
    # pipeline.orchestrator.verify_candidates to call anymore.
    import pipeline.orchestrator as orchestrator

    assert not hasattr(orchestrator, "verify_candidates")


# ---------------------------------------------------------------------------
# 3. Long / short candidates filtered before any usability download
# ---------------------------------------------------------------------------

def test_full_match_length_candidate_is_filtered_before_download():
    full_match = _candidate("Full Match Replay", duration=5700)  # 95 minutes
    kept, rejected = filter_candidates_by_duration([full_match], min_duration=20)
    assert kept == []
    assert rejected[0].reason.startswith("rejected: candidate duration 5700s exceeds")


def test_too_short_candidate_is_filtered_before_download():
    too_short = _candidate("Tiny clip", duration=5)
    kept, rejected = filter_candidates_by_duration([too_short], min_duration=20)
    assert kept == []
    assert rejected[0].reason.startswith("rejected: candidate duration 5s is shorter")


def test_legitimate_highlight_length_candidate_is_not_damaged():
    highlight = _candidate("Best Goals of the Group Stage", duration=185)
    kept, rejected = filter_candidates_by_duration([highlight], min_duration=20)
    assert kept == [highlight]
    assert rejected == []


def test_unknown_duration_is_not_penalised():
    unknown = _candidate("Unknown duration clip", duration=0)
    kept, rejected = filter_candidates_by_duration([unknown], min_duration=20)
    assert kept == [unknown]
    assert rejected == []


def test_duration_ceiling_is_configurable():
    borderline = _candidate("Long compilation", duration=1500)
    kept, _ = filter_candidates_by_duration([borderline], min_duration=20, max_duration=1200)
    assert kept == []
    kept, _ = filter_candidates_by_duration([borderline], min_duration=20, max_duration=1800)
    assert kept == [borderline]


# ---------------------------------------------------------------------------
# 4. Top-K / early-exit behaviour in the usability gate
# ---------------------------------------------------------------------------

def test_assess_candidates_stops_after_configured_usable_count(tmp_path):
    paths = []
    for i in range(5):
        path = tmp_path / f"clip_{i}.mp4"
        _local_video(path)
        paths.append(path)
    candidates = [
        CandidateClip(f"Usable clip {i}", "local", str(paths[i]), 20, 80, 0.95, "thumb", "")
        for i in range(5)
    ]

    results = assess_candidates(candidates, tmp_path, stop_after_usable=2)

    usable_count = sum(1 for item in results if item.usable)
    assert usable_count == 2
    # Early exit means not every candidate was even attempted.
    assert len(results) < len(candidates)


def test_one_high_motion_candidate_cannot_stop_evaluation_alone(tmp_path):
    # Sprint C.1 regression: a single candidate scoring very high on decoded
    # motion (e.g. a prediction/studio/reaction clip with moving graphics)
    # must not end the usability gate by itself when more shortlisted
    # candidates remain -- assess_candidates() no longer has any
    # single-candidate "excellent score" early exit at all.
    paths = []
    for i in range(3):
        path = tmp_path / f"clip_{i}.mp4"
        _local_video(path)
        paths.append(path)
    candidates = [
        CandidateClip(f"High motion clip {i}", "local", str(paths[i]), 20, 80, 0.95, "thumb", "")
        for i in range(3)
    ]

    # No excellent_score parameter exists to pass anymore; even with the
    # highest-scoring possible first candidate, stop_after_usable=2 must
    # require a second usable candidate before stopping.
    results = assess_candidates(candidates, tmp_path, stop_after_usable=2)

    assert len(results) >= 2
    assert sum(1 for item in results if item.usable) == 2


def test_two_usable_candidates_allow_early_exit_without_exhausting_list(tmp_path):
    paths = []
    for i in range(5):
        path = tmp_path / f"clip_{i}.mp4"
        _local_video(path)
        paths.append(path)
    candidates = [
        CandidateClip(f"Usable clip {i}", "local", str(paths[i]), 20, 80, 0.95, "thumb", "")
        for i in range(5)
    ]

    results = assess_candidates(candidates, tmp_path, stop_after_usable=2)

    assert sum(1 for item in results if item.usable) == 2
    assert len(results) == 2  # stopped right after the 2nd usable candidate
    assert len(results) < len(candidates)


def test_assess_candidates_has_no_excellent_score_parameter():
    import inspect

    signature = inspect.signature(assess_candidates)
    assert "excellent_score" not in signature.parameters


def test_assess_candidates_without_early_exit_processes_everything(tmp_path):
    # Default behaviour (no stop_after_usable) is unchanged -- every
    # candidate is still processed, preserving prior behaviour for any
    # other caller.
    path = tmp_path / "clip_0.mp4"
    _local_video(path)
    candidates = [
        CandidateClip(f"Clip {i}", "local", str(path), 20, 80, 0.95, "thumb", "")
        for i in range(3)
    ]

    results = assess_candidates(candidates, tmp_path)

    assert len(results) == 3


def test_orchestrator_only_assesses_top_k_candidates(tmp_path):
    # Integration-style check: with more accepted candidates than
    # USABILITY_TOP_K, run_football_mvp's usability call must receive at most
    # USABILITY_TOP_K candidates, not the full accepted pool.
    import pipeline.orchestrator as orchestrator

    story = _story()
    candidates = [
        _candidate(f"Cristiano Ronaldo scores a stunning goal {i}", url=f"https://example.com/{i}", duration=60)
        for i in range(bfi_config.USABILITY_TOP_K + 5)
    ]
    verifications = {c.url: verify_candidate(story, c) for c in candidates}

    with (
        patch("pipeline.orchestrator.FootballIntelligence") as intelligence,
        patch("pipeline.orchestrator.MediaDiscovery") as discovery,
        patch("pipeline.orchestrator.assess_candidates") as usability,
        patch("pipeline.orchestrator.rank_candidates") as ranker,
        patch("pipeline.orchestrator.run") as render_and_publish,
    ):
        intelligence.return_value.discover.return_value = [story]
        discovery.return_value.diagnostics = {}
        discovery.return_value.discover.return_value = candidates
        discovery.return_value.verification_results = verifications
        usability.return_value = [
            SimpleNamespace(
                candidate=candidates[0],
                usable=True,
                score=100.0,
                local_path=None,
                report=lambda: {"usable": True},
            )
        ]
        ranker.return_value = [
            SimpleNamespace(candidate=candidates[0], report=lambda: {"score": 100.0}),
        ]
        render_and_publish.return_value = {
            "final_duration": 20.0,
            "clip_timeline": [],
            "video_path": "/tmp/final.mp4",
            "narration": {},
        }
        orchestrator.run_football_mvp()

    usability.assert_called_once()
    assessed_candidates = list(usability.call_args.args[0])
    assert len(assessed_candidates) <= bfi_config.USABILITY_TOP_K


def test_final_ranking_compares_both_usable_candidates(tmp_path):
    # Sprint C.1 regression: when the usability gate finds two usable
    # candidates (its normal stopping point), the final quality ranking
    # must actually compare both of them -- not settle for whichever was
    # assessed first. This is the concrete guarantee that closes the defect
    # Codex found (a single high-motion clip winning by default).
    import pipeline.orchestrator as orchestrator

    story = _story()
    candidates = [
        _candidate(f"Cristiano Ronaldo scores a stunning goal {i}", url=f"https://example.com/{i}", duration=60)
        for i in range(3)
    ]
    verifications = {c.url: verify_candidate(story, c) for c in candidates}

    with (
        patch("pipeline.orchestrator.FootballIntelligence") as intelligence,
        patch("pipeline.orchestrator.MediaDiscovery") as discovery,
        patch("pipeline.orchestrator.assess_candidates") as usability,
        patch("pipeline.orchestrator.rank_candidates") as ranker,
        patch("pipeline.orchestrator.run") as render_and_publish,
    ):
        intelligence.return_value.discover.return_value = [story]
        discovery.return_value.diagnostics = {}
        discovery.return_value.discover.return_value = candidates
        discovery.return_value.verification_results = verifications
        # Simulate the usability gate's normal stopping point: 2 usable
        # candidates found (the 3rd was never even assessed).
        usability.return_value = [
            SimpleNamespace(
                candidate=candidates[0], usable=True, score=95.0, local_path=None,
                report=lambda: {"usable": True},
            ),
            SimpleNamespace(
                candidate=candidates[1], usable=True, score=80.0, local_path=None,
                report=lambda: {"usable": True},
            ),
        ]
        ranker.return_value = [
            SimpleNamespace(candidate=candidates[1], score=100.0, reason="best", report=lambda: {"score": 100.0}),
            SimpleNamespace(candidate=candidates[0], score=90.0, reason="second", report=lambda: {"score": 90.0}),
        ]
        render_and_publish.return_value = {
            "final_duration": 20.0,
            "clip_timeline": [],
            "video_path": "/tmp/final.mp4",
            "narration": {},
        }
        orchestrator.run_football_mvp()

    ranker.assert_called_once()
    ranked_candidates = list(ranker.call_args.args[0])
    assert len(ranked_candidates) == 2
    assert {c.url for c in ranked_candidates} == {candidates[0].url, candidates[1].url}


# ---------------------------------------------------------------------------
# 5. Selected usability download reused during rendering (no 2nd download)
# ---------------------------------------------------------------------------

def test_selected_media_is_reused_not_redownloaded_for_rendering(tmp_path):
    import pipeline.orchestrator as orchestrator

    story = _story()
    candidate = _candidate("Cristiano Ronaldo scores a stunning goal", duration=60)
    verification = verify_candidate(story, candidate)
    downloaded_path = tmp_path / "candidate_0.mp4"
    downloaded_path.write_bytes(b"fake video bytes")

    with (
        patch("pipeline.orchestrator.FootballIntelligence") as intelligence,
        patch("pipeline.orchestrator.MediaDiscovery") as discovery,
        patch("pipeline.orchestrator.assess_candidates") as usability,
        patch("pipeline.orchestrator.rank_candidates") as ranker,
        patch("pipeline.orchestrator.run") as render_and_publish,
    ):
        intelligence.return_value.discover.return_value = [story]
        discovery.return_value.diagnostics = {}
        discovery.return_value.discover.return_value = [candidate]
        discovery.return_value.verification_results = {candidate.url: verification}
        usability.return_value = [
            SimpleNamespace(
                candidate=candidate,
                usable=True,
                score=100.0,
                local_path=downloaded_path,
                report=lambda: {"usable": True},
            )
        ]
        ranker.return_value = [
            SimpleNamespace(candidate=candidate, report=lambda: {"score": 100.0}),
        ]
        render_and_publish.return_value = {
            "final_duration": 20.0,
            "clip_timeline": [],
            "video_path": "/tmp/final.mp4",
            "narration": {},
        }
        orchestrator.run_football_mvp()

    render_and_publish.assert_called_once()
    _, kwargs = render_and_publish.call_args
    render_candidate = kwargs["media_candidate"]
    assert render_candidate.source == "local"
    assert render_candidate.url == str(downloaded_path)


def test_local_source_candidate_is_not_rewrapped():
    # A candidate that was already local (e.g. LocalMediaProvider fallback)
    # must not be modified -- there's nothing to "reuse a download" for.
    import pipeline.orchestrator as orchestrator

    story = _story()
    local_candidate = CandidateClip(
        "Local fallback clip", "local", "/some/local/path.mp4", 60, 80, 0.95, "thumb", "",
    )
    verification = verify_candidate(story, local_candidate)

    with (
        patch("pipeline.orchestrator.FootballIntelligence") as intelligence,
        patch("pipeline.orchestrator.MediaDiscovery") as discovery,
        patch("pipeline.orchestrator.assess_candidates") as usability,
        patch("pipeline.orchestrator.rank_candidates") as ranker,
        patch("pipeline.orchestrator.run") as render_and_publish,
    ):
        intelligence.return_value.discover.return_value = [story]
        discovery.return_value.diagnostics = {}
        discovery.return_value.discover.return_value = [local_candidate]
        discovery.return_value.verification_results = {local_candidate.url: verification}
        usability.return_value = [
            SimpleNamespace(
                candidate=local_candidate,
                usable=True,
                score=100.0,
                local_path=Path(local_candidate.url),
                report=lambda: {"usable": True},
            )
        ]
        ranker.return_value = [
            SimpleNamespace(candidate=local_candidate, report=lambda: {"score": 100.0}),
        ]
        render_and_publish.return_value = {
            "final_duration": 20.0,
            "clip_timeline": [],
            "video_path": "/tmp/final.mp4",
            "narration": {},
        }
        orchestrator.run_football_mvp()

    _, kwargs = render_and_publish.call_args
    render_candidate = kwargs["media_candidate"]
    assert render_candidate.url == "/some/local/path.mp4"
    assert render_candidate.source == "local"
