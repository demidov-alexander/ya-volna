"""Candidate scoring (spec section 14.4).

The numbers here are deliberately internal: the public configuration exposes
gaps, cooldowns and ratios, while the weighting can evolve without breaking
anyone's config.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from yavolna.library.models import SourceType, Track
from yavolna.mixing.constraints import (
    Constraints,
    SchedulerState,
    days_between,
    is_exploratory,
)


@dataclass(frozen=True, slots=True)
class ScoreWeights:
    base: float = 1.0
    cluster_balance: float = 1.6
    quota_need: float = 1.2
    exploratory: float = 0.6
    track_recency: float = 2.0
    artist_recency: float = 1.5
    album_recency: float = 1.0
    cluster_recency: float = 1.2
    generation_count: float = 0.5

    @classmethod
    def for_variety(cls, prefer_high_variety: bool) -> ScoreWeights:
        if prefer_high_variety:
            return cls()
        return cls(cluster_balance=0.8, cluster_recency=0.6, artist_recency=1.0)


@dataclass(slots=True)
class ScoringContext:
    constraints: Constraints
    weights: ScoreWeights
    cluster_targets: dict[str, float] = field(default_factory=dict)
    last_generated: dict[str, datetime] = field(default_factory=dict)
    generation_counts: dict[str, int] = field(default_factory=dict)
    familiar_target_ratio: float = 0.65
    exploratory_ratio: float = 0.25
    now: datetime | None = None


@dataclass(slots=True)
class ScoreBreakdown:
    total: float
    components: dict[str, float]


def score_track(
    track: Track,
    source: SourceType,
    state: SchedulerState,
    context: ScoringContext,
) -> ScoreBreakdown:
    weights = context.weights
    components: dict[str, float] = {"base": weights.base}

    components["cluster_balance"] = weights.cluster_balance * _cluster_deficit(
        track, state, context
    )
    components["quota_need"] = weights.quota_need * _quota_deficit(source, state, context)
    components["exploratory"] = weights.exploratory * _exploratory_signal(
        track, source, state, context
    )

    components["track_recency"] = -weights.track_recency * _track_recency_penalty(track, context)
    components["artist_recency"] = -weights.artist_recency * _gap_penalty(
        state.distance_since_artist(track), context.constraints.same_artist_gap
    )
    components["album_recency"] = -weights.album_recency * _gap_penalty(
        state.distance_since_album(track), context.constraints.same_album_gap
    )
    components["cluster_recency"] = -weights.cluster_recency * _gap_penalty(
        state.distance_since_cluster(track), context.constraints.same_cluster_gap
    )
    components["generation_count"] = -weights.generation_count * _generation_penalty(track, context)

    return ScoreBreakdown(total=sum(components.values()), components=components)


def _cluster_deficit(track: Track, state: SchedulerState, context: ScoringContext) -> float:
    """Positive when the track's cluster is behind its target share so far."""
    cluster_id = track.cluster_id
    if not cluster_id or state.position == 0:
        return 0.0
    target = context.cluster_targets.get(cluster_id)
    if target is None:
        target = 1.0 / max(1, len(context.cluster_targets) or 1)
    actual = state.cluster_counts.get(cluster_id, 0) / state.position
    return max(-1.0, min(1.0, target - actual))


def _quota_deficit(source: SourceType, state: SchedulerState, context: ScoringContext) -> float:
    """Positive when this source is behind the configured long-term ratio."""
    position = state.position + 1
    familiar_target = context.familiar_target_ratio * position
    deficit = familiar_target - state.familiar_count
    if source is SourceType.DISCOVERY:
        deficit = -deficit
    return max(-1.0, min(1.0, deficit / 10.0))


def _exploratory_signal(
    track: Track, source: SourceType, state: SchedulerState, context: ScoringContext
) -> float:
    """Steer the exploratory share of discovery towards its configured ratio.

    A constant bonus for the odd seed groups would let them crowd out the
    taste-adjacent recommendations entirely, so this is a two-sided quota
    signal: positive for whichever side is behind its target.
    """
    if source is not SourceType.DISCOVERY:
        return 0.0
    target = context.exploratory_ratio * (state.discovery_count + 1)
    deficit = max(-1.0, min(1.0, (target - state.exploratory_count) / 5.0))
    return deficit if is_exploratory(track) else -deficit


def _track_recency_penalty(track: Track, context: ScoringContext) -> float:
    stamp = context.last_generated.get(track.provider_track_id)
    if stamp is None:
        return 0.0
    cooldown = context.constraints.cooldown_days_for(track)
    if cooldown <= 0:
        return 0.0
    elapsed = days_between(stamp, context.now)
    return max(0.0, min(1.0, (cooldown - elapsed) / cooldown))


def _gap_penalty(distance: int | None, gap: int) -> float:
    """1.0 when the item just played, decaying to 0 at the configured gap."""
    if distance is None or gap <= 0:
        return 0.0
    if distance >= gap:
        return 0.0
    return (gap - distance) / gap


def _generation_penalty(track: Track, context: ScoringContext) -> float:
    count = context.generation_counts.get(track.provider_track_id, 0)
    if count <= 0:
        return 0.0
    return min(1.0, count / 10.0)


def cluster_targets(
    cluster_sizes: dict[str, int], *, prefer_high_variety: bool
) -> dict[str, float]:
    """Target share per cluster.

    With prefer_high_variety the target is pulled towards a uniform share, so
    small clusters get more airtime than their library share would give them.
    """
    total = sum(cluster_sizes.values())
    if total <= 0 or not cluster_sizes:
        return {}
    uniform = 1.0 / len(cluster_sizes)
    blend = 0.5 if prefer_high_variety else 0.15
    return {
        cluster_id: (1 - blend) * (size / total) + blend * uniform
        for cluster_id, size in cluster_sizes.items()
    }
