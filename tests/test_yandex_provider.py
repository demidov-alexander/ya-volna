"""Adapter tests with a stub client: no network, no account (spec section 22)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from yavolna.config import Secrets
from yavolna.errors import AuthenticationError, PlaylistWriteError, ProviderError
from yavolna.providers.yandex_music import YandexMusicProvider

SECRETS = Secrets(yandex_music_token="y0_test-token-value")


def artist(artist_id="1", name="Artist", genres=()):
    return SimpleNamespace(id=artist_id, name=name, genres=list(genres))


def album(album_id="10", title="Album", genre="rock", year=2001):
    return SimpleNamespace(
        id=album_id, title=title, genre=genre, year=year, original_release_year=year
    )


def raw_track(
    track_id="100",
    title="Song",
    duration_ms=210_000,
    available=True,
    artists=None,
    albums=None,
    explicit=False,
):
    return SimpleNamespace(
        id=track_id,
        title=title,
        duration_ms=duration_ms,
        available=available,
        artists=artists if artists is not None else [artist()],
        albums=albums if albums is not None else [album()],
        explicit=explicit,
        content_warning=None,
    )


class StubClient:
    """Minimal stand-in for yandex_music.Client."""

    def __init__(self, **overrides):
        self.calls: list[tuple[str, tuple, dict]] = []
        self._overrides = overrides
        self.playlists: dict[str, SimpleNamespace] = {}

    def __getattr__(self, name):
        if name in self._overrides:
            value = self._overrides[name]

            def call(*args, **kwargs):
                self.calls.append((name, args, kwargs))
                if isinstance(value, Exception):
                    raise value
                if callable(value):
                    return value(*args, **kwargs)
                return value

            return call
        raise AttributeError(name)


def provider_with(**overrides) -> tuple[YandexMusicProvider, StubClient]:
    client = StubClient(**overrides)
    return YandexMusicProvider(SECRETS, client=client), client


# -- auth --------------------------------------------------------------------


def test_check_auth_returns_account_info():
    status = SimpleNamespace(
        account=SimpleNamespace(uid=12345, login="user", display_name="User Name"),
        subscription=SimpleNamespace(
            had_any_subscription=True, auto_renewable=None, non_auto_renewable_remainder=None
        ),
    )
    provider, _ = provider_with(account_status=status)
    account = provider.check_auth()
    assert account.user_id == "12345"
    assert account.login == "user"
    assert account.has_subscription is True
    assert "12345" in account.describe()


def test_check_auth_without_account_is_an_auth_error():
    provider, _ = provider_with(account_status=SimpleNamespace(account=None, subscription=None))
    with pytest.raises(AuthenticationError):
        provider.check_auth()


def test_unauthorized_library_error_maps_to_auth_error():
    class UnauthorizedError(Exception):
        pass

    provider, _ = provider_with(account_status=UnauthorizedError("nope"))
    with pytest.raises(AuthenticationError) as excinfo:
        provider.check_auth()
    assert "auth-check" in (excinfo.value.hint or "")


def test_other_library_errors_map_to_provider_error():
    provider, _ = provider_with(account_status=RuntimeError("boom"))
    with pytest.raises(ProviderError):
        provider.check_auth()


# -- liked tracks ------------------------------------------------------------


def test_liked_tracks_are_normalized_and_batched():
    shorts = [
        SimpleNamespace(id=index, album_id=999, timestamp="2026-01-02T03:04:05+00:00")
        for index in range(1, 4)
    ]
    fetched = []

    def tracks(ids):
        fetched.append(list(ids))
        return [raw_track(track_id=str(track_id)) for track_id in ids]

    provider, _ = provider_with(users_likes_tracks=SimpleNamespace(tracks=shorts), tracks=tracks)
    result = provider.get_liked_tracks()

    assert [track.provider_track_id for track in result] == ["1", "2", "3"]
    assert all(track.liked for track in result)
    assert result[0].duration_seconds == 210
    assert result[0].genres == ("rock",)
    assert result[0].release_year == 2001
    assert result[0].metadata["liked_at"].startswith("2026-01-02")
    assert fetched == [["1", "2", "3"]]


def test_liked_tracks_without_likes_returns_empty():
    provider, _ = provider_with(users_likes_tracks=SimpleNamespace(tracks=[]))
    assert provider.get_liked_tracks() == []


def test_artist_genres_extend_the_album_genre():
    shorts = [SimpleNamespace(id=1, album_id=None, timestamp=None)]
    track = raw_track(artists=[artist(genres=["rusrock", "punk"])], albums=[album(genre="rock")])
    provider, _ = provider_with(
        users_likes_tracks=SimpleNamespace(tracks=shorts), tracks=lambda ids: [track]
    )
    result = provider.get_liked_tracks()
    assert result[0].genres == ("rock", "rusrock", "punk")


def test_album_hint_fills_a_missing_album_id():
    shorts = [SimpleNamespace(id=1, album_id=777, timestamp=None)]
    track = raw_track(track_id="1", albums=[])
    provider, _ = provider_with(
        users_likes_tracks=SimpleNamespace(tracks=shorts), tracks=lambda ids: [track]
    )
    assert provider.get_liked_tracks()[0].album_id == "777"


def test_tracks_without_title_are_skipped():
    shorts = [SimpleNamespace(id=1, album_id=None, timestamp=None)]
    provider, _ = provider_with(
        users_likes_tracks=SimpleNamespace(tracks=shorts),
        tracks=lambda ids: [SimpleNamespace(id=1, title=None)],
    )
    assert provider.get_liked_tracks() == []


# -- history and recommendations --------------------------------------------


def test_missing_history_endpoint_returns_empty():
    provider, _ = provider_with(queues_list=RuntimeError("404"))
    assert provider.get_recent_history() == []


def test_history_is_reconstructed_from_queues():
    queue = SimpleNamespace(
        tracks=[SimpleNamespace(track_id="55:66", id=None)],
        modified="2026-08-01T10:00:00+00:00",
        context=SimpleNamespace(type="playlist"),
    )
    provider, _ = provider_with(
        queues_list=[SimpleNamespace(id="q1")], queue=lambda queue_id: queue
    )
    events = provider.get_recent_history()
    assert [event.provider_track_id for event in events] == ["55"]
    assert events[0].context == "playlist"
    assert events[0].played_at is not None


def test_recommendations_query_each_seed_and_tag_the_source():
    from yavolna.library.models import Track

    seeds = [
        Track(provider="yandex", provider_track_id="s1", title="Seed 1"),
        Track(provider="yandex", provider_track_id="s2", title="Seed 2"),
    ]
    queried: list[str] = []

    def similar(track_id):
        queried.append(track_id)
        return SimpleNamespace(similar_tracks=[raw_track(track_id=f"{track_id}-sim")])

    provider, _ = provider_with(tracks_similar=similar)
    result = provider.get_recommendations(seeds, limit=10)

    assert queried == ["s1", "s2"]
    assert [track.provider_track_id for track in result] == ["s1-sim", "s2-sim"]
    assert result[0].metadata["seed_track_id"] == "s1"
    assert all(not track.liked for track in result)


def test_recommendation_failure_for_one_seed_is_skipped():
    from yavolna.library.models import Track

    def similar(track_id):
        if track_id == "s1":
            raise RuntimeError("no similar tracks")
        return SimpleNamespace(similar_tracks=[raw_track(track_id="ok")])

    provider, _ = provider_with(tracks_similar=similar)
    seeds = [
        Track(provider="yandex", provider_track_id="s1", title="A"),
        Track(provider="yandex", provider_track_id="s2", title="B"),
    ]
    assert [t.provider_track_id for t in provider.get_recommendations(seeds)] == ["ok"]


def test_personal_wave_is_optional():
    provider, _ = provider_with(rotor_station_tracks=RuntimeError("unavailable"))
    assert provider.get_personal_wave() == []


def test_personal_wave_tracks_are_tagged():
    batch = SimpleNamespace(sequence=[SimpleNamespace(track=raw_track(track_id="w1"))])
    provider, _ = provider_with(rotor_station_tracks=batch)
    wave = provider.get_personal_wave()
    assert [track.provider_track_id for track in wave] == ["w1"]
    assert wave[0].metadata["seed_group"] == "personal_wave"


# -- playlists ---------------------------------------------------------------


def raw_playlist(kind=42, title="Daily Chaos", track_count=0, revision=3):
    return SimpleNamespace(
        kind=kind,
        title=title,
        track_count=track_count,
        revision=revision,
        owner=SimpleNamespace(login="user", uid=1),
    )


def test_existing_playlist_is_reused():
    provider, client = provider_with(
        users_playlists_list=[raw_playlist()],
        users_playlists_description=None,
    )
    playlist = provider.get_or_create_playlist("Daily Chaos", description="d")
    assert playlist.provider_playlist_id == "42"
    assert "users_playlists_create" not in {name for name, _, _ in client.calls}


def test_playlist_is_created_when_missing():
    provider, client = provider_with(
        users_playlists_list=[],
        users_playlists_create=raw_playlist(kind=77, title="New"),
        users_playlists_description=None,
    )
    playlist = provider.get_or_create_playlist("New", description="d", visibility="private")
    assert playlist.provider_playlist_id == "77"
    created = [call for call in client.calls if call[0] == "users_playlists_create"]
    assert created[0][2]["visibility"] == "private"


def test_playlist_url_is_derived():
    provider, _ = provider_with(users_playlists_list=[raw_playlist(kind=5)])
    playlist = provider.get_or_create_playlist("Daily Chaos")
    assert playlist.url == "https://music.yandex.ru/users/user/playlists/5"


def test_failed_creation_raises_playlist_write_error():
    provider, _ = provider_with(users_playlists_list=[], users_playlists_create=None)
    with pytest.raises(PlaylistWriteError):
        provider.get_or_create_playlist("New")


def test_replace_tracks_clears_then_inserts_with_revisions():
    from yavolna.library.models import Track

    state = {"revision": 3}
    diffs: list[dict] = []

    def change(kind, diff, revision, **kwargs):
        assert revision == state["revision"]
        diffs.append(json.loads(diff)[0])
        state["revision"] += 1
        return SimpleNamespace(revision=state["revision"])

    provider, _ = provider_with(
        users_playlists=raw_playlist(track_count=2, revision=3),
        users_playlists_change=change,
    )
    tracks = [
        Track(provider="yandex", provider_track_id=str(i), title=f"T{i}", album_id="900")
        for i in range(3)
    ]
    provider.replace_playlist_tracks("42", tracks)

    assert diffs[0] == {"op": "delete", "from": 0, "to": 2}
    assert diffs[1]["op"] == "insert"
    assert diffs[1]["at"] == 0
    assert [item["id"] for item in diffs[1]["tracks"]] == ["0", "1", "2"]


def test_replace_tracks_on_an_empty_playlist_skips_the_delete():
    from yavolna.library.models import Track

    diffs: list[dict] = []

    def change(kind, diff, revision, **kwargs):
        diffs.append(json.loads(diff)[0])
        return SimpleNamespace(revision=revision + 1)

    provider, _ = provider_with(
        users_playlists=raw_playlist(track_count=0), users_playlists_change=change
    )
    provider.replace_playlist_tracks(
        "42", [Track(provider="yandex", provider_track_id="1", title="T", album_id="9")]
    )
    assert [diff["op"] for diff in diffs] == ["insert"]


def test_tracks_without_album_id_are_skipped_on_insert():
    from yavolna.library.models import Track

    diffs: list[dict] = []

    def change(kind, diff, revision, **kwargs):
        diffs.append(json.loads(diff)[0])
        return SimpleNamespace(revision=revision + 1)

    provider, _ = provider_with(
        users_playlists=raw_playlist(track_count=0), users_playlists_change=change
    )
    tracks = [
        Track(provider="yandex", provider_track_id="1", title="A", album_id=None),
        Track(provider="yandex", provider_track_id="2", title="B", album_id="9"),
    ]
    provider.replace_playlist_tracks("42", tracks)
    assert [item["id"] for item in diffs[0]["tracks"]] == ["2"]


def test_replace_tracks_on_a_missing_playlist_is_an_error():
    from yavolna.library.models import Track

    provider, _ = provider_with(users_playlists=RuntimeError("gone"))
    with pytest.raises(PlaylistWriteError, match="not available"):
        provider.replace_playlist_tracks(
            "42", [Track(provider="yandex", provider_track_id="1", title="T", album_id="9")]
        )


def test_failed_diff_is_a_playlist_write_error():
    from yavolna.library.models import Track

    provider, _ = provider_with(
        users_playlists=raw_playlist(track_count=0), users_playlists_change=None
    )
    with pytest.raises(PlaylistWriteError):
        provider.replace_playlist_tracks(
            "42", [Track(provider="yandex", provider_track_id="1", title="T", album_id="9")]
        )


def test_delete_playlist_is_delegated():
    provider, client = provider_with(users_playlists_delete=True)
    provider.delete_playlist("42")
    assert client.calls[0][0] == "users_playlists_delete"
