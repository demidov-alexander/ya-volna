"""SQLite bootstrap for the anti-repetition database (spec section 16)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from yavolna.errors import DatabaseError
from yavolna.logging import get_logger

log = get_logger(__name__)

SCHEMA_VERSION = 1

SCHEMA: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS generation_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        status TEXT NOT NULL,
        playlist_id TEXT,
        playlist_title TEXT,
        target_duration_seconds INTEGER,
        actual_duration_seconds INTEGER,
        familiar_count INTEGER,
        discovery_count INTEGER,
        random_seed INTEGER,
        notes TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS playlist_entries (
        run_id INTEGER NOT NULL REFERENCES generation_runs(id) ON DELETE CASCADE,
        position INTEGER NOT NULL,
        provider_track_id TEXT NOT NULL,
        cluster_id TEXT,
        source_type TEXT NOT NULL,
        selected_at TEXT NOT NULL,
        PRIMARY KEY (run_id, position)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS track_state (
        provider_track_id TEXT PRIMARY KEY,
        last_generated_at TEXT,
        generation_count INTEGER NOT NULL DEFAULT 0,
        last_seen_liked TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS managed_playlists (
        provider TEXT NOT NULL,
        playlist_id TEXT NOT NULL,
        title TEXT NOT NULL,
        date_key TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (provider, playlist_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_entries_track ON playlist_entries(provider_track_id)",
    "CREATE INDEX IF NOT EXISTS idx_runs_started ON generation_runs(started_at)",
    "CREATE INDEX IF NOT EXISTS idx_managed_date ON managed_playlists(date_key)",
)


def connect(database_path: Path | str) -> sqlite3.Connection:
    """Open (creating if needed) the local database and apply the schema."""
    path = Path(database_path)
    try:
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path, isolation_level=None)
    except (OSError, sqlite3.Error) as exc:
        raise DatabaseError(
            f"Could not open the database at {path}: {exc}",
            hint="Check runtime.database_path and directory permissions.",
        ) from exc

    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        _apply_schema(connection)
    except sqlite3.Error as exc:
        connection.close()
        raise DatabaseError(f"Could not initialise the database schema: {exc}") from exc
    return connection


def _apply_schema(connection: sqlite3.Connection) -> None:
    for statement in SCHEMA:
        connection.execute(statement)
    row = connection.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    if row is None:
        connection.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
    elif int(row["version"]) > SCHEMA_VERSION:
        raise DatabaseError(
            f"The database was written by a newer version of yavolna "
            f"(schema {row['version']} > {SCHEMA_VERSION}).",
            hint="Upgrade yavolna or point runtime.database_path at a new file.",
        )
    else:
        connection.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))
