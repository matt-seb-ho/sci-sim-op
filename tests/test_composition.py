"""The harness x test-time-scaling factorial.

arXiv:2607.12227 compares harness evolution *against* test-time scaling as
alternatives competing for one budget. That is a fair question, but not the one
a deployment faces: nobody runs a deliberately worse harness in order to afford
more samples. The two compose, so what decides whether harness work is worth
doing is whether the harness still helps once *both* arms get the same inference
budget.

These tests exist mainly to establish that the instrument discriminates. A grid
that reported "the harness helps" under every world would be decoration.
"""

from __future__ import annotations

import hashlib
import random
import struct

import pytest

from harness_evolve.evaluation.composition import (
    CompositionGrid, CompositionResult, validator_selector,
)
from harness_evolve.types import Cost, Rollout, Score

TASKS = [f"t{i}" for i in range(8)]
SYSTEMATIC = {"t0", "t1"}


def _seed(*parts: object) -> int:
    """A stable seed. Never ``hash()``: it is salted per process, so fixtures
    built on it produce different worlds on different runs and a verdict test
    becomes a coin flip."""
    digest = hashlib.blake2b(
        "|".join(str(p) for p in parts).encode(), digest_size=8
    ).digest()
    return struct.unpack("<Q", digest)[0]


def systematic_world(harness: str, task: str, rep: int, i: int) -> Rollout:
    """Two tasks the seed fails on *every* draw; the rest are coin flips.

    A task the agent fails identically every time is failing systematically —
    it does not know the interface — and resampling a confident, uniform error
    yields k copies of it.
    """
    rng = random.Random(_seed(harness, task, rep, i))
    if task in SYSTEMATIC:
        value = 0.0 if harness == "seed" else 0.75
    else:
        value = 0.85 if rng.random() < 0.5 else 0.0
    return Rollout(task=task, candidate_id=harness, seed=rep,
                   score=Score(task, value), cost=Cost())


def stochastic_world(harness: str, task: str, rep: int, i: int) -> Rollout:
    """The harness only raises the per-sample success probability.

    Resampling buys the same thing, so the gain should be absorbed as k grows.
    """
    rng = random.Random(_seed(harness, task, rep, i))
    p = 0.35 if harness == "seed" else 0.60
    return Rollout(task=task, candidate_id=harness, seed=rep,
                   score=Score(task, 0.85 if rng.random() < p else 0.0), cost=Cost())


def no_gain_world(harness: str, task: str, rep: int, i: int) -> Rollout:
    rng = random.Random(_seed(task, rep, i))
    return Rollout(task=task, candidate_id=harness, seed=rep,
                   score=Score(task, 0.85 if rng.random() < 0.5 else 0.0), cost=Cost())


# ---------------------------------------------------------------------------
# the instrument must discriminate
# ---------------------------------------------------------------------------

def test_a_gain_on_systematic_failures_persists_under_scaling():
    """The claim harness work needs: repairing errors resampling cannot reach."""
    r = CompositionGrid(ks=(1, 3, 5)).run(
        draw=systematic_world, tasks=TASKS, replicates=(1, 2, 3)
    )
    assert r.classify() == "persists"
    assert r.retention >= 0.6
    assert r.gain_at(5) >= r.gain_at(1) * 0.6


def test_a_gain_on_stochastic_failures_is_absorbed_by_scaling():
    """The clean null, and a better one than 'evolution lost a comparison'
    because it says why."""
    r = CompositionGrid(ks=(1, 3, 7)).run(
        draw=stochastic_world, tasks=TASKS, replicates=(1, 2, 3)
    )
    assert r.classify() in ("decays", "vanishes")
    assert r.retention < 0.6
    assert r.gain_at(7) < r.gain_at(1)


def test_no_gain_at_k1_is_undetermined_not_a_trend():
    """With nothing to retain, fitting a trend through noise would manufacture
    a conclusion. The matched comparison at k=1 has to be won first."""
    r = CompositionGrid(ks=(1, 3)).run(
        draw=no_gain_world, tasks=TASKS, replicates=(1, 2)
    )
    assert r.classify() == "undetermined"
    assert "matched comparison at k=1" in r.render()


# ---------------------------------------------------------------------------
# error-class attribution
# ---------------------------------------------------------------------------

def test_systematic_failures_are_identified_by_failing_every_draw():
    r = CompositionGrid(ks=(1, 5)).run(
        draw=systematic_world, tasks=TASKS, replicates=(1, 2, 3)
    )
    assert set(r.systematic_tasks(5)) == SYSTEMATIC


def test_rescuing_a_systematically_failing_task_is_reported():
    """The cleanest evidence available: the seed failed all k attempts, the
    evolved arm did not."""
    r = CompositionGrid(ks=(1, 5)).run(
        draw=systematic_world, tasks=TASKS, replicates=(1, 2, 3)
    )
    assert set(r.systematic_rescues(5)) == SYSTEMATIC
    assert "cleanest available evidence" in r.render()


def test_a_purely_stochastic_world_has_no_systematic_failures_at_high_k():
    r = CompositionGrid(ks=(1, 7)).run(
        draw=stochastic_world, tasks=TASKS, replicates=(1, 2, 3)
    )
    assert len(r.systematic_tasks(7)) < len(r.systematic_tasks(1))


# ---------------------------------------------------------------------------
# selectors
# ---------------------------------------------------------------------------

def test_the_validator_selector_is_weaker_than_the_oracle():
    """In a domain where scoring needs the ground truth you are producing, the
    gap between an oracle selector and a realizable one is not an implementation
    shortcoming — it is the problem, and it is why scaling is weaker here than
    on a benchmark with unit tests."""
    oracle = CompositionGrid(ks=(1, 5)).run(
        draw=stochastic_world, tasks=TASKS, replicates=(1, 2, 3)
    )
    realizable = CompositionGrid(ks=(1, 5)).run(
        draw=stochastic_world, tasks=TASKS, replicates=(1, 2, 3),
        select=validator_selector,
    )
    assert oracle.cells[("seed", 5)].mean >= realizable.cells[("seed", 5)].mean


def test_validator_selector_prefers_a_draw_that_validated():
    good = Rollout("t", "c", 1, Score("t", 0.4), validator_events=[])
    bad = Rollout("t", "c", 1, Score("t", 0.9),
                  validator_events=[{"decision": "block"}])
    assert validator_selector([bad, good]) is good


def test_validator_selector_falls_back_rather_than_raising():
    """Every draw failing validation is an ordinary outcome, not an error."""
    draws = [Rollout("t", "c", 1, Score("t", 0.0, "failed"),
                     validator_events=[{"decision": "block"}]) for _ in range(3)]
    assert validator_selector(draws) is draws[0]


# ---------------------------------------------------------------------------
# guards
# ---------------------------------------------------------------------------

def test_budget_is_compared_within_a_k_not_across_it():
    """Spend must match between harnesses at each k; comparing across k is the
    entire point of the grid."""
    r = CompositionGrid(ks=(1, 3, 5)).run(
        draw=systematic_world, tasks=TASKS, replicates=(1, 2)
    )
    assert r.budget_matched()
    assert r.cells[("seed", 5)].rollouts > r.cells[("seed", 1)].rollouts


def test_unmatched_spend_is_flagged_in_the_report():
    r = CompositionResult(ks=(1,), cells={})
    from harness_evolve.evaluation.composition import Cell
    from harness_evolve.evaluation.stats import ArmScores

    r.cells[("seed", 1)] = Cell("seed", 1, ArmScores("s", {"t": (0.5,)}), rollouts=10)
    r.cells[("evolved", 1)] = Cell("evolved", 1, ArmScores("e", {"t": (0.9,)}),
                                   rollouts=40)
    assert not r.budget_matched()
    assert "measures budget rather than harness" in r.render()


def test_zero_rate_is_reported_per_cell():
    """Under failures-as-zero the zero rate is the reliability claim, and the
    grid is where it should be visible falling as either lever is pulled."""
    r = CompositionGrid(ks=(1, 5)).run(
        draw=systematic_world, tasks=TASKS, replicates=(1, 2, 3)
    )
    assert r.cells[("evolved", 5)].zero_rate < r.cells[("seed", 1)].zero_rate
    assert "zero-rate" in r.render()


def test_thresholds_are_stated_rather_than_hidden():
    """A reader should be able to disagree with a convention without having to
    reverse-engineer it."""
    # Same data, different convention, different verdict — which is the point:
    # the thresholds do visible work, and a reader who sets the bar elsewhere
    # gets a different answer from identical numbers rather than having to
    # reverse-engineer why ours came out as it did.
    r = CompositionGrid(ks=(1, 3, 5)).run(
        draw=systematic_world, tasks=TASKS, replicates=(1, 2, 3)
    )
    assert r.classify() == "persists"
    demanding = r.retention + 0.5
    assert r.classify(persist_floor=demanding) != "persists"
