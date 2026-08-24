from __future__ import annotations

from datetime import date

import pytest

from tests.conftest import make_track
from yavolna.config import AppConfig
from yavolna.errors import PlaylistWriteError
from yavolna.library.models import MixResult, PlaylistEntry, SourceType
from yavolna.playlists.writer import PlaylistWriter, raise_if_empty
from yavolna.providers.fake import FakeMusicProvider

TODAY = date(2026, 8, 24)


def result(count: int = 5) -> MixResult:
    entries = [
        PlaylistEntry(
            position=index,
            track=make_track(f"t{index}", cluster="c1"),
            source_type=SourceType.FAMILIAR,
            cluster_id="c1",
        )
        for index in range(count)
    ]
    return MixResult(
        entries=entries, total_duration_seconds=count * 200, target_duration_seconds=1000
    )


def config_for(**playlist) -> AppConfig:
    return AppConfig.model_validate({"playlist": {"name": "Daily Chaos", **playlist}})


def writer_for(provider, repository, **playlist) -> PlaylistWriter:
    return PlaylistWriter(provider, config_for(**playlist), repository)


def test_replace_mode_keeps_one_playlist(provider: FakeMusicProvider, repository):
    writer = writer_for(provider, repository)
    first = writer.publish(result(), today=TODAY)
    second = writer.publish(result(3), today=date(2026, 8, 25))

    assert first.playlist.provider_playlist_id == second.playlist.provider_playlist_id
    assert first.playlist.title == "Daily Chaos"
    assert len(provider.list_playlists()) == 1
    assert len(provider.playlist_tracks(second.playlist.provider_playlist_id)) == 3


def test_daily_new_mode_creates_one_playlist_per_day(provider: FakeMusicProvider, repository):
    writer = writer_for(provider, repository, mode="daily_new")
    first = writer.publish(result(), today=TODAY)
    second = writer.publish(result(), today=date(2026, 8, 25))

    titles = sorted(playlist.title for playlist in provider.list_playlists())
    assert titles == ["Daily Chaos 2026-08-24", "Daily Chaos 2026-08-25"]
    assert first.playlist.provider_playlist_id != second.playlist.provider_playlist_id


def test_second_run_on_the_same_day_reuses_the_dated_playlist(provider, repository):
    writer = writer_for(provider, repository, mode="daily_new")
    first = writer.publish(result(5), today=TODAY)
    second = writer.publish(result(2), today=TODAY)

    assert first.playlist.provider_playlist_id == second.playlist.provider_playlist_id
    assert len(provider.list_playlists()) == 1
    assert len(provider.playlist_tracks(second.playlist.provider_playlist_id)) == 2


def test_custom_daily_title_template(provider, repository):
    writer = writer_for(
        provider,
        repository,
        mode="daily_new",
        daily_name_template="{name} · {date}",
        date_format="%d.%m",
    )
    outcome = writer.publish(result(), today=TODAY)
    assert outcome.playlist.title == "Daily Chaos · 24.08"


def test_stored_reference_is_used_before_a_title_lookup(provider, repository):
    writer = writer_for(provider, repository)
    outcome = writer.publish(result(), today=TODAY)
    playlist_id = outcome.playlist.provider_playlist_id

    # Rename the playlist behind our back: the local reference must still win.
    provider.list_playlists()[0].title = "Renamed by the user"
    again = writer.publish(result(2), today=TODAY)
    assert again.playlist.provider_playlist_id == playlist_id
    assert len(provider.list_playlists()) == 1


def test_deleted_playlist_reference_is_forgotten(provider, repository):
    writer = writer_for(provider, repository)
    outcome = writer.publish(result(), today=TODAY)
    provider.delete_playlist(outcome.playlist.provider_playlist_id)

    again = writer.publish(result(), today=TODAY)
    assert again.playlist.provider_playlist_id != outcome.playlist.provider_playlist_id
    assert repository.find_managed_playlist(provider.name, "")["playlist_id"] == (
        again.playlist.provider_playlist_id
    )


def test_keep_daily_playlists_prunes_the_oldest(provider, repository):
    writer = writer_for(provider, repository, mode="daily_new", keep_daily_playlists=2)
    for day in range(20, 25):
        writer.publish(result(2), today=date(2026, 8, day))

    titles = sorted(playlist.title for playlist in provider.list_playlists())
    assert titles == ["Daily Chaos 2026-08-23", "Daily Chaos 2026-08-24"]
    assert len(repository.managed_playlists(provider.name)) == 2


def test_keep_zero_never_deletes(provider, repository):
    writer = writer_for(provider, repository, mode="daily_new", keep_daily_playlists=0)
    for day in range(20, 25):
        writer.publish(result(2), today=date(2026, 8, day))
    assert len(provider.list_playlists()) == 5


def test_replace_mode_never_prunes(provider, repository):
    writer = writer_for(provider, repository, keep_daily_playlists=1)
    for day in range(20, 25):
        outcome = writer.publish(result(2), today=date(2026, 8, day))
        assert outcome.deleted_playlists == []
    assert len(provider.list_playlists()) == 1


def test_only_managed_playlists_are_deleted(provider, repository):
    manual = provider.get_or_create_playlist("My own precious playlist")
    writer = writer_for(provider, repository, mode="daily_new", keep_daily_playlists=1)
    for day in range(20, 24):
        writer.publish(result(2), today=date(2026, 8, day))

    titles = {playlist.title for playlist in provider.list_playlists()}
    assert manual.title in titles


def test_provider_without_delete_support_is_tolerated(repository):
    provider = FakeMusicProvider(liked_count=10, catalog_count=40, supports_delete=False)
    writer = writer_for(provider, repository, mode="daily_new", keep_daily_playlists=1)
    for day in range(20, 23):
        outcome = writer.publish(result(2), today=date(2026, 8, day))
    assert outcome.deleted_playlists == []
    assert len(provider.list_playlists()) == 3


def test_date_key_and_title_helpers(provider, repository):
    replace = writer_for(provider, repository)
    assert replace.date_key(TODAY) == ""
    assert replace.title_for(TODAY) == "Daily Chaos"

    daily = writer_for(provider, repository, mode="daily_new")
    assert daily.date_key(TODAY) == "2026-08-24"
    assert daily.title_for(TODAY) == "Daily Chaos 2026-08-24"


def test_reuse_disabled_creates_a_new_playlist(provider, repository):
    provider.get_or_create_playlist("Daily Chaos")
    writer = writer_for(provider, repository, reuse_existing_playlist=False)
    outcome = writer.publish(result(), today=TODAY)
    assert outcome.playlist.title == "Daily Chaos (2)"


def test_raise_if_empty():
    with pytest.raises(PlaylistWriteError):
        raise_if_empty(MixResult())
    raise_if_empty(result())
