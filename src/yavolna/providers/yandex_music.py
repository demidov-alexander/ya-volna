"""Yandex Music adapter built on the unofficial `yandex-music` client.

This is the only module allowed to import `yandex_music` or to know about its
data shapes (spec sections 4 and 9). Everything here is defensive on purpose:
the upstream API is reverse-engineered and fields disappear without notice.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Any

from yavolna.config import Secrets
from yavolna.errors import (
    AuthenticationError,
    PlaylistWriteError,
    ProviderError,
    YaVolnaError,
)
from yavolna.library.models import PlaybackEvent, Playlist, Track
from yavolna.logging import get_logger
from yavolna.providers.base import AccountInfo, MusicProvider

log = get_logger(__name__)

PROVIDER_NAME = "yandex"

#: Full track metadata is fetched in batches; the endpoint rejects huge id lists.
TRACK_BATCH_SIZE = 100
#: Playlist mutations are chunked to stay inside request-size limits.
PLAYLIST_CHUNK_SIZE = 100
#: Station id of "My Wave" used as an extra discovery source.
PERSONAL_WAVE_STATION = "user:onyourwave"


class YandexMusicProvider(MusicProvider):
    name = PROVIDER_NAME

    def __init__(self, secrets: Secrets, *, client: Any | None = None) -> None:
        self._secrets = secrets
        self._client = client
        self._account: AccountInfo | None = None

    # -- client bootstrap -----------------------------------------------------

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = self._create_client()
        return self._client

    def _create_client(self) -> Any:
        try:
            from yandex_music import Client
            from yandex_music.exceptions import UnauthorizedError, YandexMusicError
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise ProviderError(
                "The yandex-music package is not installed.",
                hint="Install the project dependencies: pip install -e .",
            ) from exc

        try:
            client = Client(self._secrets.yandex_music_token)
            client.init()
        except UnauthorizedError as exc:
            raise AuthenticationError(
                "Yandex Music rejected the token.",
                hint="Check YANDEX_MUSIC_TOKEN and run `yavolna auth-check`.",
            ) from exc
        except YandexMusicError as exc:
            raise ProviderError(f"Could not initialise the Yandex Music client: {exc}") from exc
        return client

    @property
    def _user_id(self) -> str | None:
        if self._secrets.yandex_music_user_id:
            return self._secrets.yandex_music_user_id
        account = self._account or self._safe_account()
        return account.user_id if account else None

    def _safe_account(self) -> AccountInfo | None:
        try:
            return self.check_auth()
        except Exception:  # pragma: no cover - only used for optional lookups
            return None

    # -- auth -----------------------------------------------------------------

    def check_auth(self) -> AccountInfo:
        status = self._call("account status", lambda: self.client.account_status())
        account = getattr(status, "account", None)
        if account is None or getattr(account, "uid", None) is None:
            raise AuthenticationError(
                "Authentication failed: the account status response has no account.",
                hint="Check YANDEX_MUSIC_TOKEN and run `yavolna auth-check`.",
            )
        subscription = getattr(status, "subscription", None)
        has_sub = None
        if subscription is not None:
            has_sub = bool(
                getattr(subscription, "had_any_subscription", False)
                or getattr(subscription, "auto_renewable", None)
                or getattr(subscription, "non_auto_renewable_remainder", None)
            )
        info = AccountInfo(
            provider=PROVIDER_NAME,
            user_id=str(account.uid),
            login=getattr(account, "login", None),
            display_name=getattr(account, "display_name", None)
            or getattr(account, "full_name", None),
            has_subscription=has_sub,
        )
        self._account = info
        return info

    # -- library --------------------------------------------------------------

    def get_liked_tracks(self) -> list[Track]:
        likes = self._call(
            "liked tracks",
            lambda: self.client.users_likes_tracks(user_id=self._secrets.yandex_music_user_id),
        )
        shorts = list(getattr(likes, "tracks", None) or [])
        if not shorts:
            return []

        liked_at: dict[str, datetime | None] = {}
        album_hints: dict[str, str] = {}
        ids: list[str] = []
        for short in shorts:
            track_id = str(getattr(short, "id", "") or "")
            if not track_id:
                continue
            ids.append(track_id)
            liked_at[track_id] = _parse_timestamp(getattr(short, "timestamp", None))
            album_id = getattr(short, "album_id", None)
            if album_id:
                album_hints[track_id] = str(album_id)

        tracks: list[Track] = []
        for batch in _chunks(ids, TRACK_BATCH_SIZE):
            raw_tracks = self._call("track metadata", lambda b=batch: self.client.tracks(b))
            for raw in raw_tracks or []:
                track = self._to_track(raw, liked=True)
                if track is None:
                    continue
                if track.album_id is None and track.provider_track_id in album_hints:
                    track.album_id = album_hints[track.provider_track_id]
                stamp = liked_at.get(track.provider_track_id)
                if stamp is not None:
                    track.metadata["liked_at"] = stamp.isoformat()
                tracks.append(track)

        missing = len(ids) - len(tracks)
        if missing > 0:
            log.warning("%d liked tracks could not be resolved to full metadata", missing)
        return tracks

    def get_recent_history(self) -> list[PlaybackEvent]:
        """Recent playback, reconstructed from playback queues.

        The unofficial API exposes no proper history endpoint; queues are the
        closest approximation and are missing for some accounts. Returning an
        empty list is a normal outcome, not an error (spec section 4).
        """
        try:
            queues = self.client.queues_list()
        except Exception as exc:
            log.info("Remote listening history is unavailable (%s)", type(exc).__name__)
            return []

        events: list[PlaybackEvent] = []
        for item in list(queues or [])[:10]:
            queue_id = getattr(item, "id", None)
            if not queue_id:
                continue
            try:
                queue = self.client.queue(queue_id)
            except Exception as exc:
                log.debug("Could not read queue %s (%s)", queue_id, type(exc).__name__)
                continue
            modified = _parse_timestamp(getattr(queue, "modified", None))
            context = getattr(getattr(queue, "context", None), "type", None)
            for entry in list(getattr(queue, "tracks", None) or []):
                track_id = getattr(entry, "track_id", None) or getattr(entry, "id", None)
                if track_id:
                    events.append(
                        PlaybackEvent(
                            provider_track_id=str(track_id).split(":")[0],
                            played_at=modified,
                            context=context,
                        )
                    )
        log.debug("Collected %d playback events from queues", len(events))
        return events

    # -- recommendations ------------------------------------------------------

    def get_recommendations(self, seeds: Sequence[Track], *, limit: int = 20) -> list[Track]:
        collected: dict[str, Track] = {}
        for seed in seeds:
            try:
                similar = self.client.tracks_similar(seed.provider_track_id)
            except Exception as exc:
                log.debug(
                    "No similar tracks for %s (%s)", seed.provider_track_id, type(exc).__name__
                )
                continue
            for raw in list(getattr(similar, "similar_tracks", None) or []):
                track = self._to_track(raw, liked=False)
                if track is None:
                    continue
                track.metadata["seed_track_id"] = seed.provider_track_id
                collected.setdefault(track.provider_track_id, track)
                if len(collected) >= limit:
                    break
            if len(collected) >= limit:
                break
        return list(collected.values())

    def get_personal_wave(self, *, limit: int = 30) -> list[Track]:
        try:
            batch = self.client.rotor_station_tracks(PERSONAL_WAVE_STATION)
        except Exception as exc:
            log.info("Personal wave is unavailable (%s)", type(exc).__name__)
            return []

        tracks: list[Track] = []
        for sequence_item in list(getattr(batch, "sequence", None) or []):
            raw = getattr(sequence_item, "track", None)
            track = self._to_track(raw, liked=False) if raw is not None else None
            if track is not None:
                track.metadata["seed_group"] = "personal_wave"
                tracks.append(track)
            if len(tracks) >= limit:
                break
        return tracks

    # -- playlists ------------------------------------------------------------

    def get_or_create_playlist(
        self, title: str, *, description: str | None = None, visibility: str = "private"
    ) -> Playlist:
        existing = self._find_playlist_by_title(title)
        if existing is not None:
            if description:
                self._set_description(existing.provider_playlist_id, description)
            return existing

        raw = self._call(
            "create playlist",
            lambda: self.client.users_playlists_create(title=title, visibility=visibility),
            error=PlaylistWriteError,
        )
        if raw is None:
            raise PlaylistWriteError(f"Yandex Music did not create the playlist {title!r}.")
        playlist = self._to_playlist(raw)
        if description:
            self._set_description(playlist.provider_playlist_id, description)
        log.info("Created playlist %r (kind=%s)", title, playlist.provider_playlist_id)
        return playlist

    def get_playlist(self, playlist_id: str) -> Playlist | None:
        try:
            raw = self.client.users_playlists(
                playlist_id, user_id=self._secrets.yandex_music_user_id
            )
        except Exception as exc:
            log.debug("Playlist %s is not readable (%s)", playlist_id, type(exc).__name__)
            return None
        if isinstance(raw, list):
            raw = raw[0] if raw else None
        return self._to_playlist(raw) if raw is not None else None

    def list_playlists(self) -> list[Playlist]:
        raws = self._call("list playlists", lambda: self.client.users_playlists_list())
        return [self._to_playlist(raw) for raw in raws or []]

    def delete_playlist(self, playlist_id: str) -> None:
        self._call(
            "delete playlist",
            lambda: self.client.users_playlists_delete(playlist_id),
            error=PlaylistWriteError,
        )
        log.info("Deleted playlist kind=%s", playlist_id)

    def replace_playlist_tracks(self, playlist_id: str, tracks: Sequence[Track]) -> Playlist:
        """Clear the playlist and insert the new sequence, revision by revision.

        Yandex Music mutates playlists through revision-checked diffs, so the
        revision returned by each call has to be fed into the next one
        (spec section 17).
        """
        current = self.get_playlist(playlist_id)
        if current is None:
            raise PlaylistWriteError(
                f"Playlist {playlist_id} is not available for writing.",
                hint="It may have been deleted in the Yandex Music app.",
            )
        revision = current.revision or 1

        if current.track_count:
            revision = self._apply_diff(
                playlist_id,
                revision,
                [{"op": "delete", "from": 0, "to": current.track_count}],
                what=f"clear {current.track_count} tracks",
            )

        position = 0
        for chunk in _chunks(list(tracks), PLAYLIST_CHUNK_SIZE):
            payload = [
                {"id": track.provider_track_id, "albumId": track.album_id}
                for track in chunk
                if track.album_id
            ]
            skipped = len(chunk) - len(payload)
            if skipped:
                log.warning("Skipped %d tracks without an album id (not insertable)", skipped)
            if not payload:
                continue
            revision = self._apply_diff(
                playlist_id,
                revision,
                [{"op": "insert", "at": position, "tracks": payload}],
                what=f"insert {len(payload)} tracks at {position}",
            )
            position += len(payload)

        updated = self.get_playlist(playlist_id)
        return updated or current

    def _apply_diff(
        self, playlist_id: str, revision: int, diff: list[dict[str, Any]], *, what: str
    ) -> int:
        raw = self._call(
            f"playlist update ({what})",
            lambda: self.client.users_playlists_change(
                kind=playlist_id, diff=json.dumps(diff), revision=revision
            ),
            error=PlaylistWriteError,
        )
        if raw is None:
            raise PlaylistWriteError(f"Playlist update failed: {what}.")
        new_revision = getattr(raw, "revision", None)
        return int(new_revision) if new_revision is not None else revision + 1

    def _find_playlist_by_title(self, title: str) -> Playlist | None:
        for playlist in self.list_playlists():
            if playlist.title == title:
                return playlist
        return None

    def _set_description(self, playlist_id: str, description: str) -> None:
        try:
            self.client.users_playlists_description(kind=playlist_id, description=description)
        except Exception as exc:
            log.debug("Could not set playlist description (%s)", type(exc).__name__)

    # -- conversion -----------------------------------------------------------

    def _to_track(self, raw: Any, *, liked: bool) -> Track | None:
        track_id = getattr(raw, "id", None)
        title = getattr(raw, "title", None)
        if not track_id or not title:
            return None

        artists = list(getattr(raw, "artists", None) or [])
        albums = list(getattr(raw, "albums", None) or [])
        album = albums[0] if albums else None

        genres: list[str] = []
        if album is not None and getattr(album, "genre", None):
            genres.append(str(album.genre))
        for artist in artists:
            for genre in list(getattr(artist, "genres", None) or []):
                genres.append(str(genre))

        duration_ms = getattr(raw, "duration_ms", None)
        duration = int(duration_ms // 1000) if duration_ms else None

        return Track(
            provider=PROVIDER_NAME,
            provider_track_id=str(track_id),
            title=str(title),
            artist_ids=tuple(str(a.id) for a in artists if getattr(a, "id", None)),
            artist_names=tuple(str(a.name) for a in artists if getattr(a, "name", None)),
            album_id=str(album.id) if album is not None and getattr(album, "id", None) else None,
            album_title=str(getattr(album, "title", "")) or None if album is not None else None,
            duration_seconds=duration,
            genres=tuple(dict.fromkeys(genres)),
            release_year=_first_year(album),
            liked=liked,
            explicit=bool(getattr(raw, "explicit", False) or getattr(raw, "content_warning", None)),
            available=bool(getattr(raw, "available", True)),
            content_type=_content_type(raw, album),
            metadata={},
        )

    def _to_playlist(self, raw: Any) -> Playlist:
        kind = getattr(raw, "kind", None)
        owner = getattr(raw, "owner", None)
        login = getattr(owner, "login", None) if owner is not None else None
        uid = getattr(owner, "uid", None) if owner is not None else None
        url = f"https://music.yandex.ru/users/{login or uid}/playlists/{kind}" if kind else None
        return Playlist(
            provider=PROVIDER_NAME,
            provider_playlist_id=str(kind),
            title=str(getattr(raw, "title", "") or ""),
            track_count=int(getattr(raw, "track_count", 0) or 0),
            revision=int(getattr(raw, "revision", 0) or 0) or None,
            url=url,
            raw=None,
        )

    # -- plumbing -------------------------------------------------------------

    def _call(self, what: str, action: Any, *, error: type[YaVolnaError] = ProviderError) -> Any:
        """Run a provider call, mapping library failures to our own errors."""
        try:
            return action()
        except Exception as exc:
            name = type(exc).__name__
            if name in {"UnauthorizedError", "InvalidBearerTokenError"}:
                raise AuthenticationError(
                    f"Yandex Music rejected the credentials while performing: {what}.",
                    hint="Check YANDEX_MUSIC_TOKEN and run `yavolna auth-check`.",
                ) from exc
            raise error(
                f"Yandex Music request failed ({what}): {name}",
                hint="The unofficial API may have changed; rerun with --debug for details.",
            ) from exc


def _chunks(items: list[Any], size: int) -> Iterable[list[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


#: Yandex reports the same thing under several names; normalize to one word.
_CONTENT_TYPE_ALIASES: dict[str, str] = {
    "podcast-episode": "podcast",
    "podcast": "podcast",
    "audiobook": "audiobook",
    "audiobook-part": "audiobook",
    "fairy-tale": "audiobook",
    "article": "article",
    "music": "music",
}


def _content_type(raw: Any, album: Any) -> str:
    """Music, podcast episode, audiobook chapter, ...

    Yandex marks non-music both on the track (`type`) and on its album
    (`meta_type`), and not always on both, so any non-music marker wins.
    """
    for value in (getattr(raw, "type", None), getattr(album, "meta_type", None)):
        if not value:
            continue
        key = str(value).strip().casefold()
        normalized = _CONTENT_TYPE_ALIASES.get(key, key)
        if normalized != "music":
            return normalized
    return "music"


def _first_year(album: Any) -> int | None:
    if album is None:
        return None
    for attribute in ("original_release_year", "year"):
        value = getattr(album, attribute, None)
        if value:
            try:
                return int(str(value)[:4])
            except ValueError:
                continue
    return None


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, int | float):
        try:
            return datetime.fromtimestamp(float(value) / (1000 if value > 1e11 else 1), tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
