from __future__ import annotations

from tests.conftest import make_track
from yavolna.library.normalization import (
    content_key,
    dedupe_tracks,
    normalize_genre,
    normalize_text,
)


def test_normalize_text_strips_noise():
    assert normalize_text("Song (feat. Someone)") == "song"
    assert normalize_text("Song - Remastered 2011") == "song"
    assert normalize_text("Sóng!!  Two") == "song two"
    assert normalize_text("ПЕСНЯ, Раз") == "песня раз"


def test_content_key_matches_the_same_song_on_two_albums():
    single = make_track("1", title="Wind of Change", album="al1")
    compilation = make_track("2", title="Wind of Change (Remastered 2015)", album="al2")
    assert content_key(single) == content_key(compilation)


def test_dedupe_by_provider_id():
    tracks = [make_track("1"), make_track("1"), make_track("2")]
    assert [t.provider_track_id for t in dedupe_tracks(tracks, by_content=False)] == ["1", "2"]


def test_dedupe_by_content_keeps_the_first_occurrence():
    tracks = [
        make_track("1", title="Song"),
        make_track("2", title="Song (feat. Guest)"),
        make_track("3", title="Other"),
    ]
    assert [t.provider_track_id for t in dedupe_tracks(tracks)] == ["1", "3"]


def test_dedupe_by_content_can_be_disabled():
    tracks = [make_track("1", title="Song"), make_track("2", title="Song")]
    assert len(dedupe_tracks(tracks, by_content=False)) == 2


def test_normalize_genre():
    assert normalize_genre(" Rus-Rock ") == "rusrock"
    assert normalize_genre("post_rock") == "postrock"
