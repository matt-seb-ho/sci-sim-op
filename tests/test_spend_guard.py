"""The spend ceiling: polled from the provider, not hardcoded.

(`tests/test_budget.py` is a different thing entirely -- it tests
`evaluation.budget`, the compute-matching planner. This file tests
`harness_evolve.budget`, the money.)

The failure this guards against is not "we spent too much". It is "we believed
we had a cap and did not" -- the ledger the campaign already had could only see
proposer calls, while essentially all of the money is spent by the coding agent
inside the container through its own credentials.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from harness_evolve.spend import (
    AUTHORIZED_USD,
    BASELINE_USAGE,
    AccountUsage,
    BudgetExhausted,
    BudgetGuard,
    BudgetGuardedRunner,
)
from harness_evolve.core.candidate import Candidate
from harness_evolve.core.manifest import ComponentSpec, Manifest
from harness_evolve.runners.base import RolloutRunner
from harness_evolve.types import Cost, Rollout, Score


def usage(u: float, limit: float | None = 10.0) -> AccountUsage:
    return AccountUsage(
        usage=u,
        limit=limit,
        limit_remaining=(None if limit is None else limit - u),
        ts=time.time(),
    )


def make_candidate() -> Candidate:
    return Candidate(
        manifest=Manifest(
            components={"primer": ComponentSpec("primer", "prose", path="P.md")}
        ),
        files={"P.md": "seed"},
    )


class CountingRunner(RolloutRunner):
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def run(self, candidate, task, seed=1):
        self.calls.append((task, seed))
        return Rollout(
            task=task, candidate_id=candidate.cid, seed=seed,
            score=Score(task=task, value=0.5), cost=Cost(),
        )


def guard(readings, **kw):
    it = iter(readings)
    last = {}

    def reader():
        try:
            last["v"] = next(it)
        except StopIteration:
            pass
        return last["v"]

    return BudgetGuard(reader=reader, min_interval_s=0.0, **kw)


# -- the ceiling arithmetic ------------------------------------------------


def test_the_ceiling_is_the_key_cap_not_the_authorization_when_the_cap_is_lower():
    # 2026-09-02 as measured: limit 10, baseline 1.271 -> 8.729 headroom, less
    # the reserve. The $20 authorization is not reachable through this key.
    g = guard([usage(BASELINE_USAGE)])
    g.poll()
    assert g.ceiling() == pytest.approx(10.0 - BASELINE_USAGE)
    assert g.ceiling() < AUTHORIZED_USD


def test_raising_the_key_cap_mid_run_raises_the_ceiling_to_the_authorization():
    g = guard([usage(BASELINE_USAGE), usage(5.0, limit=100.0)])
    g.poll()
    assert g.ceiling() == pytest.approx(8.728929, abs=1e-5)
    g.poll()
    assert g.ceiling() == AUTHORIZED_USD
    assert not g.tripped


def test_a_cap_change_is_announced_so_it_can_be_logged_as_a_decision():
    seen: list[tuple] = []
    g = guard([usage(BASELINE_USAGE), usage(2.0, limit=30.0)],
              on_limit_change=lambda before, after: seen.append((before, after)))
    g.poll()
    g.poll()
    assert seen == [(10.0, 30.0)]


def test_the_ceiling_does_not_shrink_as_we_spend():
    # The trap in the naive form. `limit_remaining` falls as `usage` rises, so
    # testing `spent >= min(20, limit_remaining)` against a *live* reading halts
    # at half the allowance. Pinned because both forms agree at t=0, which is
    # exactly what makes the wrong one easy to ship.
    g = guard([usage(BASELINE_USAGE), usage(5.0), usage(5.6355)])
    g.poll()
    ceiling = g.ceiling()
    g.poll()
    assert g.ceiling() == pytest.approx(ceiling)
    naive_halt = g.poll()
    assert naive_halt.limit_remaining == pytest.approx(naive_halt.spent(), abs=1e-3)
    assert not g.tripped, "halted at half the allowance -- the live-reading trap"


# -- tripping ---------------------------------------------------------------


def test_it_trips_when_additional_spend_reaches_the_ceiling():
    g = guard([usage(BASELINE_USAGE), usage(10.0)])
    g.check(force=True)
    with pytest.raises(BudgetExhausted, match="reached the ceiling"):
        g.check(force=True)
    assert g.tripped


def test_it_trips_when_one_more_batch_would_not_fit():
    g = guard([usage(9.0)], batch_cost_usd=2.0)
    with pytest.raises(BudgetExhausted, match="below the cost of one more batch"):
        g.check(force=True)


def test_a_trip_is_permanent_and_does_not_need_another_poll():
    g = guard([usage(10.0)])
    with pytest.raises(BudgetExhausted):
        g.check(force=True)
    with pytest.raises(BudgetExhausted):
        g.check()  # not due; must still refuse


def test_it_never_says_switch_model_is_an_option():
    g = guard([usage(10.0)])
    with pytest.raises(BudgetExhausted) as exc:
        g.check(force=True)
    assert "Do NOT switch to a different model" in str(exc.value)


def test_an_unreadable_counter_stops_the_run_rather_than_being_assumed_fine():
    def boom():
        raise BudgetExhausted("OPENROUTER_API_KEY is not set")

    g = BudgetGuard(reader=boom, min_interval_s=0.0)
    with pytest.raises(BudgetExhausted):
        g.check(force=True)


# -- logging ----------------------------------------------------------------


def test_every_reading_is_logged_with_what_it_was_judged_against(tmp_path: Path):
    ledger = tmp_path / "provider_calls.jsonl"
    g = guard([usage(BASELINE_USAGE), usage(3.0)], ledger_path=ledger)
    g.poll()
    g.poll()
    rows = [json.loads(l) for l in ledger.read_text().splitlines()]
    assert len(rows) == 2
    assert rows[1]["kind"] == "account_usage"
    assert rows[1]["usage"] == 3.0
    assert rows[1]["spent_this_campaign"] == pytest.approx(3.0 - BASELINE_USAGE)
    assert rows[1]["ceiling_usd"] == pytest.approx(8.728929, abs=1e-5)


# -- the runner wrapper -----------------------------------------------------


def test_the_guard_stops_rollouts_from_starting():
    inner = CountingRunner()
    g = guard([usage(BASELINE_USAGE), usage(10.0)])
    runner = BudgetGuardedRunner(inner, g)
    c = make_candidate()

    assert runner.run(c, "t0", 1).score.value == 0.5
    with pytest.raises(BudgetExhausted):
        runner.run(c, "t1", 1)
    assert inner.calls == [("t0", 1)], "a rollout started after the ceiling"


def test_a_replayed_rollout_is_not_gated(tmp_path: Path):
    # The guard sits *inside* recording, so resume and offline re-analysis keep
    # working when the money runs out -- which is exactly when they matter.
    from harness_evolve.runners.recording import RecordingRunner

    corpus = tmp_path / "rollouts.jsonl"
    c = make_candidate()
    inner = CountingRunner()
    g = guard([usage(BASELINE_USAGE)])
    RecordingRunner(
        BudgetGuardedRunner(inner, g), corpus, model="m"
    ).run(c, "t0", 1)

    g2 = guard([usage(10.0)])
    replayed = RecordingRunner(
        BudgetGuardedRunner(CountingRunner(), g2), corpus, model="m"
    )
    assert replayed.run(c, "t0", 1).score.value == 0.5
    assert replayed.stats.replayed == 1
