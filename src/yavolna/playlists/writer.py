"""Publishing the playlist (spec sections 17 and 21).

Resolution order for the target playlist: the local reference stored in SQLite
first, then a title lookup at the provider, then creation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from yavolna.config import AppConfig, PlaylistMode
from yavolna.errors import PlaylistWriteError
from yavolna.library.models import MixResult, Playlist
from yavolna.logging import get_logger
from yavolna.persistence.repository import Repository
from yavolna.providers.base import MusicProvider

log = get_logger(__name__)


@dataclass(slots=True)
class PublishOutcome:
    playlist: Playlist
    created: bool
    date_key: str
    deleted_playlists: list[str]


class PlaylistWriter:
    def __init__(self, provider: MusicProvider, config: AppConfig, repository: Repository) -> None:
        self._provider = provider
        self._config = config
        self._repository = repository

    def date_key(self, today: date) -> str:
        """Identity of the run's target playlist: dated, or the single slot."""
        if self._config.playlist.mode is PlaylistMode.DAILY_NEW:
            return today.strftime(self._config.playlist.date_format)
        return ""

    def title_for(self, today: date) -> str:
        return self._config.playlist.title_for(today.strftime(self._config.playlist.date_format))

    def publish(self, result: MixResult, *, today: date) -> PublishOutcome:
        playlist_config = self._config.playlist
        date_key = self.date_key(today)
        title = self.title_for(today)

        playlist, created = self._resolve_playlist(title, date_key)
        log.info(
            "Writing %d tracks to playlist %r (id=%s, %s)",
            len(result.entries),
            playlist.title,
            playlist.provider_playlist_id,
            "created" if created else "existing",
        )
        updated = self._provider.replace_playlist_tracks(
            playlist.provider_playlist_id, result.tracks
        )

        self._repository.remember_managed_playlist(
            self._provider.name, playlist.provider_playlist_id, title, date_key
        )

        deleted: list[str] = []
        if (
            playlist_config.mode is PlaylistMode.DAILY_NEW
            and playlist_config.keep_daily_playlists > 0
        ):
            deleted = self._prune_daily_playlists(keep=playlist_config.keep_daily_playlists)

        return PublishOutcome(
            playlist=updated or playlist,
            created=created,
            date_key=date_key,
            deleted_playlists=deleted,
        )

    # -- internals ------------------------------------------------------------

    def _resolve_playlist(self, title: str, date_key: str) -> tuple[Playlist, bool]:
        playlist_config = self._config.playlist

        reference = self._repository.find_managed_playlist(self._provider.name, date_key)
        if reference:
            existing = self._lookup_by_id(str(reference["playlist_id"]))
            if existing is not None:
                return existing, False
            log.info(
                "The remembered playlist %s no longer exists; a new one will be used",
                reference["playlist_id"],
            )
            self._repository.forget_managed_playlist(
                self._provider.name, str(reference["playlist_id"])
            )

        reuse = (
            playlist_config.reuse_existing_playlist
            or playlist_config.mode is PlaylistMode.DAILY_NEW
        )
        if reuse:
            playlist = self._provider.get_or_create_playlist(
                title,
                description=playlist_config.description,
                visibility=str(playlist_config.visibility),
            )
            created = playlist.track_count == 0
            return playlist, created

        # reuse disabled: always start from a brand new playlist.
        playlist = self._create_unique(title)
        return playlist, True

    def _create_unique(self, title: str) -> Playlist:
        candidate = title
        for attempt in range(1, 50):
            existing_titles = {p.title for p in self._safe_list_playlists()}
            if candidate not in existing_titles:
                break
            candidate = f"{title} ({attempt + 1})"
        playlist = self._provider.get_or_create_playlist(
            candidate,
            description=self._config.playlist.description,
            visibility=str(self._config.playlist.visibility),
        )
        return playlist

    def _lookup_by_id(self, playlist_id: str) -> Playlist | None:
        getter = getattr(self._provider, "get_playlist", None)
        if callable(getter):
            try:
                return getter(playlist_id)
            except Exception as exc:
                log.debug("Playlist lookup by id failed (%s)", type(exc).__name__)
                return None
        for playlist in self._safe_list_playlists():
            if playlist.provider_playlist_id == playlist_id:
                return playlist
        return None

    def _safe_list_playlists(self) -> list[Playlist]:
        try:
            return self._provider.list_playlists()
        except Exception as exc:
            log.debug("Could not list playlists (%s)", type(exc).__name__)
            return []

    def _prune_daily_playlists(self, *, keep: int) -> list[str]:
        """Delete the oldest daily playlists that yavolna itself created.

        Only playlists tracked in the local database are ever touched, and a
        failure to delete is never fatal for the run.
        """
        managed = [
            row
            for row in self._repository.managed_playlists(self._provider.name)
            if str(row["date_key"])
        ]
        stale = managed[keep:]
        deleted: list[str] = []
        for row in stale:
            playlist_id = str(row["playlist_id"])
            try:
                self._provider.delete_playlist(playlist_id)
            except NotImplementedError:
                log.info(
                    "Provider %s cannot delete playlists; skipping clean-up", self._provider.name
                )
                break
            except Exception as exc:
                log.warning(
                    "Could not delete old playlist %r (%s); leaving it in place",
                    row["title"],
                    type(exc).__name__,
                )
                continue
            self._repository.forget_managed_playlist(self._provider.name, playlist_id)
            deleted.append(str(row["title"]))
        if deleted:
            log.info("Removed %d old daily playlists: %s", len(deleted), ", ".join(deleted))
        return deleted


def raise_if_empty(result: MixResult) -> None:
    if not result.entries:
        raise PlaylistWriteError(
            "Refusing to publish an empty playlist.",
            hint="Check that the liked library is large enough and that discovery is working.",
        )
