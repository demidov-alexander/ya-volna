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


def test_real_yandex_genre_codes_seen_in_the_wild():
    """Codes verified against a real library; phonk arrives as 'phonkgenre'."""
    tracks = [
        make_track("1", genres=("phonkgenre",)),
        make_track("2", genres=("electronics",)),
        make_track("3", genres=("house",)),
        make_track("4", genres=("relax",)),
        make_track("5", genres=("lounge",)),
        make_track("6", genres=("classical",)),
        make_track("7", genres=("epicmetal",)),
        make_track("8", genres=("folkmetal",)),
        make_track("9", genres=("rusrap",)),
        make_track("10", genres=("alternative",)),
    ]
    MetadataClusterer().assign(tracks)
    assert [t.cluster_id for t in tracks] == [
        "hiphop",
        "electronic",
        "techno",
        "ambient_melodic",
        "ambient_melodic",
        "ambient_melodic",
        "metal",
        "metal",
        "hiphop",
        "rock",
    ]
