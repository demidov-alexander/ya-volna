from __future__ import annotations

from datetime import timedelta

import pytest

from tests.conftest import NOW, make_track
from yavolna.config import AppConfig
from yavolna.library.models import SourceType
from yavolna.mixing.constraints import (
    Constraints,
    Relaxation,
    SchedulerState,
    days_between,
    is_eligible,
    passes_hard_filters,
)

CONSTRAINTS = Constraints(
    same_artist_gap=5,
    same_album_gap=8,
    same_cluster_gap=2,
    track_cooldown_days=10,
    favorite_track_cooldown_days=4,
)


def state_with(tracks) -> SchedulerState:
    state = SchedulerState()
    for track in tracks:
        state.observe(track, SourceType.FAMILIAR, track.duration_seconds or 200)
    return state


def test_constraints_from_config():
    constraints = Constraints.from_config(AppConfig())
    assert constraints.same_artist_gap == 20
    assert constraints.same_album_gap == 40
    assert constraints.same_cluster_gap == 3


def test_cooldown_is_shorter_for_liked_tracks():
    assert CONSTRAINTS.cooldown_days_for(make_track("1", liked=True)) == 4
    assert CONSTRAINTS.cooldown_days_for(make_track("2", liked=False)) == 10


def test_hard_filters_block_duplicates_and_unavailable():
    state = state_with([make_track("1")])
    assert not passes_hard_filters(make_track("1"), state)
    assert not passes_hard_filters(make_track("2", available=False), state)
    assert passes_hard_filters(make_track("2"), state)


def test_artist_gap_blocks_then_allows():
    state = state_with([make_track("1", artist="a1", cluster="c1")])
    candidate = make_track("2", artist="a1", cluster="c2", album="al2")
    assert not is_eligible(candidate, state, CONSTRAINTS, Relaxation.NONE)

    for index in range(4):
        state.observe(
            make_track(f"f{index}", artist="other", cluster="c9"), SourceType.FAMILIAR, 200
        )
    assert is_eligible(candidate, state, CONSTRAINTS, Relaxation.NONE)


def test_album_and_cluster_gaps_are_independent():
    state = state_with([make_track("1", artist="a1", album="al1", cluster="c1")])
    same_album = make_track("2", artist="a2", album="al1", cluster="c2")
    same_cluster = make_track("3", artist="a3", album="al2", cluster="c1")
    assert not is_eligible(same_album, state, CONSTRAINTS, Relaxation.NONE)
    assert not is_eligible(same_cluster, state, CONSTRAINTS, Relaxation.NONE)


@pytest.mark.parametrize(
    ("level", "expected"),
    [
        (Relaxation.NONE, False),
        (Relaxation.CLUSTER, True),
    ],
)
def test_relaxing_the_cluster_gap_first(level, expected):
    state = state_with([make_track("1", artist="a1", album="al1", cluster="c1")])
    candidate = make_track("2", artist="a2", album="al2", cluster="c1")
    assert is_eligible(candidate, state, CONSTRAINTS, level) is expected


def test_relaxation_ladder_is_ordered():
    state = state_with([make_track("1", artist="a1", album="al1", cluster="c1")])
    candidate = make_track("2", artist="a1", album="al1", cluster="c1")
    assert not is_eligible(candidate, state, CONSTRAINTS, Relaxation.CLUSTER)
    assert not is_eligible(candidate, state, CONSTRAINTS, Relaxation.ALBUM)
    assert is_eligible(candidate, state, CONSTRAINTS, Relaxation.ARTIST)


def test_cooldown_blocks_recent_tracks_until_relaxed():
    state = SchedulerState()
    candidate = make_track("1", liked=False)
    last_generated = {"1": NOW - timedelta(days=3)}
    assert not is_eligible(
        candidate, state, CONSTRAINTS, Relaxation.ARTIST, last_generated=last_generated, now=NOW
    )
    assert is_eligible(
        candidate, state, CONSTRAINTS, Relaxation.COOLDOWN, last_generated=last_generated, now=NOW
    )


def test_liked_tracks_leave_cooldown_sooner():
    state = SchedulerState()
    last_generated = {"1": NOW - timedelta(days=5), "2": NOW - timedelta(days=5)}
    liked = make_track("1", liked=True)
    other = make_track("2", liked=False)
    assert is_eligible(
        liked, state, CONSTRAINTS, Relaxation.NONE, last_generated=last_generated, now=NOW
    )
    assert not is_eligible(
        other, state, CONSTRAINTS, Relaxation.NONE, last_generated=last_generated, now=NOW
    )


def test_zero_gap_disables_the_constraint():
    constraints = Constraints(0, 0, 0, 0, 0)
    state = state_with([make_track("1", artist="a1", album="al1", cluster="c1")])
    candidate = make_track("2", artist="a1", album="al1", cluster="c1")
    assert is_eligible(candidate, state, constraints, Relaxation.NONE)


def test_state_tracks_counts_and_duration():
    state = SchedulerState()
    state.observe(make_track("1", cluster="c1"), SourceType.FAMILIAR, 200)
    state.observe(make_track("2", cluster="c2"), SourceType.DISCOVERY, 300)
    assert (state.familiar_count, state.discovery_count) == (1, 1)
    assert state.total_duration == 500
    assert state.position == 2
    assert state.cluster_counts == {"c1": 1, "c2": 1}


def test_days_between_is_never_negative():
    assert days_between(NOW + timedelta(days=2), NOW) == 0.0
    assert days_between(NOW - timedelta(days=2), NOW) == pytest.approx(2.0)
