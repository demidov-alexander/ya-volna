"""Queries over the local anti-repetition database (spec sections 16 and 17)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from yavolna.errors import DatabaseError
from yavolna.library.models import PlaylistEntry
from yavolna.logging import get_logger

log = get_logger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(stamp: datetime) -> str:
    return stamp.astimezone(UTC).isoformat()


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class Repository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    # -- reads ----------------------------------------------------------------

    def last_generated_map(self, *, within_days: int | None = None) -> dict[str, datetime]:
        """provider_track_id -> when it was last put into a generated playlist."""
        sql = "SELECT provider_track_id, last_generated_at FROM track_state WHERE last_generated_at IS NOT NULL"
        params: list[Any] = []
        if within_days is not None:
            sql += " AND last_generated_at >= ?"
            params.append(_iso(_now() - timedelta(days=within_days)))
        result: dict[str, datetime] = {}
        for row in self._query(sql, params):
            stamp = _parse(row["last_generated_at"])
            if stamp is not None:
                result[row["provider_track_id"]] = stamp
        return result

    def generation_counts(self) -> dict[str, int]:
        return {
            row["provider_track_id"]: int(row["generation_count"])
            for row in self._query(
                "SELECT provider_track_id, generation_count FROM track_state WHERE generation_count > 0",
                [],
            )
        }

    def recently_generated_ids(self, *, within_days: int) -> set[str]:
        return set(self.last_generated_map(within_days=within_days))

    def last_run(self) -> dict[str, Any] | None:
        rows = self._query(
            "SELECT * FROM generation_runs ORDER BY id DESC LIMIT 1",
            [],
        )
        return dict(rows[0]) if rows else None

    def stats(self) -> dict[str, Any]:
        runs = self._query(
            """
            SELECT COUNT(*) AS total,
                   SUM(status = 'success') AS successful,
                   MIN(started_at) AS first_run,
                   MAX(started_at) AS last_run
            FROM generation_runs
            """,
            [],
        )[0]
        tracks = self._query(
            """
            SELECT COUNT(*) AS known_tracks,
                   SUM(generation_count) AS total_selections,
                   MAX(generation_count) AS most_selected
            FROM track_state
            """,
            [],
        )[0]
        playlists = self._query("SELECT COUNT(*) AS managed FROM managed_playlists", [])[0]
        return {
            "runs_total": int(runs["total"] or 0),
            "runs_successful": int(runs["successful"] or 0),
            "first_run": runs["first_run"],
            "last_run": runs["last_run"],
            "known_tracks": int(tracks["known_tracks"] or 0),
            "total_selections": int(tracks["total_selections"] or 0),
            "most_selected_count": int(tracks["most_selected"] or 0),
            "managed_playlists": int(playlists["managed"] or 0),
        }

    def top_tracks(self, limit: int = 10) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self._query(
                """
                SELECT provider_track_id, generation_count, last_generated_at
                FROM track_state
                ORDER BY generation_count DESC, last_generated_at DESC
                LIMIT ?
                """,
                [limit],
            )
        ]

    # -- managed playlists ----------------------------------------------------

    def find_managed_playlist(self, provider: str, date_key: str = "") -> dict[str, Any] | None:
        rows = self._query(
            """
            SELECT * FROM managed_playlists
            WHERE provider = ? AND date_key = ?
            ORDER BY updated_at DESC LIMIT 1
            """,
            [provider, date_key],
        )
        return dict(rows[0]) if rows else None

    def remember_managed_playlist(
        self, provider: str, playlist_id: str, title: str, date_key: str = ""
    ) -> None:
        now = _iso(_now())
        self._execute(
            """
            INSERT INTO managed_playlists (provider, playlist_id, title, date_key, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(provider, playlist_id) DO UPDATE SET
                title = excluded.title,
                date_key = excluded.date_key,
                updated_at = excluded.updated_at
            """,
            [provider, playlist_id, title, date_key, now, now],
        )

    def managed_playlists(self, provider: str) -> list[dict[str, Any]]:
        """Newest first, by date_key then creation time."""
        return [
            dict(row)
            for row in self._query(
                """
                SELECT * FROM managed_playlists
                WHERE provider = ?
                ORDER BY date_key DESC, created_at DESC
                """,
                [provider],
            )
        ]

    def forget_managed_playlist(self, provider: str, playlist_id: str) -> None:
        self._execute(
            "DELETE FROM managed_playlists WHERE provider = ? AND playlist_id = ?",
            [provider, playlist_id],
        )

    # -- writes ---------------------------------------------------------------

    def commit_run(
        self,
        *,
        entries: Sequence[PlaylistEntry],
        status: str,
        started_at: datetime,
        playlist_id: str | None,
        playlist_title: str | None,
        target_duration_seconds: int,
        actual_duration_seconds: int,
        familiar_count: int,
        discovery_count: int,
        random_seed: int | None,
        notes: str | None = None,
        liked_ids: Iterable[str] = (),
    ) -> int:
        """Persist a finished run atomically (spec section 17, step 5).

        Called only after the remote playlist update succeeded.
        """
        now = _now()
        try:
            with self._transaction() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO generation_runs (
                        started_at, finished_at, status, playlist_id, playlist_title,
                        target_duration_seconds, actual_duration_seconds,
                        familiar_count, discovery_count, random_seed, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _iso(started_at),
                        _iso(now),
                        status,
                        playlist_id,
                        playlist_title,
                        target_duration_seconds,
                        actual_duration_seconds,
                        familiar_count,
                        discovery_count,
                        random_seed,
                        notes,
                    ),
                )
                run_id = int(cursor.lastrowid or 0)

                connection.executemany(
                    """
                    INSERT INTO playlist_entries
                        (run_id, position, provider_track_id, cluster_id, source_type, selected_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            run_id,
                            entry.position,
                            entry.track.provider_track_id,
                            entry.cluster_id,
                            str(entry.source_type),
                            _iso(now),
                        )
                        for entry in entries
                    ],
                )

                connection.executemany(
                    """
                    INSERT INTO track_state (provider_track_id, last_generated_at, generation_count, last_seen_liked)
                    VALUES (?, ?, 1, ?)
                    ON CONFLICT(provider_track_id) DO UPDATE SET
                        last_generated_at = excluded.last_generated_at,
                        generation_count = track_state.generation_count + 1,
                        last_seen_liked = COALESCE(excluded.last_seen_liked, track_state.last_seen_liked)
                    """,
                    [
                        (
                            entry.track.provider_track_id,
                            _iso(now),
                            _iso(now) if entry.track.liked else None,
                        )
                        for entry in entries
                    ],
                )

                liked = [(_iso(now), track_id) for track_id in liked_ids]
                if liked:
                    connection.executemany(
                        """
                        INSERT INTO track_state (provider_track_id, generation_count, last_seen_liked)
                        VALUES (?, 0, ?)
                        ON CONFLICT(provider_track_id) DO UPDATE SET last_seen_liked = excluded.last_seen_liked
                        """,
                        [(track_id, stamp) for stamp, track_id in liked],
                    )
        except sqlite3.Error as exc:
            raise DatabaseError(f"Could not store the generation run: {exc}") from exc

        log.info("Stored generation run #%d with %d entries", run_id, len(entries))
        return run_id

    def prune(self, *, retention_days: int) -> int:
        """Drop runs older than the retention window (spec section 7, history.*)."""
        cutoff = _iso(_now() - timedelta(days=retention_days))
        try:
            with self._transaction() as connection:
                cursor = connection.execute(
                    "DELETE FROM generation_runs WHERE started_at < ?", (cutoff,)
                )
                removed = cursor.rowcount or 0
                connection.execute(
                    """
                    DELETE FROM track_state
                    WHERE last_generated_at IS NOT NULL AND last_generated_at < ?
                      AND provider_track_id NOT IN (SELECT provider_track_id FROM playlist_entries)
                    """,
                    (cutoff,),
                )
        except sqlite3.Error as exc:
            raise DatabaseError(f"Could not prune old history: {exc}") from exc
        if removed:
            log.debug("Pruned %d generation runs older than %d days", removed, retention_days)
        return removed

    # -- plumbing -------------------------------------------------------------

    class _Transaction:
        def __init__(self, connection: sqlite3.Connection) -> None:
            self._connection = connection

        def __enter__(self) -> sqlite3.Connection:
            self._connection.execute("BEGIN")
            return self._connection

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            if exc_type is None:
                self._connection.execute("COMMIT")
            else:
                self._connection.execute("ROLLBACK")

    def _transaction(self) -> Repository._Transaction:
        return Repository._Transaction(self._connection)

    def _query(self, sql: str, params: Sequence[Any]) -> list[sqlite3.Row]:
        try:
            return list(self._connection.execute(sql, tuple(params)).fetchall())
        except sqlite3.Error as exc:
            raise DatabaseError(f"Database query failed: {exc}") from exc

    def _execute(self, sql: str, params: Sequence[Any]) -> None:
        try:
            self._connection.execute(sql, tuple(params))
        except sqlite3.Error as exc:
            raise DatabaseError(f"Database write failed: {exc}") from exc

    def close(self) -> None:
        self._connection.close()
