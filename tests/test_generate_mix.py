"""End-to-end pipeline tests against the fake provider (spec section 22.2)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from yavolna.config import AppConfig
from yavolna.errors import ConfigurationError, ProviderError
from yavolna.providers.fake import FakeMusicProvider
from yavolna.services.generate_mix import GenerateMixService, describe_mode

NOW = datetime(2026, 8, 24, 6, 0, tzinfo=UTC)


def service_for(provider, repository, tmp_path, **overrides) -> GenerateMixService:
    payload = {
        "playlist": {"name": "Test Mix", "target_duration_hours": 2},
        "selection": {"minimum_liked_tracks": 5, "random_seed": 42},
        "runtime": {"dry_run_export_dir": str(tmp_path)},
        "validation": {"duration_tolerance": 0.2},
    }
    for section, values in overrides.items():
        payload.setdefault(section, {}).update(values)
    return GenerateMixService(
        provider=provider,
        config=AppConfig.model_validate(payload),
        repository=repository,
        now=NOW,
    )


def test_dry_run_does_not_touch_the_provider(provider, repository, tmp_path):
    report = service_for(provider, repository, tmp_path).run(dry_run=True)

    assert report.result is not None
    assert report.playlist is None
    assert provider.list_playlists() == []
    assert repository.stats()["runs_total"] == 0
    assert report.export_path is not None and report.export_path.exists()


def test_dry_run_export_contains_the_proposed_sequence(provider, repository, tmp_path):
    report = service_for(provider, repository, tmp_path).run(dry_run=True, seed=7)
    payload = json.loads(report.export_path.read_text(encoding="utf-8"))

    assert payload["seed"] == 7
    assert payload["playlist_title"] == "Test Mix"
    assert len(payload["tracks"]) == len(report.result.entries)
    assert payload["tracks"][0]["position"] == 0
    assert {"familiar", "discovery"} >= {track["source"] for track in payload["tracks"]}


def test_full_run_publishes_and_persists(provider, repository, tmp_path):
    report = service_for(provider, repository, tmp_path).run()

    assert report.playlist is not None
    assert report.run_id == 1
    published = provider.playlist_tracks(report.playlist.provider_playlist_id)
    assert len(published) == len(report.result.entries)
    assert repository.stats()["runs_total"] == 1
    assert repository.generation_counts()


def test_second_run_avoids_repeating_the_previous_playlist(provider, repository, tmp_path):
    first = service_for(provider, repository, tmp_path).run(seed=1)
    second_service = GenerateMixService(
        provider=provider,
        config=first_config(tmp_path),
        repository=repository,
        now=NOW + timedelta(days=1),
    )
    second = second_service.run(seed=1)

    first_ids = {entry.track.provider_track_id for entry in first.result.entries}
    second_ids = {entry.track.provider_track_id for entry in second.result.entries}
    overlap = len(first_ids & second_ids) / len(second_ids)
    assert overlap < 0.5


def first_config(tmp_path) -> AppConfig:
    return AppConfig.model_validate(
        {
            "playlist": {"name": "Test Mix", "target_duration_hours": 2},
            "selection": {"minimum_liked_tracks": 5, "random_seed": 42},
            "runtime": {"dry_run_export_dir": str(tmp_path)},
            "validation": {"duration_tolerance": 0.2},
        }
    )


def test_seed_makes_the_whole_pipeline_reproducible(repository, tmp_path):
    ids = []
    for _ in range(2):
        provider = FakeMusicProvider(liked_count=120, catalog_count=600, seed=1)
        report = service_for(provider, repository, tmp_path).run(dry_run=True, seed=99)
        ids.append([entry.track.provider_track_id for entry in report.result.entries])
    assert ids[0] == ids[1]


def test_too_small_library_is_an_actionable_error(repository, tmp_path):
    provider = FakeMusicProvider(liked_count=6, catalog_count=40, seed=2)
    service = service_for(provider, repository, tmp_path, selection={"minimum_liked_tracks": 50})
    with pytest.raises(ConfigurationError) as excinfo:
        service.run(dry_run=True)
    assert "minimum_liked_tracks" in str(excinfo.value)
    assert excinfo.value.hint


def test_empty_library_is_reported(repository, tmp_path):
    provider = FakeMusicProvider(liked_count=0, catalog_count=40, seed=2)
    with pytest.raises(ProviderError, match="no liked tracks"):
        service_for(provider, repository, tmp_path).run(dry_run=True)


def test_discovery_failure_degrades_to_familiar_only(repository, tmp_path):
    provider = FakeMusicProvider(
        liked_count=200, catalog_count=600, seed=3, fail_recommendations=True
    )
    service = service_for(
        provider,
        repository,
        tmp_path,
        discovery={"use_personal_wave": False},
        validation={"ratio_tolerance": 1.0, "duration_tolerance": 0.2},
    )
    report = service.run(dry_run=True)
    assert report.discovery_pool == 0
    assert report.result.discovery_count == 0
    assert report.result.familiar_count > 0


def test_missing_remote_history_is_not_fatal(repository, tmp_path):
    provider = FakeMusicProvider(liked_count=120, catalog_count=600, seed=4, supports_history=False)
    report = service_for(provider, repository, tmp_path).run(dry_run=True)
    assert report.remote_history_events == 0
    assert report.result.entries


def test_remote_history_is_used_as_a_cooldown_hint(provider, repository, tmp_path):
    service = service_for(
        provider, repository, tmp_path, history={"use_remote_listening_history": True}
    )
    report = service.run(dry_run=True)
    assert report.remote_history_events > 0


def test_blocked_tracks_never_appear(provider, repository, tmp_path):
    blocked = [track.provider_track_id for track in provider.get_liked_tracks()[:10]]
    service = service_for(provider, repository, tmp_path, exclusions={"blocked_track_ids": blocked})
    report = service.run(dry_run=True)
    selected = {entry.track.provider_track_id for entry in report.result.entries}
    assert selected.isdisjoint(blocked)


def test_daily_new_mode_titles_the_playlist_with_the_date(provider, repository, tmp_path):
    service = service_for(provider, repository, tmp_path, playlist={"mode": "daily_new"})
    report = service.run()
    assert report.playlist_title == "Test Mix 2026-08-24"
    assert report.playlist.title == "Test Mix 2026-08-24"


def test_report_summary_is_human_readable(provider, repository, tmp_path):
    report = service_for(provider, repository, tmp_path).run(dry_run=True)
    text = "\n".join(report.summary_lines())
    assert "library:" in text
    assert "mix:" in text
    assert "dry-run export:" in text


def test_describe_mode():
    replace = AppConfig()
    assert "one playlist" in describe_mode(replace)
    daily = AppConfig.model_validate({"playlist": {"mode": "daily_new", "keep_daily_playlists": 3}})
    assert "keeping the last 3" in describe_mode(daily)
