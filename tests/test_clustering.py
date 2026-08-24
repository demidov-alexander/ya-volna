from __future__ import annotations

from tests.conftest import make_track
from yavolna.clustering.metadata_clusterer import MetadataClusterer


def test_genres_map_to_coarse_clusters():
    tracks = [
        make_track("1", genres=("rock",)),
        make_track("2", genres=("rusrock",)),
        make_track("3", genres=("techno",)),
        make_track("4", genres=("rusrap",)),
        make_track("5", genres=("ambient",)),
    ]
    MetadataClusterer().assign(tracks)
    assert [t.cluster_id for t in tracks] == [
        "rock",
        "russian_rock",
        "techno",
        "hiphop",
        "ambient_melodic",
    ]


def test_unknown_genre_falls_back():
    tracks = [make_track("1", genres=("throat-singing-core",), artist="lonely")]
    MetadataClusterer(fallback_cluster="unsorted").assign(tracks)
    assert tracks[0].cluster_id == "unsorted"


def test_tracks_without_genres_inherit_the_artists_cluster():
    tracks = [
        make_track("1", artist="a1", genres=("metal",)),
        make_track("2", artist="a1", genres=("metal",)),
        make_track("3", artist="a1", genres=()),
    ]
    MetadataClusterer().assign(tracks)
    assert tracks[2].cluster_id == "metal"


def test_configured_map_overrides_the_default():
    tracks = [make_track("1", genres=("rock",))]
    MetadataClusterer(genre_map={"rock": "guitars"}).assign(tracks)
    assert tracks[0].cluster_id == "guitars"


def test_configured_map_accepts_unnormalized_keys():
    tracks = [make_track("1", genres=("Post Rock",))]
    MetadataClusterer(genre_map={"post-rock": "walls_of_sound"}).assign(tracks)
    assert tracks[0].cluster_id == "walls_of_sound"


def test_scheduler_never_needs_cluster_names():
    """Cluster ids stay opaque: any labels must work (spec 13.2)."""
    tracks = [make_track(str(i), genres=(f"g{i}",)) for i in range(5)]
    MetadataClusterer(genre_map={f"g{i}": f"c{i}" for i in range(5)}).assign(tracks)
    assert {t.cluster_id for t in tracks} == {f"c{i}" for i in range(5)}
