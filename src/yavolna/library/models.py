"""Provider-neutral domain model (spec section 10).

Nothing outside providers/ may depend on provider-native objects; everything
works on these dataclasses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class SourceType(StrEnum):
    FAMILIAR = "familiar"
    DISCOVERY = "discovery"


@dataclass(slots=True)
class Track:
    provider: str
    provider_track_id: str
    title: str
    artist_ids: tuple[str, ...] = ()
    artist_names: tuple[str, ...] = ()
    album_id: str | None = None
    album_title: str | None = None
    duration_seconds: int | None = None
    genres: tuple[str, ...] = ()
    release_year: int | None = None
    liked: bool = False
    explicit: bool = False
    available: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    # Runtime annotation, assigned by the clusterer.
    cluster_id: str | None = None

    @property
    def primary_artist_id(self) -> str | None:
        return self.artist_ids[0] if self.artist_ids else None

    @property
    def artist_label(self) -> str:
        return ", ".join(self.artist_names) if self.artist_names else "Unknown artist"

    def duration_or(self, fallback: int) -> int:
        if self.duration_seconds and self.duration_seconds > 0:
            return self.duration_seconds
        return fallback

    def describe(self) -> str:
        return f"{self.artist_label} — {self.title}"


@dataclass(frozen=True, slots=True)
class PlaybackEvent:
    provider_track_id: str
    played_at: datetime | None = None
    context: str | None = None


@dataclass(slots=True)
class Playlist:
    provider: str
    provider_playlist_id: str
    title: str
    track_count: int = 0
    revision: int | None = None
    url: str | None = None
    raw: Any = None


@dataclass(slots=True)
class PlaylistEntry:
    position: int
    track: Track
    source_type: SourceType
    cluster_id: str | None = None
    relaxation: str | None = None


@dataclass(slots=True)
class MixResult:
    entries: list[PlaylistEntry] = field(default_factory=list)
    total_duration_seconds: int = 0
    target_duration_seconds: int = 0
    relaxation_counts: dict[str, int] = field(default_factory=dict)
    stopped_early: bool = False
    stop_reason: str | None = None

    @property
    def tracks(self) -> list[Track]:
        return [entry.track for entry in self.entries]

    @property
    def familiar_count(self) -> int:
        return sum(1 for e in self.entries if e.source_type is SourceType.FAMILIAR)

    @property
    def discovery_count(self) -> int:
        return sum(1 for e in self.entries if e.source_type is SourceType.DISCOVERY)

    @property
    def familiar_ratio(self) -> float:
        return self.familiar_count / len(self.entries) if self.entries else 0.0

    @property
    def discovery_ratio(self) -> float:
        return self.discovery_count / len(self.entries) if self.entries else 0.0

    def cluster_histogram(self) -> dict[str, int]:
        histogram: dict[str, int] = {}
        for entry in self.entries:
            key = entry.cluster_id or "unknown"
            histogram[key] = histogram.get(key, 0) + 1
        return histogram


@dataclass(slots=True)
class Library:
    """The user's liked library, normalized and clustered."""

    tracks: list[Track] = field(default_factory=list)
    liked_at: dict[str, datetime] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.tracks)

    @property
    def track_ids(self) -> set[str]:
        return {track.provider_track_id for track in self.tracks}

    def by_cluster(self) -> dict[str, list[Track]]:
        grouped: dict[str, list[Track]] = {}
        for track in self.tracks:
            grouped.setdefault(track.cluster_id or "unknown", []).append(track)
        return grouped

    def stats(self, fallback_duration: int = 240) -> dict[str, Any]:
        artists = {aid for track in self.tracks for aid in track.artist_ids}
        albums = {track.album_id for track in self.tracks if track.album_id}
        clusters = self.by_cluster()
        total_seconds = sum(track.duration_or(fallback_duration) for track in self.tracks)
        return {
            "liked_tracks": len(self.tracks),
            "artists": len(artists),
            "albums": len(albums),
            "clusters": len(clusters),
            "unavailable_tracks": sum(1 for t in self.tracks if not t.available),
            "tracks_without_duration": sum(1 for t in self.tracks if not t.duration_seconds),
            "estimated_duration_seconds": total_seconds,
        }
