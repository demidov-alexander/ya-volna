"""Variety constraints and the relaxation ladder (spec sections 14.3 and 14.6)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum

from yavolna.config import AppConfig
from yavolna.library.models import SourceType, Track
from yavolna.library.normalization import content_key


class Relaxation(IntEnum):
    """Ordered relaxation steps. Lower is stricter."""

    NONE = 0
    CLUSTER = 1
    ALBUM = 2
    ARTIST = 3
    COOLDOWN = 4
    RATIO = 5

    @property
    def label(self) -> str:
        return self.name.lower()


#: Order in which constraints are given up when nothing is selectable.
RELAXATION_LADDER: tuple[Relaxation, ...] = (
    Relaxation.NONE,
    Relaxation.CLUSTER,
    Relaxation.ALBUM,
    Relaxation.ARTIST,
    Relaxation.COOLDOWN,
)


@dataclass(frozen=True, slots=True)
class Constraints:
    same_artist_gap: int
    same_album_gap: int
    same_cluster_gap: int
    track_cooldown_days: int
    favorite_track_cooldown_days: int

    @classmethod
    def from_config(cls, config: AppConfig) -> Constraints:
        repetition = config.repetition
        return cls(
            same_artist_gap=repetition.same_artist_gap_tracks,
            same_album_gap=repetition.same_album_gap_tracks,
            same_cluster_gap=repetition.same_cluster_gap_tracks,
            track_cooldown_days=repetition.track_cooldown_days,
            favorite_track_cooldown_days=repetition.favorite_track_cooldown_days,
        )

    def cooldown_days_for(self, track: Track) -> int:
        return self.favorite_track_cooldown_days if track.liked else self.track_cooldown_days


@dataclass(slots=True)
class SchedulerState:
    """Everything the scheduler needs to know about what it already picked."""

    position: int = 0
    total_duration: int = 0
    familiar_count: int = 0
    discovery_count: int = 0
    used_track_ids: set[str] = field(default_factory=set)
    # Same recording under a different provider id: two ids, one song. Liked
    # libraries do contain those, and in a playlist they read as a duplicate.
    used_content_keys: set[tuple[str, str]] = field(default_factory=set)
    last_artist_position: dict[str, int] = field(default_factory=dict)
    last_album_position: dict[str, int] = field(default_factory=dict)
    last_cluster_position: dict[str, int] = field(default_factory=dict)
    cluster_counts: Counter[str] = field(default_factory=Counter)

    def observe(self, track: Track, source: SourceType, duration_seconds: int) -> None:
        self.used_track_ids.add(track.provider_track_id)
        key = content_key(track)
        if key != ("", ""):
            self.used_content_keys.add(key)
        for artist_id in track.artist_ids:
            self.last_artist_position[artist_id] = self.position
        if track.album_id:
            self.last_album_position[track.album_id] = self.position
        if track.cluster_id:
            self.last_cluster_position[track.cluster_id] = self.position
            self.cluster_counts[track.cluster_id] += 1
        if source is SourceType.FAMILIAR:
            self.familiar_count += 1
        else:
            self.discovery_count += 1
        self.total_duration += duration_seconds
        self.position += 1

    def distance_since_artist(self, track: Track) -> int | None:
        positions = [
            self.last_artist_position[artist_id]
            for artist_id in track.artist_ids
            if artist_id in self.last_artist_position
        ]
        if not positions:
            return None
        return self.position - max(positions)

    def distance_since_album(self, track: Track) -> int | None:
        if not track.album_id or track.album_id not in self.last_album_position:
            return None
        return self.position - self.last_album_position[track.album_id]

    def distance_since_cluster(self, track: Track) -> int | None:
        if not track.cluster_id or track.cluster_id not in self.last_cluster_position:
            return None
        return self.position - self.last_cluster_position[track.cluster_id]


def passes_hard_filters(track: Track, state: SchedulerState) -> bool:
    """Filters that are never relaxed, at any level."""
    if not track.available:
        return False
    if track.provider_track_id in state.used_track_ids:
        return False
    key = content_key(track)
    return not (key != ("", "") and key in state.used_content_keys)


def is_eligible(
    track: Track,
    state: SchedulerState,
    constraints: Constraints,
    level: Relaxation,
    *,
    last_generated: dict[str, datetime] | None = None,
    now: datetime | None = None,
) -> bool:
    """Check a candidate against the variety constraints at a relaxation level."""
    if not passes_hard_filters(track, state):
        return False

    if level < Relaxation.CLUSTER and constraints.same_cluster_gap > 0:
        distance = state.distance_since_cluster(track)
        if distance is not None and distance < constraints.same_cluster_gap:
            return False

    if level < Relaxation.ALBUM and constraints.same_album_gap > 0:
        distance = state.distance_since_album(track)
        if distance is not None and distance < constraints.same_album_gap:
            return False

    if level < Relaxation.ARTIST and constraints.same_artist_gap > 0:
        distance = state.distance_since_artist(track)
        if distance is not None and distance < constraints.same_artist_gap:
            return False

    if level < Relaxation.COOLDOWN and last_generated:
        stamp = last_generated.get(track.provider_track_id)
        if stamp is not None:
            cooldown = constraints.cooldown_days_for(track)
            if cooldown > 0 and days_between(stamp, now) < cooldown:
                return False

    return True


def days_between(stamp: datetime, now: datetime | None) -> float:
    reference = now or datetime.now(stamp.tzinfo)
    if stamp.tzinfo and not reference.tzinfo:
        reference = reference.replace(tzinfo=stamp.tzinfo)
    return max(0.0, (reference - stamp).total_seconds() / 86400.0)
