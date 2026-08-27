"""Exclusion rules: ids, content types, genres, clusters (spec section 38)."""

from __future__ import annotations

import pytest

from tests.conftest import make_track
from yavolna.clustering.metadata_clusterer import MetadataClusterer
from yavolna.config import AppConfig, ExclusionsConfig
from yavolna.library.filters import ExclusionFilter, genre_key
from yavolna.library.loader import load_library
from yavolna.providers.fake import FakeMusicProvider


def filter_for(**exclusions) -> ExclusionFilter:
    return ExclusionFilter(ExclusionsConfig.model_validate(exclusions))


def podcast(track_id: str = "p1", **kwargs):
    track = make_track(track_id, genres=("forchildren",), **kwargs)
    track.content_type = "podcast"
    return track


def test_podcasts_are_excluded_by_default():
    excluder = filter_for()
    assert excluder.metadata_reason(podcast()) == "content_type"
    assert excluder.metadata_reason(make_track("t1")) is None


def test_audiobooks_are_excluded_by_default():
    track = make_track("t1")
    track.content_type = "audiobook"
    assert filter_for().metadata_reason(track) == "content_type"


def test_content_type_check_can_be_disabled():
    excluder = filter_for(allowed_content_types=[])
    assert excluder.metadata_reason(podcast()) is None


def test_extra_content_types_can_be_allowed():
    excluder = filter_for(allowed_content_types=["music", "Podcast"])
    assert excluder.metadata_reason(podcast()) is None


@pytest.mark.parametrize("blocked", ["forchildren", "For Children", "forchildrengenre"])
def test_blocked_genres_are_matched_after_normalization(blocked):
    excluder = filter_for(allowed_content_types=[], blocked_genres=[blocked])
    track = make_track("t1", genres=("ForChildrenGenre",))
    assert excluder.metadata_reason(track) == "genre"
    assert excluder.metadata_reason(make_track("t2", genres=("rock",))) is None


def test_blocked_genre_matches_any_of_the_track_genres():
    excluder = filter_for(blocked_genres=["podcasts"])
    track = make_track("t1", genres=("rock", "podcasts"))
    assert excluder.metadata_reason(track) == "genre"


def test_blocked_ids_and_artists_still_apply():
    excluder = filter_for(blocked_track_ids=["t1"], blocked_artist_ids=["a9"])
    assert excluder.metadata_reason(make_track("t1")) == "blocked_track_id"
    assert excluder.metadata_reason(make_track("t2", artist="a9")) == "blocked_artist_id"


def test_clusters_are_only_checked_after_assignment():
    excluder = filter_for(blocked_clusters=["dance"])
    unassigned = make_track("t1", genres=("dance",))
    assert excluder.metadata_reason(unassigned) is None
    assert excluder.cluster_reason(unassigned) is None

    MetadataClusterer().assign([unassigned])
    assert unassigned.cluster_id == "dance"
    assert excluder.cluster_reason(unassigned) == "cluster"


def test_apply_counts_every_reason():
    excluder = filter_for(blocked_track_ids=["t1"], blocked_genres=["jazz"])
    kept = excluder.apply(
        [
            make_track("t1"),
            podcast("p1"),
            podcast("p2"),
            make_track("t2", genres=("jazz",)),
            make_track("t3"),
        ]
    )
    assert [t.provider_track_id for t in kept] == ["t3"]
    assert excluder.counts == {"blocked_track_id": 1, "content_type": 2, "genre": 1}
    assert excluder.excluded == 4
    assert "content_type=2" in excluder.describe_counts()


def test_apply_clusters_keeps_everything_when_nothing_is_blocked():
    excluder = filter_for()
    tracks = [make_track("t1", cluster="rock"), make_track("t2", cluster="dance")]
    assert excluder.apply_clusters(tracks) == tracks
    assert excluder.excluded == 0


def test_genre_key_drops_the_provider_suffix():
    assert genre_key("PhonkGenre") == "phonk"
    assert genre_key("genre") == "genre"


def test_library_drops_podcasts_by_default():
    provider = FakeMusicProvider(liked_count=40, catalog_count=120, podcast_count=5, seed=7)
    library = load_library(provider, AppConfig(), MetadataClusterer())
    assert all(track.content_type == "music" for track in library.tracks)
    assert not [t for t in library.tracks if t.provider_track_id.startswith("p")]


def test_library_keeps_podcasts_when_the_user_allows_them():
    provider = FakeMusicProvider(liked_count=40, catalog_count=120, podcast_count=5, seed=7)
    config = AppConfig.model_validate({"exclusions": {"allowed_content_types": []}})
    library = load_library(provider, config, MetadataClusterer())
    assert [t for t in library.tracks if t.content_type == "podcast"]


def test_library_drops_a_blocked_cluster():
    provider = FakeMusicProvider(liked_count=60, catalog_count=200, seed=8)
    config = AppConfig.model_validate({"exclusions": {"blocked_clusters": ["dance"]}})
    library = load_library(provider, config, MetadataClusterer())
    assert "dance" not in library.by_cluster()
    assert len(library) > 0
