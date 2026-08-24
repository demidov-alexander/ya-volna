"""Loading and preparing the liked library (spec steps 3 and 6)."""

from __future__ import annotations

from datetime import datetime

from yavolna.clustering.base import Clusterer
from yavolna.config import AppConfig
from yavolna.errors import ProviderError
from yavolna.library.models import Library, Track
from yavolna.library.normalization import dedupe_tracks
from yavolna.logging import get_logger
from yavolna.providers.base import MusicProvider

log = get_logger(__name__)


def load_library(
    provider: MusicProvider,
    config: AppConfig,
    clusterer: Clusterer,
) -> Library:
    """Fetch liked tracks, apply exclusions, deduplicate and cluster them."""
    raw_tracks = provider.get_liked_tracks()
    if not raw_tracks:
        raise ProviderError(
            "The provider returned no liked tracks.",
            hint="Like a few tracks in Yandex Music, or check that the token belongs "
            "to the right account (`yavolna auth-check`).",
        )

    blocked_tracks = set(config.exclusions.blocked_track_ids)
    blocked_artists = set(config.exclusions.blocked_artist_ids)

    kept: list[Track] = []
    excluded = 0
    for track in raw_tracks:
        if track.provider_track_id in blocked_tracks:
            excluded += 1
            continue
        if blocked_artists.intersection(track.artist_ids):
            excluded += 1
            continue
        kept.append(track)

    deduped = dedupe_tracks(kept, by_content=False)
    duplicates = len(kept) - len(deduped)

    clusterer.assign(deduped)

    liked_at: dict[str, datetime] = {}
    for track in deduped:
        stamp = track.metadata.get("liked_at")
        if isinstance(stamp, str):
            try:
                liked_at[track.provider_track_id] = datetime.fromisoformat(stamp)
            except ValueError:
                continue

    library = Library(tracks=deduped, liked_at=liked_at)
    log.info(
        "Liked library: %d tracks (%d excluded, %d duplicates removed), %d clusters",
        len(library),
        excluded,
        duplicates,
        len(library.by_cluster()),
    )
    return library
