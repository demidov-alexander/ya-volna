"""The generation pipeline (spec section 27).

Wires provider, library, clustering, discovery, scheduler, validation, writer
and persistence into one deterministic one-shot run.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from yavolna.clustering.metadata_clusterer import MetadataClusterer
from yavolna.config import AppConfig, PlaylistMode
from yavolna.errors import ConfigurationError, ProviderError
from yavolna.library.filters import ExclusionFilter
from yavolna.library.loader import load_library
from yavolna.library.models import Library, MixResult, Playlist
from yavolna.logging import get_logger
from yavolna.mixing.candidate_pool import PoolSet
from yavolna.mixing.scheduler import Scheduler
from yavolna.persistence.repository import Repository
from yavolna.playlists.validation import ensure_valid
from yavolna.playlists.writer import PlaylistWriter, raise_if_empty
from yavolna.providers.base import MusicProvider
from yavolna.recommendation.discovery import fetch_discovery_candidates
from yavolna.recommendation.seeds import build_seed_groups

log = get_logger(__name__)


@dataclass(slots=True)
class GenerationReport:
    started_at: datetime
    finished_at: datetime | None = None
    dry_run: bool = False
    seed: int | None = None
    library_size: int = 0
    familiar_pool: int = 0
    discovery_pool: int = 0
    result: MixResult | None = None
    playlist: Playlist | None = None
    playlist_title: str | None = None
    playlist_created: bool = False
    deleted_playlists: list[str] = field(default_factory=list)
    export_path: Path | None = None
    run_id: int | None = None
    remote_history_events: int = 0

    @property
    def duration_seconds(self) -> float:
        end = self.finished_at or datetime.now(UTC)
        return (end - self.started_at).total_seconds()

    def summary_lines(self) -> list[str]:
        result = self.result
        lines = [
            f"library:           {self.library_size} liked tracks",
            f"candidate pools:   familiar {self.familiar_pool}, discovery {self.discovery_pool}",
        ]
        if result is not None:
            lines += [
                f"selected:          {len(result.entries)} tracks "
                f"({result.total_duration_seconds / 3600:.1f} h of "
                f"{result.target_duration_seconds / 3600:.1f} h target)",
                f"mix:               familiar {result.familiar_count} "
                f"({result.familiar_ratio:.0%}), discovery {result.discovery_count} "
                f"({result.discovery_ratio:.0%})",
                f"clusters used:     {len(result.cluster_histogram())}",
            ]
            if result.relaxation_counts:
                relaxed = ", ".join(f"{k}={v}" for k, v in sorted(result.relaxation_counts.items()))
                lines.append(f"relaxations:       {relaxed}")
            if result.stopped_early:
                lines.append(f"stopped early:     {result.stop_reason}")
        if self.playlist is not None:
            lines.append(
                f"playlist:          {self.playlist_title!r} "
                f"(id={self.playlist.provider_playlist_id}"
                + (", created" if self.playlist_created else "")
                + ")"
            )
            if self.playlist.url:
                lines.append(f"url:               {self.playlist.url}")
        if self.deleted_playlists:
            lines.append(f"removed old:       {', '.join(self.deleted_playlists)}")
        if self.export_path is not None:
            lines.append(f"dry-run export:    {self.export_path}")
        lines.append(f"runtime:           {self.duration_seconds:.1f}s")
        return lines


class GenerateMixService:
    def __init__(
        self,
        *,
        provider: MusicProvider,
        config: AppConfig,
        repository: Repository,
        today: date | None = None,
        now: datetime | None = None,
    ) -> None:
        self._provider = provider
        self._config = config
        self._repository = repository
        self._now = now or datetime.now(UTC)
        self._today = today or self._now.date()

    # -- public API -----------------------------------------------------------

    def run(self, *, dry_run: bool = False, seed: int | None = None) -> GenerationReport:
        report = GenerationReport(started_at=self._now, dry_run=dry_run)
        config = self._config

        effective_seed = seed if seed is not None else config.selection.random_seed
        report.seed = effective_seed
        rng = random.Random(effective_seed)

        # Steps 3 and 6: liked library, normalized and clustered.
        library = self.load_library()
        report.library_size = len(library)
        if len(library) < config.selection.minimum_liked_tracks:
            raise ConfigurationError(
                f"Only {len(library)} liked tracks available, "
                f"selection.minimum_liked_tracks is {config.selection.minimum_liked_tracks}.",
                hint="Like more tracks in Yandex Music or lower selection.minimum_liked_tracks.",
            )

        # Step 4: local anti-repetition memory.
        self._repository.prune(retention_days=config.history.local_retention_days)
        last_generated = self._repository.last_generated_map(
            within_days=max(config.repetition.track_cooldown_days * 3, 30)
        )
        generation_counts = self._repository.generation_counts()

        # Step 5: optional remote history, used only as an extra cooldown hint.
        if config.history.use_remote_listening_history:
            events = self._safe_remote_history()
            report.remote_history_events = len(events)
            for event in events:
                if event.played_at and event.provider_track_id not in last_generated:
                    last_generated[event.provider_track_id] = event.played_at

        # Steps 7 to 10: candidate pools.
        familiar = [track for track in library.tracks if track.available]
        recently_generated = {
            track_id
            for track_id, stamp in last_generated.items()
            if (self._now - stamp).days < config.repetition.track_cooldown_days
        }
        seed_groups = build_seed_groups(library, config, rng)
        discovery = (
            fetch_discovery_candidates(
                self._provider,
                seed_groups,
                library,
                config,
                recently_generated=recently_generated,
            )
            if config.mix.discovery_ratio > 0
            else []
        )
        clusterer = self._clusterer()
        clusterer.assign(discovery)
        # exclusions.blocked_clusters can only be applied once the candidates
        # have a cluster id; the metadata rules already ran in discovery.
        cluster_exclusions = ExclusionFilter(config.exclusions)
        discovery = cluster_exclusions.apply_clusters(discovery)
        if cluster_exclusions.excluded:
            log.info(
                "Discovery: %d candidates dropped by exclusions.blocked_clusters",
                cluster_exclusions.excluded,
            )

        report.familiar_pool = len(familiar)
        report.discovery_pool = len(discovery)
        if config.mix.discovery_ratio > 0 and not discovery:
            log.warning(
                "No discovery candidates available; the playlist will be familiar-only and "
                "the familiar/discovery ratio will deviate"
            )

        # Step 11: sequencing.
        cluster_sizes = {
            cluster_id: len(tracks) for cluster_id, tracks in library.by_cluster().items()
        }
        for track in discovery:
            key = track.cluster_id or "unknown"
            cluster_sizes.setdefault(key, 0)
        scheduler = Scheduler(
            config,
            PoolSet(familiar=familiar, discovery=discovery),
            rng=rng,
            last_generated=last_generated,
            generation_counts=generation_counts,
            cluster_sizes=cluster_sizes,
            now=self._now,
        )
        result = scheduler.build()
        report.result = result

        # Step 12: validation before anything is published.
        raise_if_empty(result)
        ensure_valid(result, config)

        writer = PlaylistWriter(self._provider, config, self._repository)
        report.playlist_title = writer.title_for(self._today)

        if dry_run:
            report.export_path = self._export_dry_run(report, result)
            report.finished_at = datetime.now(UTC)
            log.info("Dry run complete; Yandex Music was not modified")
            return report

        # Step 13: remote update, then step 14: local commit.
        outcome = writer.publish(result, today=self._today)
        report.playlist = outcome.playlist
        report.playlist_created = outcome.created
        report.deleted_playlists = outcome.deleted_playlists

        report.run_id = self._repository.commit_run(
            entries=result.entries,
            status="success",
            started_at=report.started_at,
            playlist_id=outcome.playlist.provider_playlist_id,
            playlist_title=report.playlist_title,
            target_duration_seconds=result.target_duration_seconds,
            actual_duration_seconds=result.total_duration_seconds,
            familiar_count=result.familiar_count,
            discovery_count=result.discovery_count,
            random_seed=effective_seed,
            notes=result.stop_reason,
            liked_ids=library.track_ids,
        )
        report.finished_at = datetime.now(UTC)
        return report

    def load_library(self) -> Library:
        return load_library(self._provider, self._config, self._clusterer())

    # -- internals ------------------------------------------------------------

    def _clusterer(self) -> MetadataClusterer:
        return MetadataClusterer(
            genre_map=self._config.clustering.genre_map,
            fallback_cluster=self._config.clustering.fallback_cluster,
        )

    def _safe_remote_history(self) -> list[Any]:
        try:
            return list(self._provider.get_recent_history())
        except ProviderError as exc:
            log.info("Remote listening history unavailable: %s", exc.message)
            return []
        except Exception as exc:
            log.info("Remote listening history unavailable (%s)", type(exc).__name__)
            return []

    def _export_dry_run(self, report: GenerationReport, result: MixResult) -> Path:
        directory = Path(self._config.runtime.dry_run_export_dir)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"dry-run-{self._today.isoformat()}.json"
        payload = {
            "generated_at": self._now.isoformat(),
            "mode": str(self._config.playlist.mode),
            "playlist_title": report.playlist_title,
            "seed": report.seed,
            "target_duration_seconds": result.target_duration_seconds,
            "total_duration_seconds": result.total_duration_seconds,
            "familiar_count": result.familiar_count,
            "discovery_count": result.discovery_count,
            "cluster_histogram": result.cluster_histogram(),
            "relaxations": result.relaxation_counts,
            "stopped_early": result.stopped_early,
            "stop_reason": result.stop_reason,
            "tracks": [
                {
                    "position": entry.position,
                    "provider_track_id": entry.track.provider_track_id,
                    "title": entry.track.title,
                    "artists": list(entry.track.artist_names),
                    "album": entry.track.album_title,
                    "duration_seconds": entry.track.duration_seconds,
                    "cluster": entry.cluster_id,
                    "source": str(entry.source_type),
                    "seed_group": entry.track.metadata.get("seed_group"),
                    "relaxation": entry.relaxation,
                }
                for entry in result.entries
            ],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("Exported the proposed playlist to %s", path)
        return path


def describe_mode(config: AppConfig) -> str:
    if config.playlist.mode is PlaylistMode.DAILY_NEW:
        keep = config.playlist.keep_daily_playlists
        retention = f", keeping the last {keep}" if keep else ", keeping all"
        return f"a new dated playlist per day{retention}"
    return "one playlist, contents replaced on every run"
