"""In-memory provider used by tests and by `--provider fake` (spec section 22.2).

It generates a deterministic synthetic library so the whole pipeline can run
end to end with no Yandex account and no network access.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from yavolna.errors import ProviderError
from yavolna.library.models import PlaybackEvent, Playlist, Track
from yavolna.providers.base import AccountInfo, MusicProvider

PROVIDER_NAME = "fake"

_GENRE_POOL: tuple[tuple[str, int], ...] = (
    ("rock", 8),
    ("rusrock", 6),
    ("electronics", 7),
    ("techno", 4),
    ("dance", 4),
    ("ambient", 3),
    ("pop", 6),
    ("metal", 4),
    ("rap", 4),
    ("jazz", 2),
)


class FakeMusicProvider(MusicProvider):
    name = PROVIDER_NAME

    def __init__(
        self,
        *,
        liked_count: int = 240,
        catalog_count: int = 900,
        podcast_count: int = 0,
        seed: int = 20260824,
        supports_history: bool = True,
        supports_delete: bool = True,
        fail_recommendations: bool = False,
    ) -> None:
        self._rng = random.Random(seed)
        self._supports_history = supports_history
        self._supports_delete = supports_delete
        self._fail_recommendations = fail_recommendations
        self._catalog: list[Track] = []
        self._playlists: dict[str, Playlist] = {}
        self._playlist_tracks: dict[str, list[Track]] = {}
        self._next_playlist_id = 1000

        self._build_catalog(liked_count=liked_count, catalog_count=catalog_count)
        self._build_non_music(podcast_count)

    # -- catalog construction -------------------------------------------------

    def _build_catalog(self, *, liked_count: int, catalog_count: int) -> None:
        genres = [genre for genre, weight in _GENRE_POOL for _ in range(weight)]
        artist_count = max(12, catalog_count // 8)
        artists = [
            (f"a{index}", f"Artist {index}", self._rng.choice(genres))
            for index in range(1, artist_count + 1)
        ]
        for index in range(1, catalog_count + 1):
            artist_id, artist_name, genre = artists[index % len(artists)]
            album_index = index // 6
            liked = index <= liked_count
            self._catalog.append(
                Track(
                    provider=PROVIDER_NAME,
                    provider_track_id=f"t{index}",
                    title=f"Track {index}",
                    artist_ids=(artist_id,),
                    artist_names=(artist_name,),
                    album_id=f"al{album_index}",
                    album_title=f"Album {album_index}",
                    duration_seconds=self._rng.randint(120, 400),
                    genres=(genre,),
                    release_year=self._rng.randint(1975, 2026),
                    liked=liked,
                    available=index % 97 != 0,
                    metadata={"source": "fake"},
                )
            )
        self._liked_ids = {t.provider_track_id for t in self._catalog if t.liked}

    def _build_non_music(self, count: int) -> None:
        """Liked non-music entries — the kids' podcasts users ask to filter out.

        Appended after the music catalog and built without the rng, so the
        synthetic library stays byte-identical when count is 0.
        """
        for index in range(1, count + 1):
            self._catalog.append(
                Track(
                    provider=PROVIDER_NAME,
                    provider_track_id=f"p{index}",
                    title=f"Kids Podcast Episode {index}",
                    artist_ids=("podcaster1",),
                    artist_names=("Kids Podcast",),
                    album_id="palbum1",
                    album_title="Kids Podcast",
                    duration_seconds=900,
                    genres=("forchildren",),
                    release_year=2026,
                    liked=True,
                    available=True,
                    content_type="podcast",
                    metadata={"source": "fake"},
                )
            )
            self._liked_ids.add(f"p{index}")

    # -- provider interface ---------------------------------------------------

    def check_auth(self) -> AccountInfo:
        return AccountInfo(
            provider=PROVIDER_NAME,
            user_id="fake-uid",
            login="fake",
            display_name="Fake account",
            has_subscription=True,
        )

    def get_liked_tracks(self) -> list[Track]:
        now = datetime.now(UTC)
        tracks: list[Track] = []
        for offset, track in enumerate(t for t in self._catalog if t.liked):
            metadata = dict(track.metadata)
            metadata["liked_at"] = (now - timedelta(days=offset % 400)).isoformat()
            tracks.append(replace(track, metadata=metadata))
        return tracks

    def get_recent_history(self) -> list[PlaybackEvent]:
        if not self._supports_history:
            return []
        now = datetime.now(UTC)
        sample = self._rng.sample(sorted(self._liked_ids), min(25, len(self._liked_ids)))
        return [
            PlaybackEvent(
                provider_track_id=tid, played_at=now - timedelta(hours=index), context="fake"
            )
            for index, tid in enumerate(sample)
        ]

    def get_recommendations(self, seeds: Sequence[Track], *, limit: int = 20) -> list[Track]:
        if self._fail_recommendations:
            raise ProviderError("fake provider was configured to fail recommendations")
        if not seeds:
            return []
        seed_genres = {genre for seed in seeds for genre in seed.genres}
        seed_ids = {seed.provider_track_id for seed in seeds}
        pool = [
            track
            for track in self._catalog
            if track.provider_track_id not in seed_ids
            and (not seed_genres or set(track.genres) & seed_genres)
        ]
        if not pool:
            pool = [t for t in self._catalog if t.provider_track_id not in seed_ids]
        picked = self._rng.sample(pool, min(limit, len(pool)))
        return [self._as_recommendation(track) for track in picked]

    def get_personal_wave(self, *, limit: int = 30) -> list[Track]:
        pool = [t for t in self._catalog if not t.liked]
        picked = self._rng.sample(pool, min(limit, len(pool)))
        return [self._as_recommendation(track) for track in picked]

    def _as_recommendation(self, track: Track) -> Track:
        return replace(
            track,
            metadata=dict(track.metadata),
            liked=track.provider_track_id in self._liked_ids,
        )

    def get_or_create_playlist(
        self, title: str, *, description: str | None = None, visibility: str = "private"
    ) -> Playlist:
        for playlist in self._playlists.values():
            if playlist.title == title:
                return playlist
        self._next_playlist_id += 1
        playlist_id = str(self._next_playlist_id)
        playlist = Playlist(
            provider=PROVIDER_NAME,
            provider_playlist_id=playlist_id,
            title=title,
            track_count=0,
            revision=1,
        )
        self._playlists[playlist_id] = playlist
        self._playlist_tracks[playlist_id] = []
        return playlist

    def replace_playlist_tracks(self, playlist_id: str, tracks: Sequence[Track]) -> Playlist:
        if playlist_id not in self._playlists:
            raise ProviderError(f"unknown playlist {playlist_id}")
        self._playlist_tracks[playlist_id] = list(tracks)
        playlist = self._playlists[playlist_id]
        playlist.track_count = len(tracks)
        playlist.revision = (playlist.revision or 1) + 1
        return playlist

    def list_playlists(self) -> list[Playlist]:
        return list(self._playlists.values())

    def delete_playlist(self, playlist_id: str) -> None:
        if not self._supports_delete:
            raise NotImplementedError("fake provider cannot delete playlists")
        self._playlists.pop(playlist_id, None)
        self._playlist_tracks.pop(playlist_id, None)

    # -- test helpers ---------------------------------------------------------

    def playlist_tracks(self, playlist_id: str) -> list[Track]:
        return list(self._playlist_tracks.get(playlist_id, []))
