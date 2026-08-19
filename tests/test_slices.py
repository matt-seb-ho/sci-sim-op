"""Anchor / probe / held-out slice construction.

The predecessor ran each round on a different third of its pool, so no two
rounds were comparable. Fixing that needs one fixed anchor -- and choosing which
tasks belong in it is a real decision, because the obvious answer is wrong here.
"""

from __future__ import annotations

import pytest

from harness_evolve.evaluation.slices import (
    BOUNDARY, COVERAGE, FRESH, SlicePlan, TaskStat, build_slices, stats_from_rollouts,
)

POOL = [f"t{i}" for i in range(16)]
GROUPS = {t: ["poro", "frac", "thermal", "flow"][i % 4] for i, t in enumerate(POOL)}


def group_of(t: str) -> str:
    return GROUPS[t]


def stats(**overrides) -> dict[str, TaskStat]:
    """Default pool: mostly mid-range, with a few saturated and a few hopeless."""
    out = {}
    for t in POOL:
        out[t] = TaskStat(t, (0.55, 0.60, 0.50), GROUPS[t])
    for t, scores in overrides.items():
        out[t] = TaskStat(t, scores, GROUPS[t])
    return out


# ---------------------------------------------------------------------------
# what "in play" means
# ---------------------------------------------------------------------------

def test_intermittent_catastrophe_ranks_highest():
    """A task that sometimes fails catastrophically and sometimes does not is
    exactly the behaviour adapters are known to fix, so it is the single most
    informative task to score on."""
    tail = TaskStat("tail", (0.0, 0.9, 0.0))
    saturated = TaskStat("sat", (0.95, 0.96, 0.94))
    hopeless = TaskStat("dead", (0.0, 0.0, 0.0))
    mid = TaskStat("mid", (0.55, 0.60, 0.50))

    assert tail.in_play > mid.in_play
    assert tail.in_play > saturated.in_play
    assert tail.in_play > hopeless.in_play


def test_saturated_and_hopeless_are_both_near_zero():
    """For the same reason: nothing a candidate does will move either, so
    scoring on them spends budget to learn nothing."""
    saturated = TaskStat("sat", (0.98, 0.99, 0.99))
    hopeless = TaskStat("dead", (0.0, 0.0, 0.0))
    assert saturated.in_play < 0.3
    assert hopeless.in_play < 0.3


def test_zero_rate_is_measured():
    assert TaskStat("t", (0.0, 0.9, 0.0)).zero_rate == pytest.approx(2 / 3)
    assert TaskStat("t", (0.9, 0.9)).zero_rate == 0.0


# ---------------------------------------------------------------------------
# construction
# ---------------------------------------------------------------------------

def test_anchor_is_weighted_toward_tasks_in_play():
    s = stats(t0=(0.0, 0.9, 0.0), t1=(0.0, 0.85, 0.0), t2=(0.0, 0.8, 0.9))
    plan = build_slices(POOL, stats=s, anchor_size=8, group_of=group_of)
    boundary = [t for t in plan.anchor if plan.roles[t] == BOUNDARY]
    assert {"t0", "t1", "t2"} <= set(boundary), (
        "the tail tasks must be in the anchor; the effect lives there"
    )


def test_every_anchor_task_carries_a_reason():
    plan = build_slices(POOL, stats=stats(), anchor_size=6, group_of=group_of)
    for t in plan.anchor:
        assert plan.rationale[t], f"{t} has no stated reason for inclusion"
        assert plan.roles[t] in (COVERAGE, BOUNDARY, FRESH)


def test_coverage_spreads_across_groups():
    plan = build_slices(POOL, stats=stats(), anchor_size=8, boundary_fraction=0.0,
                        group_of=group_of)
    covered = {group_of(t) for t in plan.anchor}
    assert len(covered) >= 3


def test_slices_are_disjoint():
    plan = build_slices(POOL, stats=stats(), anchor_size=6, probe_size=4,
                        held_out=["t14", "t15"], group_of=group_of)
    assert not (set(plan.anchor) & set(plan.probe))
    assert not (set(plan.anchor) & set(plan.held_out))
    assert not (set(plan.probe) & set(plan.held_out))


def test_overlapping_slices_raise():
    plan = SlicePlan(anchor=("a", "b"), probe=("b",))
    with pytest.raises(ValueError, match="overlap"):
        plan.validate()


def test_a_fresh_task_is_held_back():
    plan = build_slices(POOL, stats=stats(), anchor_size=8, group_of=group_of)
    assert any(plan.roles[t] == FRESH for t in plan.anchor)


# ---------------------------------------------------------------------------
# honest degradation
# ---------------------------------------------------------------------------

def test_cold_start_says_it_cannot_identify_the_boundary():
    """Guessing which tasks are in play, with no data, would be worse than
    saying so: the anchor would look principled and be arbitrary."""
    plan = build_slices(POOL, anchor_size=6, group_of=group_of)
    assert plan.cold_start
    assert plan.anchor
    assert all(plan.roles[t] in (COVERAGE, FRESH) for t in plan.anchor)
    assert any("coverage-only" in w for w in plan.warnings)


def test_missing_group_coverage_is_reported():
    """Weighting toward tasks in play costs coverage. Which groups it cost is a
    decision the reader should see, not one buried in a ranking."""
    s = stats(t0=(0.0, 0.9, 0.0), t4=(0.0, 0.9, 0.0), t8=(0.0, 0.9, 0.0),
              t12=(0.0, 0.9, 0.0))
    plan = build_slices(POOL, stats=s, anchor_size=4, boundary_fraction=1.0,
                        group_of=group_of)
    # All four boundary picks are group 'poro'; the rest are uncovered.
    assert any("does not cover group" in w for w in plan.warnings)


def test_absent_probe_is_reported():
    plan = build_slices(["a", "b"], stats=None, anchor_size=2, probe_size=2)
    assert any("no probe slice" in w for w in plan.warnings)


def test_empty_pool_after_held_out():
    plan = build_slices(["a"], held_out=["a"])
    assert plan.anchor == ()
    assert any("no tasks left" in w for w in plan.warnings)


def test_stats_are_derivable_from_any_prior_run():
    from harness_evolve.types import Rollout, Score

    rollouts = [
        Rollout("t0", "c", 1, Score("t0", 0.0)),
        Rollout("t0", "c", 2, Score("t0", 0.9)),
        Rollout("t1", "c", 1, Score("t1", 0.8)),
    ]
    s = stats_from_rollouts(rollouts)
    assert s["t0"].zero_rate == 0.5
    assert s["t0"].in_play > s["t1"].in_play


def test_plan_renders_the_reasoning():
    plan = build_slices(POOL, stats=stats(t0=(0.0, 0.9, 0.0)), anchor_size=5,
                        held_out=["t15"], group_of=group_of)
    text = plan.render()
    assert "anchor:" in text
    assert "held-out (touched once, at the end)" in text
    assert "[boundary]" in text or "[coverage]" in text
