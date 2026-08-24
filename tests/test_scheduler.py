from __future__ import annotations

import itertools
import random
from datetime import timedelta

from tests.conftest import NOW, make_track
from yavolna.config import AppConfig
from yavolna.library.models import SourceType
from yavolna.mixing.candidate_pool import CandidatePool, PoolSet
from yavolna.mixing.scheduler import Scheduler

CLUSTERS = ("c1", "c2", "c3", "c4")


def pools(familiar_count: int = 300, discovery_count: int = 300) -> PoolSet:
    familiar = [
        make_track(
            f"f{i}",
            artist=f"fa{i % 40}",
            album=f"fal{i % 25}",
            cluster=CLUSTERS[i % len(CLUSTERS)],
            duration=200 + (i % 7) * 10,
            liked=True,
        )
        for i in range(familiar_count)
    ]
    discovery = [
        make_track(
            f"d{i}",
            artist=f"da{i % 45}",
            album=f"dal{i % 30}",
            cluster=CLUSTERS[i % len(CLUSTERS)],
            duration=190 + (i % 5) * 15,
            seed_group="cluster:test",
        )
        for i in range(discovery_count)
    ]
    return PoolSet(familiar=familiar, discovery=discovery)


def config_for(hours: float = 4.0, **overrides) -> AppConfig:
    payload = {
        "playlist": {"target_duration_hours": hours},
        "repetition": {
            "same_artist_gap_tracks": 10,
            "same_album_gap_tracks": 15,
            "same_cluster_gap_tracks": 2,
        },
        "validation": {"duration_tolerance": 0.2},
    }
    payload.update(overrides)
    return AppConfig.model_validate(payload)


def build(seed: int = 42, **kwargs):
    config = kwargs.pop("config", config_for())
    scheduler = Scheduler(
        config,
        kwargs.pop("pools", pools()),
        rng=random.Random(seed),
        cluster_sizes=dict.fromkeys(CLUSTERS, 75),
        now=NOW,
        **kwargs,
    )
    return scheduler.build()


def test_reaches_the_target_duration():
    result = build()
    target = 4 * 3600
    assert result.total_duration_seconds >= target
    assert result.total_duration_seconds - target < 400  # overshoot is one track at most


def test_same_seed_reproduces_the_playlist():
    first = build(seed=7)
    second = build(seed=7)
    assert [e.track.provider_track_id for e in first.entries] == [
        e.track.provider_track_id for e in second.entries
    ]


def test_different_seeds_produce_different_playlists():
    first = [e.track.provider_track_id for e in build(seed=1).entries]
    second = [e.track.provider_track_id for e in build(seed=2).entries]
    assert first != second


def test_no_duplicate_tracks():
    ids = [e.track.provider_track_id for e in build().entries]
    assert len(ids) == len(set(ids))


def test_respects_the_configured_ratio():
    result = build()
    assert abs(result.familiar_ratio - 0.65) < 0.05


def test_ratio_is_configurable():
    config = config_for(mix={"familiar_ratio": 0.3, "discovery_ratio": 0.7})
    result = build(config=config)
    assert abs(result.familiar_ratio - 0.3) < 0.05


def test_familiar_only_configuration():
    config = config_for(mix={"familiar_ratio": 1.0, "discovery_ratio": 0.0})
    result = build(config=config, pools=pools(discovery_count=0))
    assert result.discovery_count == 0


def test_artist_album_and_cluster_gaps_are_respected():
    result = build()
    last_artist: dict[str, int] = {}
    last_album: dict[str, int] = {}
    last_cluster: dict[str, int] = {}
    for position, entry in enumerate(result.entries):
        if entry.relaxation:  # relaxed positions are allowed to break the gaps
            pass
        else:
            for artist in entry.track.artist_ids:
                assert position - last_artist.get(artist, -99) >= 10
            assert position - last_album.get(entry.track.album_id, -99) >= 15
            assert position - last_cluster.get(entry.cluster_id, -99) >= 2
        for artist in entry.track.artist_ids:
            last_artist[artist] = position
        last_album[entry.track.album_id] = position
        last_cluster[entry.cluster_id] = position


def test_clusters_alternate_rather_than_clump():
    result = build()
    clusters = [entry.cluster_id for entry in result.entries]
    runs = sum(1 for a, b in itertools.pairwise(clusters) if a == b)
    assert runs / len(clusters) < 0.05
    assert len(set(clusters)) == len(CLUSTERS)


def test_cooldown_is_relaxed_before_the_ratio_is_sacrificed():
    """Spec 14.6 puts cooldown relaxation (step 4) ahead of ratio deviation (step 5)."""
    last_generated = {f"f{i}": NOW - timedelta(days=1) for i in range(300)}
    result = build(last_generated=last_generated)
    assert result.relaxation_counts.get("cooldown")
    assert "ratio" not in result.relaxation_counts
    assert abs(result.familiar_ratio - 0.65) < 0.05


def test_least_recently_generated_tracks_win_inside_a_relaxed_level():
    last_generated = {f"f{i}": NOW - timedelta(days=1) for i in range(300)}
    for index in range(10):
        last_generated[f"f{index}"] = NOW - timedelta(days=60)
    result = build(last_generated=last_generated)
    picked = {e.track.provider_track_id for e in result.entries}
    assert len(picked & {f"f{i}" for i in range(10)}) >= 8


def test_relaxation_is_recorded():
    tight = config_for(
        repetition={
            "same_artist_gap_tracks": 500,
            "same_album_gap_tracks": 500,
            "same_cluster_gap_tracks": 500,
        }
    )
    result = build(config=tight)
    assert result.relaxation_counts
    assert any(entry.relaxation for entry in result.entries)


def test_stops_early_when_candidates_run_out():
    result = build(config=config_for(hours=100), pools=pools(20, 20))
    assert result.stopped_early
    assert result.stop_reason == "no playable candidates left"
    assert len(result.entries) == 40


def test_missing_duration_uses_the_fallback():
    familiar = [
        make_track(f"f{i}", duration=None, artist=f"a{i}", album=f"al{i}") for i in range(60)
    ]
    config = config_for(hours=1, selection={"fallback_track_duration_seconds": 300})
    result = build(config=config, pools=PoolSet(familiar=familiar, discovery=[]))
    assert result.total_duration_seconds == 300 * len(result.entries)


def test_max_playlist_tracks_is_honoured():
    config = config_for(hours=100, validation={"max_playlist_tracks": 25})
    result = build(config=config)
    assert len(result.entries) == 25
    assert "max_playlist_tracks" in (result.stop_reason or "")


def test_entries_are_positioned_and_typed():
    result = build()
    assert [entry.position for entry in result.entries] == list(range(len(result.entries)))
    assert all(
        entry.source_type in {SourceType.FAMILIAR, SourceType.DISCOVERY} for entry in result.entries
    )
    assert all(entry.cluster_id for entry in result.entries)


def test_unavailable_tracks_are_never_selected():
    familiar = [make_track(f"f{i}", artist=f"a{i}", album=f"al{i}") for i in range(30)]
    familiar += [
        make_track(f"u{i}", available=False, artist=f"b{i}", album=f"bl{i}") for i in range(30)
    ]
    result = build(config=config_for(hours=1), pools=PoolSet(familiar=familiar, discovery=[]))
    assert all(entry.track.available for entry in result.entries)


def test_candidate_pool_sampling_is_bounded():
    pool = CandidatePool(SourceType.FAMILIAR, [make_track(str(i)) for i in range(100)])
    sampled = pool.sample(random.Random(1), 10)
    assert len(sampled) == 10
    pool.take(sampled[0])
    assert len(pool) == 99
    assert sampled[0].provider_track_id not in {t.provider_track_id for t in pool.remaining()}


def test_sampling_cap_does_not_break_long_playlists():
    config = config_for(hours=6, selection={"max_candidates_per_step": 10})
    result = build(config=config)
    assert result.total_duration_seconds >= 6 * 3600
