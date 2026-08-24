"""Discovery seed groups (spec section 12.1).

Recommendations are requested from several small, deliberately different seed
groups instead of one global seed set — that is what keeps the discovery half of
the playlist from collapsing into a single style.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from yavolna.config import AppConfig
from yavolna.library.models import Library, Track
from yavolna.logging import get_logger

log = get_logger(__name__)


@dataclass(slots=True)
class SeedGroup:
    name: str
    tracks: list[Track]

    def __len__(self) -> int:
        return len(self.tracks)


def build_seed_groups(library: Library, config: AppConfig, rng: random.Random) -> list[SeedGroup]:
    """Build up to `discovery.seed_groups_max` diverse seed groups."""
    per_group = config.discovery.seeds_per_group
    clusters = library.by_cluster()
    if not clusters:
        return []

    ordered_clusters = sorted(clusters.items(), key=lambda item: len(item[1]), reverse=True)

    # One group per cluster, largest first: covers the bulk of the taste.
    cluster_groups = [
        SeedGroup(f"cluster:{cluster_id}", _sample(tracks, per_group, rng))
        for cluster_id, tracks in ordered_clusters
    ]

    strategy_groups: list[SeedGroup] = []

    # Intentionally diverse: one track from as many clusters as possible.
    diverse = [rng.choice(tracks) for _, tracks in ordered_clusters]
    rng.shuffle(diverse)
    strategy_groups.append(SeedGroup("diverse", diverse[:per_group]))

    # Underrepresented clusters: the long tail the provider rarely surfaces.
    tail = [track for _, tracks in ordered_clusters[-3:] for track in tracks]
    if tail:
        strategy_groups.append(SeedGroup("underrepresented", _sample(tail, per_group, rng)))

    # Recently liked / oldest liked: catches drift in taste over time.
    by_recency = _sorted_by_liked_at(library)
    if by_recency:
        strategy_groups.append(
            SeedGroup("recent_likes", _sample(by_recency[: per_group * 5], per_group, rng))
        )
        strategy_groups.append(
            SeedGroup("old_likes", _sample(by_recency[-per_group * 5 :], per_group, rng))
        )

    # Interleave so that the seed_groups_max cap never drops a whole strategy:
    # two cluster groups for every strategy group.
    merged = _interleave(cluster_groups, strategy_groups, ratio=2)
    groups = [group for group in merged if group.tracks]
    dropped = max(0, len(groups) - config.discovery.seed_groups_max)
    groups = groups[: config.discovery.seed_groups_max]
    log.info(
        "Seed groups: %s%s",
        ", ".join(f"{group.name}({len(group)})" for group in groups) or "none",
        f" ({dropped} more skipped by discovery.seed_groups_max)" if dropped else "",
    )
    return groups


def _interleave(
    primary: list[SeedGroup], secondary: list[SeedGroup], *, ratio: int
) -> list[SeedGroup]:
    merged: list[SeedGroup] = []
    primary_iter, secondary_iter = iter(primary), iter(secondary)
    exhausted = 0
    while exhausted < 2:
        exhausted = 0
        for _ in range(ratio):
            item = next(primary_iter, None)
            if item is None:
                exhausted += 1
                break
            merged.append(item)
        item = next(secondary_iter, None)
        if item is None:
            exhausted += 1
        else:
            merged.append(item)
    return merged


def _sample(tracks: list[Track], count: int, rng: random.Random) -> list[Track]:
    eligible = [track for track in tracks if track.available]
    pool = eligible or list(tracks)
    if not pool:
        return []
    return rng.sample(pool, min(count, len(pool)))


def _sorted_by_liked_at(library: Library) -> list[Track]:
    stamped = [track for track in library.tracks if track.provider_track_id in library.liked_at]
    if not stamped:
        return []
    return sorted(stamped, key=lambda t: library.liked_at[t.provider_track_id], reverse=True)
