"""Incremental playlist construction (spec sections 14, 15 and 28).

This is the part of the project that owns the final sequencing policy: the
provider only supplies candidates.
"""

from __future__ import annotations

import random
from datetime import datetime

from yavolna.config import AppConfig
from yavolna.library.models import MixResult, PlaylistEntry, SourceType, Track
from yavolna.logging import get_logger
from yavolna.mixing.candidate_pool import PoolSet
from yavolna.mixing.constraints import (
    RELAXATION_LADDER,
    Constraints,
    Relaxation,
    SchedulerState,
    is_eligible,
)
from yavolna.mixing.scorer import (
    ScoreWeights,
    ScoringContext,
    cluster_targets,
    score_track,
)

log = get_logger(__name__)

#: How many top-scoring candidates take part in the weighted random draw.
TOP_WINDOW = 10
TOP_WINDOW_HIGH_VARIETY = 16


class Scheduler:
    def __init__(
        self,
        config: AppConfig,
        pools: PoolSet,
        *,
        rng: random.Random,
        last_generated: dict[str, datetime] | None = None,
        generation_counts: dict[str, int] | None = None,
        cluster_sizes: dict[str, int] | None = None,
        now: datetime | None = None,
    ) -> None:
        self.config = config
        self.pools = pools
        self.rng = rng
        self.constraints = Constraints.from_config(config)
        self.state = SchedulerState()
        self.context = ScoringContext(
            constraints=self.constraints,
            weights=ScoreWeights.for_variety(config.selection.prefer_high_variety),
            cluster_targets=cluster_targets(
                cluster_sizes or {}, prefer_high_variety=config.selection.prefer_high_variety
            ),
            last_generated=last_generated or {},
            generation_counts=generation_counts or {},
            familiar_target_ratio=config.mix.familiar_ratio,
            exploratory_ratio=config.mix.exploratory_ratio_within_discovery,
            now=now,
        )
        self._window = (
            TOP_WINDOW_HIGH_VARIETY if config.selection.prefer_high_variety else TOP_WINDOW
        )
        self._fallback_duration = config.selection.fallback_track_duration_seconds
        self._duration_fallbacks = 0
        self._relaxations: dict[str, int] = {}

    # -- public API -----------------------------------------------------------

    def build(self, target_duration_seconds: int | None = None) -> MixResult:
        target = target_duration_seconds or self.config.playlist.target_duration_seconds
        result = MixResult(target_duration_seconds=target)
        max_tracks = self.config.validation.max_playlist_tracks

        while self.state.total_duration < target:
            if len(result.entries) >= max_tracks:
                result.stopped_early = True
                result.stop_reason = f"reached max_playlist_tracks={max_tracks}"
                break

            source = self._next_source()
            picked = self._pick(source, result)
            if picked is None:
                # Spec 14.6 step 5: accept a ratio deviation before giving up.
                other = (
                    SourceType.DISCOVERY if source is SourceType.FAMILIAR else SourceType.FAMILIAR
                )
                picked = self._pick(other, result, relaxed_ratio=True)
                if picked is None:
                    result.stopped_early = True
                    result.stop_reason = "no playable candidates left"
                    log.warning(
                        "Stopping early at %d tracks / %.1f h: no candidates satisfy the constraints",
                        len(result.entries),
                        self.state.total_duration / 3600,
                    )
                    break
                source = other

            track, level = picked
            duration = self._duration_of(track)
            entry = PlaylistEntry(
                position=len(result.entries),
                track=track,
                source_type=source,
                cluster_id=track.cluster_id,
                relaxation=level.label if level is not Relaxation.NONE else None,
            )
            result.entries.append(entry)
            self.pools[source].take(track)
            self.state.observe(track, source, duration)

        result.total_duration_seconds = self.state.total_duration
        result.relaxation_counts = dict(self._relaxations)
        if self._duration_fallbacks:
            log.info(
                "Used the %ds fallback duration for %d tracks without duration metadata",
                self._fallback_duration,
                self._duration_fallbacks,
            )
        log.info(
            "Built %d tracks / %.1f h (familiar %d, discovery %d, ratio %.2f/%.2f)",
            len(result.entries),
            result.total_duration_seconds / 3600,
            result.familiar_count,
            result.discovery_count,
            result.familiar_ratio,
            result.discovery_ratio,
        )
        return result

    # -- internals ------------------------------------------------------------

    def _next_source(self) -> SourceType:
        """Quota controller: whichever source is further behind its target."""
        position = self.state.position + 1
        familiar_deficit = self.config.mix.familiar_ratio * position - self.state.familiar_count
        discovery_deficit = self.config.mix.discovery_ratio * position - self.state.discovery_count

        if len(self.pools.discovery) == 0:
            return SourceType.FAMILIAR
        if len(self.pools.familiar) == 0:
            return SourceType.DISCOVERY
        return (
            SourceType.FAMILIAR if familiar_deficit >= discovery_deficit else SourceType.DISCOVERY
        )

    def _pick(
        self, source: SourceType, result: MixResult, *, relaxed_ratio: bool = False
    ) -> tuple[Track, Relaxation] | None:
        pool = self.pools[source]
        if len(pool) == 0:
            return None

        cap = self.config.selection.max_candidates_per_step
        for level in RELAXATION_LADDER:
            candidates = self._eligible(pool.sample(self.rng, cap), level)
            if not candidates and len(pool) > cap:
                # The sample missed; fall back to a full scan before relaxing.
                candidates = self._eligible(pool.remaining(), level)
            if candidates:
                if level is not Relaxation.NONE:
                    self._record_relaxation(level, len(result.entries))
                if relaxed_ratio:
                    self._record_relaxation(Relaxation.RATIO, len(result.entries))
                return self._choose(candidates, source), level
        return None

    def _eligible(self, candidates: list[Track], level: Relaxation) -> list[Track]:
        return [
            track
            for track in candidates
            if is_eligible(
                track,
                self.state,
                self.constraints,
                level,
                last_generated=self.context.last_generated,
                now=self.context.now,
            )
        ]

    def _choose(self, candidates: list[Track], source: SourceType) -> Track:
        """Score, take a top window, then weighted-random inside it (spec 14.5)."""
        scored = [
            (score_track(track, source, self.state, self.context).total, index, track)
            for index, track in enumerate(candidates)
        ]
        scored.sort(key=lambda item: (-item[0], item[1]))
        window = scored[: max(1, min(self._window, len(scored)))]

        lowest = window[-1][0]
        weights = [max(1e-6, score - lowest + 0.25) for score, _, _ in window]
        chosen = self.rng.choices(range(len(window)), weights=weights, k=1)[0]
        return window[chosen][2]

    def _duration_of(self, track: Track) -> int:
        if track.duration_seconds and track.duration_seconds > 0:
            return track.duration_seconds
        self._duration_fallbacks += 1
        return self._fallback_duration

    def _record_relaxation(self, level: Relaxation, position: int) -> None:
        first = level.label not in self._relaxations
        self._relaxations[level.label] = self._relaxations.get(level.label, 0) + 1
        message = "Relaxed %s constraint at position %d"
        if first:
            log.info(message, level.label, position)
        else:
            log.debug(message, level.label, position)
