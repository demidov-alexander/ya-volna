"""Shared fixtures. No test may require a Yandex account (spec section 22)."""

from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest

from yavolna.clustering.metadata_clusterer import MetadataClusterer
from yavolna.config import AppConfig
from yavolna.library.models import Library, Track
from yavolna.persistence.db import connect
from yavolna.persistence.repository import Repository
from yavolna.providers.fake import FakeMusicProvider

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


@pytest.fixture
def now() -> datetime:
    return NOW


@pytest.fixture
def config() -> AppConfig:
    return AppConfig.model_validate(
        {
            "playlist": {"name": "Test Mix", "target_duration_hours": 2},
            "selection": {"minimum_liked_tracks": 5, "random_seed": 42},
            "runtime": {"database_path": ":memory:"},
        }
    )


@pytest.fixture
def provider() -> FakeMusicProvider:
    return FakeMusicProvider(liked_count=120, catalog_count=600, seed=1)


@pytest.fixture
def repository() -> Repository:
    repo = Repository(connect(":memory:"))
    yield repo
    repo.close()


@pytest.fixture
def rng() -> random.Random:
    return random.Random(42)


def make_track(
    track_id: str,
    *,
    title: str | None = None,
    artist: str = "a1",
    album: str = "al1",
    duration: int | None = 200,
    genres: tuple[str, ...] = ("rock",),
    cluster: str | None = None,
    liked: bool = False,
    available: bool = True,
    **metadata: object,
) -> Track:
    return Track(
        provider="fake",
        provider_track_id=track_id,
        title=title or f"Track {track_id}",
        artist_ids=(artist,),
        artist_names=(f"Artist {artist}",),
        album_id=album,
        album_title=f"Album {album}",
        duration_seconds=duration,
        genres=genres,
        release_year=2020,
        liked=liked,
        available=available,
        metadata=dict(metadata),
        cluster_id=cluster,
    )


@pytest.fixture
def track_factory():
    return make_track


@pytest.fixture
def library(provider: FakeMusicProvider) -> Library:
    tracks = provider.get_liked_tracks()
    MetadataClusterer().assign(tracks)
    liked_at = {
        track.provider_track_id: datetime.fromisoformat(track.metadata["liked_at"])
        for track in tracks
        if "liked_at" in track.metadata
    }
    return Library(tracks=tracks, liked_at=liked_at)
