"""Content exclusions shared by both candidate sources (spec section 38).

Provider-neutral: the rules are expressed over the internal `Track` model, so
the same filter guards the liked library and the discovery pool.
"""

from __future__ import annotations

from collections.abc import Iterable

from yavolna.config import ExclusionsConfig
from yavolna.library.models import Track
from yavolna.library.normalization import normalize_genre

#: Reason keys reported in `ExclusionFilter.counts`.
TRACK_ID = "blocked_track_id"
ARTIST_ID = "blocked_artist_id"
CONTENT_TYPE = "content_type"
GENRE = "genre"
CLUSTER = "cluster"


def genre_key(genre: str) -> str:
    """Normalize a genre for comparison.

    Yandex Music returns several codes in both forms — `phonk` and `phonkgenre`
    — so the trailing suffix is dropped the same way the clusterer drops it.
    """
    key = normalize_genre(genre)
    if key.endswith("genre") and len(key) > len("genre"):
        key = key[: -len("genre")]
    return key


class ExclusionFilter:
    """Drops what the user never wants to hear.

    Two passes, because two of the rules answer different questions. Ids,
    content types and genres are provider metadata and can be applied as soon
    as tracks arrive; a cluster is YaVolna's own grouping and only exists after
    the clusterer has run.
    """

    def __init__(self, exclusions: ExclusionsConfig) -> None:
        self._track_ids = set(exclusions.blocked_track_ids)
        self._artist_ids = set(exclusions.blocked_artist_ids)
        self._genres = {genre_key(genre) for genre in exclusions.blocked_genres}
        self._clusters = set(exclusions.blocked_clusters)
        self._content_types = set(exclusions.allowed_content_types)
        self.counts: dict[str, int] = {}

    @property
    def excluded(self) -> int:
        return sum(self.counts.values())

    def metadata_reason(self, track: Track) -> str | None:
        """Why this track is excluded on provider metadata alone, or None."""
        if track.provider_track_id in self._track_ids:
            return TRACK_ID
        if self._artist_ids.intersection(track.artist_ids):
            return ARTIST_ID
        if self._content_types and track.content_type.casefold() not in self._content_types:
            return CONTENT_TYPE
        if self._genres and any(genre_key(genre) in self._genres for genre in track.genres):
            return GENRE
        return None

    def cluster_reason(self, track: Track) -> str | None:
        """Why this track is excluded by its assigned cluster, or None."""
        if self._clusters and track.cluster_id in self._clusters:
            return CLUSTER
        return None

    def reject(self, track: Track) -> str | None:
        """Metadata check that also records the reason. Returns the reason."""
        return self._record(self.metadata_reason(track))

    def apply(self, tracks: Iterable[Track]) -> list[Track]:
        """Keep tracks that pass the metadata rules, counting what was dropped."""
        return [track for track in tracks if self.reject(track) is None]

    def apply_clusters(self, tracks: Iterable[Track]) -> list[Track]:
        """Keep tracks whose assigned cluster is not blocked. Run after clustering."""
        return [track for track in tracks if self._record(self.cluster_reason(track)) is None]

    def describe_counts(self) -> str:
        """Human-readable breakdown for the log, e.g. `content_type=6, genre=3`."""
        return ", ".join(f"{reason}={count}" for reason, count in sorted(self.counts.items()))

    def _record(self, reason: str | None) -> str | None:
        if reason is not None:
            self.counts[reason] = self.counts.get(reason, 0) + 1
        return reason
