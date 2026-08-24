from __future__ import annotations

from datetime import timedelta

from tests.conftest import NOW, make_track
from yavolna.library.models import SourceType
from yavolna.mixing.constraints import Constraints, SchedulerState
from yavolna.mixing.scorer import (
    ScoreWeights,
    ScoringContext,
    cluster_targets,
    score_track,
)

CONSTRAINTS = Constraints(20, 40, 3, 10, 4)


def context(**kwargs) -> ScoringContext:
    base = {
        "constraints": CONSTRAINTS,
        "weights": ScoreWeights(),
        "cluster_targets": {"c1": 0.5, "c2": 0.5},
        "now": NOW,
    }
    base.update(kwargs)
    return ScoringContext(**base)


def test_just_played_artist_scores_lower_than_a_fresh_one():
    state = SchedulerState()
    state.observe(make_track("1", artist="a1", cluster="c1"), SourceType.FAMILIAR, 200)

    repeat = make_track("2", artist="a1", album="al9", cluster="c2")
    fresh = make_track("3", artist="a2", album="al9", cluster="c2")
    ctx = context()
    assert (
        score_track(repeat, SourceType.FAMILIAR, state, ctx).total
        < score_track(fresh, SourceType.FAMILIAR, state, ctx).total
    )


def test_underrepresented_cluster_gets_a_bonus():
    state = SchedulerState()
    for index in range(10):
        state.observe(make_track(f"f{index}", cluster="c1"), SourceType.FAMILIAR, 200)

    starved = make_track("x", artist="a9", album="al9", cluster="c2")
    saturated = make_track("y", artist="a8", album="al8", cluster="c1")
    ctx = context()
    breakdown_starved = score_track(starved, SourceType.FAMILIAR, state, ctx)
    breakdown_saturated = score_track(saturated, SourceType.FAMILIAR, state, ctx)
    assert breakdown_starved.components["cluster_balance"] > 0
    assert breakdown_saturated.components["cluster_balance"] < 0
    assert breakdown_starved.total > breakdown_saturated.total


def test_recently_generated_track_is_penalised():
    state = SchedulerState()
    ctx = context(last_generated={"1": NOW - timedelta(days=1)})
    recent = make_track("1")
    never = make_track("2")
    assert (
        score_track(recent, SourceType.FAMILIAR, state, ctx).total
        < score_track(never, SourceType.FAMILIAR, state, ctx).total
    )


def test_cooldown_penalty_decays_to_zero():
    state = SchedulerState()
    fresh = context(last_generated={"1": NOW - timedelta(days=1)})
    old = context(last_generated={"1": NOW - timedelta(days=30)})
    track = make_track("1")
    assert score_track(track, SourceType.FAMILIAR, state, fresh).components["track_recency"] < 0
    assert score_track(track, SourceType.FAMILIAR, state, old).components["track_recency"] == 0


def test_frequently_generated_tracks_are_penalised():
    state = SchedulerState()
    ctx = context(generation_counts={"1": 20})
    assert (
        score_track(make_track("1"), SourceType.FAMILIAR, state, ctx).components["generation_count"]
        < 0
    )


def test_quota_need_favours_the_starved_source():
    state = SchedulerState()
    for index in range(10):
        state.observe(make_track(f"f{index}"), SourceType.FAMILIAR, 200)
    ctx = context(familiar_target_ratio=0.5)
    discovery = score_track(make_track("d"), SourceType.DISCOVERY, state, ctx)
    familiar = score_track(make_track("f"), SourceType.FAMILIAR, state, ctx)
    assert discovery.components["quota_need"] > familiar.components["quota_need"]


def test_exploratory_seed_groups_get_a_small_bonus():
    state = SchedulerState()
    ctx = context()
    explored = make_track("1", seed_group="underrepresented")
    plain = make_track("2", seed_group="cluster:rock")
    assert (
        score_track(explored, SourceType.DISCOVERY, state, ctx).components["exploratory"]
        > score_track(plain, SourceType.DISCOVERY, state, ctx).components["exploratory"]
    )


def test_exploratory_bonus_does_not_apply_to_familiar_tracks():
    state = SchedulerState()
    ctx = context()
    track = make_track("1", seed_group="underrepresented")
    assert score_track(track, SourceType.FAMILIAR, state, ctx).components["exploratory"] == 0


def test_cluster_targets_pull_towards_uniform_with_high_variety():
    sizes = {"big": 900, "small": 100}
    variety = cluster_targets(sizes, prefer_high_variety=True)
    literal = cluster_targets(sizes, prefer_high_variety=False)
    assert variety["small"] > literal["small"]
    assert sum(variety.values()) == 1.0


def test_cluster_targets_handle_an_empty_library():
    assert cluster_targets({}, prefer_high_variety=True) == {}


def test_weights_react_to_prefer_high_variety():
    assert (
        ScoreWeights.for_variety(True).cluster_balance
        > ScoreWeights.for_variety(False).cluster_balance
    )
