"""Discovery candidate generation (spec sections 12.2 and 12.3)."""

from __future__ import annotations

from collections.abc import Iterable

from yavolna.config import AppConfig
from yavolna.library.filters import ExclusionFilter
from yavolna.library.models import Library, Track
from yavolna.library.normalization import content_key, dedupe_tracks
from yavolna.logging import get_logger
from yavolna.providers.base import MusicProvider
from yavolna.recommendation.seeds import SeedGroup

log = get_logger(__name__)


def fetch_discovery_candidates(
    provider: MusicProvider,
    seed_groups: Iterable[SeedGroup],
    library: Library,
    config: AppConfig,
    *,
    recently_generated: set[str] | None = None,
) -> list[Track]:
    """Query every seed group separately, then merge, dedupe and filter.

    A seed group that fails is logged and skipped: partial discovery is much
    better than an aborted run (spec section 4).
    """
    collected: list[Track] = []
    failures = 0
    for group in seed_groups:
        if not group.tracks:
            continue
        try:
            candidates = provider.get_recommendations(
                group.tracks, limit=config.discovery.max_candidates_per_seed * len(group.tracks)
            )
        except Exception as exc:
            failures += 1
            log.warning(
                "Seed group %s produced no recommendations (%s)", group.name, type(exc).__name__
            )
            continue
        for track in candidates:
            track.metadata.setdefault("seed_group", group.name)
        log.debug("Seed group %s -> %d raw candidates", group.name, len(candidates))
        collected.extend(candidates)

    if config.discovery.use_personal_wave:
        try:
            wave = provider.get_personal_wave(limit=config.discovery.max_candidates_per_seed * 3)
        except Exception as exc:
            log.info("Personal wave unavailable (%s)", type(exc).__name__)
            wave = []
        if wave:
            log.debug("Personal wave -> %d raw candidates", len(wave))
            collected.extend(wave)

    filtered = filter_discovery_candidates(
        collected, library=library, config=config, recently_generated=recently_generated
    )
    log.info(
        "Discovery pool: %d candidates from %d seed groups (%d failed)",
        len(filtered),
        sum(1 for group in seed_groups if group.tracks),
        failures,
    )
    return filtered


def filter_discovery_candidates(
    candidates: Iterable[Track],
    *,
    library: Library,
    config: AppConfig,
    recently_generated: set[str] | None = None,
) -> list[Track]:
    """Apply the discovery exclusion rules from spec section 12.3."""
    liked_ids = library.track_ids
    liked_content = {content_key(track) for track in library.tracks}
    exclusions = ExclusionFilter(config.exclusions)
    recent = recently_generated or set()

    kept: list[Track] = []
    for track in candidates:
        if track.provider_track_id in liked_ids or track.liked:
            continue
        if content_key(track) in liked_content:
            continue
        if not track.available:
            continue
        if exclusions.reject(track) is not None:
            continue
        if track.provider_track_id in recent:
            continue
        track.liked = False
        kept.append(track)

    if exclusions.excluded:
        log.info(
            "Discovery: %d candidates dropped by exclusions [%s]",
            exclusions.excluded,
            exclusions.describe_counts(),
        )
    return dedupe_tracks(kept, by_content=True)
