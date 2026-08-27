"""Loading and preparing the liked library (spec steps 3 and 6)."""

from __future__ import annotations

from datetime import datetime

from yavolna.clustering.base import Clusterer
from yavolna.config import AppConfig
from yavolna.errors import ProviderError
from yavolna.library.filters import ExclusionFilter
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

    exclusions = ExclusionFilter(config.exclusions)
    kept: list[Track] = exclusions.apply(raw_tracks)

    deduped = dedupe_tracks(kept, by_content=False)
    duplicates = len(kept) - len(deduped)

    # Cluster rules need cluster ids, so they run after the clusterer; the
    # clusterer in turn should not derive artist majorities from tracks that
    # were already excluded.
    clusterer.assign(deduped)
    remaining = exclusions.apply_clusters(deduped)

    liked_at: dict[str, datetime] = {}
    for track in remaining:
        stamp = track.metadata.get("liked_at")
        if isinstance(stamp, str):
            try:
                liked_at[track.provider_track_id] = datetime.fromisoformat(stamp)
            except ValueError:
                continue

    library = Library(tracks=remaining, liked_at=liked_at)
    log.info(
        "Liked library: %d tracks (%d excluded%s, %d duplicates removed), %d clusters",
        len(library),
        exclusions.excluded,
        f" [{exclusions.describe_counts()}]" if exclusions.excluded else "",
        duplicates,
        len(library.by_cluster()),
    )
    return library
