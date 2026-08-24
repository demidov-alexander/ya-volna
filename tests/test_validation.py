from __future__ import annotations

import pytest

from tests.conftest import make_track
from yavolna.config import AppConfig
from yavolna.errors import PlaylistValidationError
from yavolna.library.models import MixResult, PlaylistEntry, SourceType
from yavolna.playlists.validation import ensure_valid, validate_result


def result_with(tracks, *, target: int = 3600, familiar: int | None = None, **kwargs) -> MixResult:
    familiar = len(tracks) if familiar is None else familiar
    entries = [
        PlaylistEntry(
            position=index,
            track=track,
            source_type=SourceType.FAMILIAR if index < familiar else SourceType.DISCOVERY,
            cluster_id=track.cluster_id or "c1",
        )
        for index, track in enumerate(tracks)
    ]
    total = sum(track.duration_seconds or 0 for track in tracks)
    return MixResult(
        entries=entries, total_duration_seconds=total, target_duration_seconds=target, **kwargs
    )


def config_for(**overrides) -> AppConfig:
    payload = {"mix": {"familiar_ratio": 1.0, "discovery_ratio": 0.0}}
    payload.update(overrides)
    return AppConfig.model_validate(payload)


def test_valid_playlist_has_no_problems():
    tracks = [make_track(str(i), duration=360) for i in range(10)]
    assert validate_result(result_with(tracks), config_for()) == []


def test_empty_playlist_is_reported():
    problems = validate_result(MixResult(target_duration_seconds=3600), config_for())
    assert problems == ["the generated playlist is empty"]


def test_duplicates_are_reported():
    tracks = [make_track("1", duration=1800), make_track("1", duration=1800)]
    problems = validate_result(result_with(tracks), config_for())
    assert any("duplicate track ids" in problem for problem in problems)


def test_unavailable_tracks_are_reported():
    tracks = [make_track("1", duration=1800), make_track("2", duration=1800, available=False)]
    problems = validate_result(result_with(tracks), config_for())
    assert any("unavailable" in problem for problem in problems)


def test_duration_deviation_is_reported():
    tracks = [make_track("1", duration=600)]
    problems = validate_result(result_with(tracks, target=3600), config_for())
    assert any("deviates" in problem and "target" in problem for problem in problems)


def test_duration_within_tolerance_passes():
    tracks = [make_track(str(i), duration=350) for i in range(10)]  # 3500s vs 3600s target
    assert validate_result(result_with(tracks, target=3600), config_for()) == []


def test_ratio_deviation_is_reported():
    tracks = [make_track(str(i), duration=360) for i in range(10)]
    config = AppConfig.model_validate({"mix": {"familiar_ratio": 0.5, "discovery_ratio": 0.5}})
    problems = validate_result(result_with(tracks, familiar=10), config)
    assert any("ratio" in problem for problem in problems)


def test_ratio_deviation_is_accepted_when_the_run_stopped_early():
    tracks = [make_track(str(i), duration=360) for i in range(10)]
    config = AppConfig.model_validate({"mix": {"familiar_ratio": 0.5, "discovery_ratio": 0.5}})
    problems = validate_result(
        result_with(tracks, familiar=10, stopped_early=True, stop_reason="pool exhausted"), config
    )
    assert problems == []


def test_max_playlist_tracks_is_reported():
    tracks = [make_track(str(i), duration=10) for i in range(30)]
    config = config_for(validation={"max_playlist_tracks": 20, "duration_tolerance": 1.0})
    problems = validate_result(result_with(tracks, target=300), config)
    assert any("max_playlist_tracks" in problem for problem in problems)


def test_ensure_valid_raises_with_a_hint():
    with pytest.raises(PlaylistValidationError) as excinfo:
        ensure_valid(MixResult(target_duration_seconds=3600), config_for())
    assert excinfo.value.problems
    assert excinfo.value.hint
    assert excinfo.value.exit_code == 8
