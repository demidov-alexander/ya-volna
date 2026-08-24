from __future__ import annotations

import contextlib
from datetime import UTC, datetime, timedelta

from tests.conftest import make_track
from yavolna.library.models import PlaylistEntry, SourceType
from yavolna.persistence.db import SCHEMA_VERSION, connect
from yavolna.persistence.repository import Repository


def entries(count: int = 3, prefix: str = "t") -> list[PlaylistEntry]:
    return [
        PlaylistEntry(
            position=index,
            track=make_track(f"{prefix}{index}", cluster="c1", liked=index % 2 == 0),
            source_type=SourceType.FAMILIAR if index % 2 == 0 else SourceType.DISCOVERY,
            cluster_id="c1",
        )
        for index in range(count)
    ]


def commit(repository: Repository, items, **overrides):
    payload = {
        "entries": items,
        "status": "success",
        "started_at": datetime.now(UTC),
        "playlist_id": "p1",
        "playlist_title": "Daily Chaos",
        "target_duration_seconds": 3600,
        "actual_duration_seconds": 3500,
        "familiar_count": 2,
        "discovery_count": 1,
        "random_seed": 42,
    }
    payload.update(overrides)
    return repository.commit_run(**payload)


def test_schema_is_created(repository):
    row = repository._connection.execute("SELECT version FROM schema_version").fetchone()
    assert row["version"] == SCHEMA_VERSION


def test_commit_run_records_entries_and_track_state(repository):
    run_id = commit(repository, entries(3))
    assert run_id == 1

    counts = repository.generation_counts()
    assert counts == {"t0": 1, "t1": 1, "t2": 1}

    last_generated = repository.last_generated_map()
    assert set(last_generated) == {"t0", "t1", "t2"}
    assert last_generated["t0"].tzinfo is not None


def test_generation_count_increments_across_runs(repository):
    commit(repository, entries(2))
    commit(repository, entries(2))
    assert repository.generation_counts() == {"t0": 2, "t1": 2}


def test_last_generated_map_can_be_windowed(repository):
    commit(repository, entries(1))
    assert repository.last_generated_map(within_days=1)
    repository._connection.execute(
        "UPDATE track_state SET last_generated_at = ?",
        ((datetime.now(UTC) - timedelta(days=30)).isoformat(),),
    )
    assert repository.last_generated_map(within_days=7) == {}
    assert repository.last_generated_map(within_days=60)


def test_recently_generated_ids(repository):
    commit(repository, entries(2))
    assert repository.recently_generated_ids(within_days=5) == {"t0", "t1"}


def test_stats_and_last_run(repository):
    commit(repository, entries(3))
    stats = repository.stats()
    assert stats["runs_total"] == 1
    assert stats["runs_successful"] == 1
    assert stats["known_tracks"] == 3
    assert stats["total_selections"] == 3
    last = repository.last_run()
    assert last is not None
    assert last["playlist_title"] == "Daily Chaos"


def test_top_tracks_orders_by_frequency(repository):
    commit(repository, entries(3))
    commit(repository, entries(1))
    top = repository.top_tracks(limit=2)
    assert top[0]["provider_track_id"] == "t0"
    assert top[0]["generation_count"] == 2


def test_prune_removes_old_runs(repository):
    commit(repository, entries(2))
    repository._connection.execute(
        "UPDATE generation_runs SET started_at = ?",
        ((datetime.now(UTC) - timedelta(days=400)).isoformat(),),
    )
    removed = repository.prune(retention_days=180)
    assert removed == 1
    assert repository.stats()["runs_total"] == 0


def test_prune_keeps_recent_runs(repository):
    commit(repository, entries(2))
    assert repository.prune(retention_days=180) == 0
    assert repository.stats()["runs_total"] == 1


def test_entries_are_removed_with_their_run(repository):
    commit(repository, entries(2))
    repository._connection.execute("DELETE FROM generation_runs")
    remaining = repository._connection.execute(
        "SELECT COUNT(*) AS n FROM playlist_entries"
    ).fetchone()
    assert remaining["n"] == 0


def test_managed_playlists_roundtrip(repository):
    repository.remember_managed_playlist("fake", "p1", "Daily Chaos", "")
    found = repository.find_managed_playlist("fake", "")
    assert found is not None
    assert found["playlist_id"] == "p1"
    assert repository.find_managed_playlist("fake", "2026-08-24") is None


def test_managed_playlists_are_ordered_newest_first(repository):
    for day in ("2026-08-20", "2026-08-24", "2026-08-22"):
        repository.remember_managed_playlist("fake", f"p-{day}", f"Mix {day}", day)
    keys = [row["date_key"] for row in repository.managed_playlists("fake")]
    assert keys == ["2026-08-24", "2026-08-22", "2026-08-20"]


def test_remembering_the_same_playlist_updates_it(repository):
    repository.remember_managed_playlist("fake", "p1", "Old", "2026-08-24")
    repository.remember_managed_playlist("fake", "p1", "New", "2026-08-24")
    rows = repository.managed_playlists("fake")
    assert len(rows) == 1
    assert rows[0]["title"] == "New"


def test_forget_managed_playlist(repository):
    repository.remember_managed_playlist("fake", "p1", "Mix", "")
    repository.forget_managed_playlist("fake", "p1")
    assert repository.managed_playlists("fake") == []


def test_liked_ids_are_recorded_without_inflating_counts(repository):
    commit(repository, entries(1), liked_ids=["liked-only"])
    assert "liked-only" not in repository.generation_counts()
    row = repository._connection.execute(
        "SELECT last_seen_liked FROM track_state WHERE provider_track_id = 'liked-only'"
    ).fetchone()
    assert row["last_seen_liked"]


def test_failed_commit_rolls_back(repository):
    bad = entries(2)
    bad[1].position = 0  # duplicate primary key inside the same run
    with contextlib.suppress(Exception):
        commit(repository, bad)
    assert repository.stats()["runs_total"] == 0
    assert repository.generation_counts() == {}


def test_database_file_is_created(tmp_path):
    path = tmp_path / "nested" / "db.sqlite3"
    connection = connect(path)
    connection.close()
    assert path.exists()
