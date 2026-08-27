from __future__ import annotations

import random

import pytest

from tests.conftest import make_track
from yavolna.config import AppConfig
from yavolna.errors import ProviderError
from yavolna.library.models import Library
from yavolna.providers.fake import FakeMusicProvider
from yavolna.recommendation.discovery import fetch_discovery_candidates, filter_discovery_candidates
from yavolna.recommendation.seeds import SeedGroup, build_seed_groups


@pytest.fixture
def small_library() -> Library:
    tracks = [
        make_track("liked1", title="Known Song", artist="a1", cluster="rock", liked=True),
        make_track("liked2", title="Second", artist="a2", cluster="pop", liked=True),
    ]
    return Library(tracks=tracks)


def test_liked_tracks_are_excluded(small_library):
    candidates = [make_track("liked1"), make_track("new1")]
    kept = filter_discovery_candidates(candidates, library=small_library, config=AppConfig())
    assert [t.provider_track_id for t in kept] == ["new1"]


def test_tracks_flagged_liked_are_excluded(small_library):
    candidates = [make_track("new1", liked=True), make_track("new2")]
    kept = filter_discovery_candidates(candidates, library=small_library, config=AppConfig())
    assert [t.provider_track_id for t in kept] == ["new2"]


def test_same_song_under_another_id_is_excluded(small_library):
    candidates = [make_track("other-id", title="Known Song (Remastered)", artist="a1")]
    kept = filter_discovery_candidates(candidates, library=small_library, config=AppConfig())
    assert kept == []


def test_unavailable_candidates_are_excluded(small_library):
    kept = filter_discovery_candidates(
        [make_track("new1", available=False)], library=small_library, config=AppConfig()
    )
    assert kept == []


def test_blocked_tracks_and_artists_are_excluded(small_library):
    config = AppConfig.model_validate(
        {"exclusions": {"blocked_track_ids": ["bad"], "blocked_artist_ids": ["villain"]}}
    )
    candidates = [
        make_track("bad"),
        make_track("byvillain", artist="villain"),
        make_track("fine", artist="hero"),
    ]
    kept = filter_discovery_candidates(candidates, library=small_library, config=config)
    assert [t.provider_track_id for t in kept] == ["fine"]


def test_non_music_candidates_are_excluded(small_library):
    podcast = make_track("cast1", genres=("forchildren",))
    podcast.content_type = "podcast"
    kept = filter_discovery_candidates(
        [podcast, make_track("new1")], library=small_library, config=AppConfig()
    )
    assert [t.provider_track_id for t in kept] == ["new1"]


def test_blocked_genres_are_excluded(small_library):
    config = AppConfig.model_validate({"exclusions": {"blocked_genres": ["forchildren"]}})
    candidates = [make_track("kids", genres=("forchildren",)), make_track("new1")]
    kept = filter_discovery_candidates(candidates, library=small_library, config=config)
    assert [t.provider_track_id for t in kept] == ["new1"]


def test_recently_generated_candidates_are_excluded(small_library):
    kept = filter_discovery_candidates(
        [make_track("new1"), make_track("new2")],
        library=small_library,
        config=AppConfig(),
        recently_generated={"new1"},
    )
    assert [t.provider_track_id for t in kept] == ["new2"]


def test_duplicates_across_seed_groups_are_merged(small_library):
    candidates = [make_track("new1"), make_track("new1"), make_track("new2")]
    kept = filter_discovery_candidates(candidates, library=small_library, config=AppConfig())
    assert [t.provider_track_id for t in kept] == ["new1", "new2"]


def test_failing_seed_group_does_not_abort_the_run(small_library, monkeypatch):
    provider = FakeMusicProvider(liked_count=10, catalog_count=60, seed=3)
    calls = {"count": 0}
    original = provider.get_recommendations

    def flaky(seeds, *, limit=20):
        calls["count"] += 1
        if calls["count"] == 1:
            raise ProviderError("boom")
        return original(seeds, limit=limit)

    monkeypatch.setattr(provider, "get_recommendations", flaky)
    groups = [
        SeedGroup("first", [make_track("s1")]),
        SeedGroup("second", [make_track("s2")]),
    ]
    candidates = fetch_discovery_candidates(provider, groups, small_library, AppConfig())
    assert candidates


def test_seed_group_metadata_is_attached(small_library):
    provider = FakeMusicProvider(liked_count=10, catalog_count=60, seed=4)
    groups = [SeedGroup("cluster:rock", [make_track("s1", genres=("rock",))])]
    config = AppConfig.model_validate({"discovery": {"use_personal_wave": False}})
    candidates = fetch_discovery_candidates(provider, groups, small_library, config)
    assert candidates
    assert all(track.metadata.get("seed_group") == "cluster:rock" for track in candidates)


def test_personal_wave_can_be_disabled(small_library, monkeypatch):
    provider = FakeMusicProvider(liked_count=10, catalog_count=60, seed=5)
    called = {"wave": False}

    def wave(*, limit=30):
        called["wave"] = True
        return []

    monkeypatch.setattr(provider, "get_personal_wave", wave)
    config = AppConfig.model_validate({"discovery": {"use_personal_wave": False}})
    fetch_discovery_candidates(
        provider, [SeedGroup("g", [make_track("s1")])], small_library, config
    )
    assert called["wave"] is False


def test_seed_groups_are_diverse_and_capped(library):
    config = AppConfig.model_validate({"discovery": {"seed_groups_max": 5, "seeds_per_group": 3}})
    groups = build_seed_groups(library, config, random.Random(1))
    assert len(groups) == 5
    assert all(len(group) <= 3 for group in groups)
    # The cap must not drop every non-cluster strategy (spec 12.1).
    assert any(not group.name.startswith("cluster:") for group in groups)


def test_seed_groups_only_use_available_tracks(library):
    for track in library.tracks[:50]:
        track.available = False
    groups = build_seed_groups(library, AppConfig(), random.Random(2))
    unavailable = [t for group in groups for t in group.tracks if not t.available]
    assert unavailable == []


def test_seed_groups_are_deterministic(library):
    first = build_seed_groups(library, AppConfig(), random.Random(9))
    second = build_seed_groups(library, AppConfig(), random.Random(9))
    assert [(g.name, [t.provider_track_id for t in g.tracks]) for g in first] == [
        (g.name, [t.provider_track_id for t in g.tracks]) for g in second
    ]


def test_no_clusters_means_no_seed_groups():
    assert build_seed_groups(Library(tracks=[]), AppConfig(), random.Random(1)) == []
