"""Tests for the evaluation protocol.

Fixtures are inline and synthetic on purpose: this suite must run on a laptop
with no data volume, and the shapes that matter here (a tail-driven effect, an
n too small to license a CI) are easier to construct than to find.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pytest

from harness_evolve.core.candidate import Candidate
from harness_evolve.core.manifest import ComponentSpec, Manifest, StopPolicy
from harness_evolve.evaluation import baselines as bl
from harness_evolve.evaluation import stats as st
from harness_evolve.evaluation.protocol import EvaluationProtocol, SliceViolation
from harness_evolve.evaluation.report import (
    ArmConfig,
    EvaluationReport,
    VerdictCriterion,
)
from harness_evolve.runners.base import RolloutRunner
from harness_evolve.types import Cost, Rollout, Score

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

TASKS = tuple(f"task{i:02d}" for i in range(10))
SEEDS = (1, 2, 3)


def arm(label: str, per_task: dict[str, tuple[float, ...]]) -> st.ArmScores:
    return st.ArmScores(label=label, per_task=per_task)


def tail_driven_fixture() -> tuple[st.ArmScores, st.ArmScores]:
    """Two catastrophic-failure rescues, eight tasks unchanged.

    Modelled on the measurement this protocol exists for: the aggregate gain
    came from 0.355 -> 0.761 and 0.541 -> 0.825, everything else was inside
    run-to-run noise, and the low-variance arm's spread collapsed because its
    zero-score runs disappeared.
    """
    base: dict[str, tuple[float, ...]] = {}
    treat: dict[str, tuple[float, ...]] = {}
    for i, t in enumerate(TASKS[:8]):
        jitter = 0.002 * ((i % 3) - 1)
        base[t] = (0.80 + jitter, 0.80, 0.80 - jitter)
        treat[t] = (0.80, 0.80 + jitter, 0.80)
    base[TASKS[8]] = (0.355, 0.0, 0.42)
    treat[TASKS[8]] = (0.761, 0.758, 0.765)
    base[TASKS[9]] = (0.541, 0.0, 0.52)
    treat[TASKS[9]] = (0.825, 0.820, 0.828)
    return arm("bare baseline", base), arm("adapter", treat)


def broad_gain_fixture(mean_delta: float) -> tuple[st.ArmScores, st.ArmScores]:
    """Same mean delta as the tail fixture, spread evenly over every task.

    The control for the central claim of this module: a mean cannot tell these
    two situations apart, and they support completely different conclusions.
    """
    base = {t: (0.60, 0.60, 0.60) for t in TASKS}
    treat = {t: (0.60 + mean_delta,) * 3 for t in TASKS}
    return arm("bare baseline", base), arm("adapter", treat)


def make_candidate(retries: int = 2) -> Candidate:
    manifest = Manifest(
        components={
            "primer": ComponentSpec(
                name="primer", kind="prose", path="PRIMER.md", budget_tokens=1000
            ),
            "stop_policy": ComponentSpec(name="stop_policy", kind="config"),
        },
        stop_policy=StopPolicy(retries=retries),
    )
    return Candidate(manifest=manifest, files={"PRIMER.md": "grounding primer"})


@dataclass
class ScriptedRunner(RolloutRunner):
    """Deterministic runner over a score table; records every call."""

    table: dict[tuple[str, int], float] = field(default_factory=dict)
    default: float = 0.5
    events: dict[tuple[str, int], list[dict[str, object]]] = field(default_factory=dict)
    retry_gain: float = 0.0
    calls: list[tuple[str, int, int]] = field(default_factory=list)

    def run(self, candidate, task, seed: int = 1) -> Rollout:
        retries = candidate.manifest.stop_policy.retries
        self.calls.append((task, seed, retries))
        value = self.table.get((task, seed), self.default)
        value = min(1.0, value + self.retry_gain * max(0, retries - 2))
        return Rollout(
            task=task,
            candidate_id=candidate.cid,
            seed=seed,
            score=Score(task=task, value=value),
            cost=Cost(tool_calls=10.0, wall_seconds=60.0, usd=0.25),
            validator_events=list(self.events.get((task, seed), [])),
        )


# ---------------------------------------------------------------------------
# bootstrap
# ---------------------------------------------------------------------------


def test_bootstrap_ci_on_constant_deltas_is_degenerate():
    # Every resample of a constant sample has the same mean, so the only
    # correct interval is the point itself.
    res = st.paired_bootstrap_ci([0.1] * 12, resamples=500, seed=1)
    assert res.reportable
    assert res.interval is not None
    assert res.interval.low == pytest.approx(0.1)
    assert res.interval.high == pytest.approx(0.1)
    assert res.point == pytest.approx(0.1)


def test_bootstrap_ci_matches_normal_theory_at_large_n():
    deltas = [(i - 99.5) / 200.0 for i in range(200)]
    res = st.paired_bootstrap_ci(deltas, resamples=4000, seed=7)
    assert res.interval is not None
    mean = sum(deltas) / len(deltas)
    sd = math.sqrt(sum((d - mean) ** 2 for d in deltas) / (len(deltas) - 1))
    sem = sd / math.sqrt(len(deltas))
    assert res.interval.low == pytest.approx(mean - 1.96 * sem, abs=0.01)
    assert res.interval.high == pytest.approx(mean + 1.96 * sem, abs=0.01)


def test_bootstrap_is_reproducible_under_a_seed():
    deltas = [0.0, 0.2, -0.1, 0.4, 0.05, 0.3, -0.2, 0.1]
    a = st.paired_bootstrap_ci(deltas, resamples=1000, seed=42)
    b = st.paired_bootstrap_ci(deltas, resamples=1000, seed=42)
    c = st.paired_bootstrap_ci(deltas, resamples=1000, seed=43)
    assert a.interval == b.interval
    assert a.interval != c.interval


# ---------------------------------------------------------------------------
# guard rails
# ---------------------------------------------------------------------------


def test_small_n_guard_rail_refuses_instead_of_emitting_an_interval():
    res = st.paired_bootstrap_ci([0.3, 0.25, 0.28], resamples=1000, seed=1)
    assert not res.reportable
    assert res.interval is None
    assert res.refusal is not None and "below the floor" in res.refusal
    assert "no CI" in res.render()
    # A refusal must not be mistakable for "no effect".
    assert res.point == pytest.approx(0.2766666, abs=1e-5)
    assert not res.excludes_zero


def test_few_movers_guard_rail_refuses_even_when_n_is_adequate():
    deltas = [0.0] * 8 + [0.40, 0.28]
    res = st.paired_bootstrap_ci(deltas, resamples=1000, seed=1, noise_band=0.01)
    assert not res.reportable
    assert res.refusal is not None and "2 of 10 tasks moved" in res.refusal


# ---------------------------------------------------------------------------
# permutation
# ---------------------------------------------------------------------------


def test_paired_permutation_detects_a_constructed_uniform_effect():
    res = st.paired_permutation_test([0.2] * 10, noise_band=0.01)
    assert res.exact
    assert res.n_permutations == 2**10
    # Only the all-positive and all-negative sign assignments are as extreme.
    assert res.p_value == pytest.approx(2 / 1024)
    assert res.significant
    assert not res.underpowered


def test_paired_permutation_reports_its_own_power_ceiling():
    res = st.paired_permutation_test([0.3, 0.25, 0.28], noise_band=0.01)
    assert res.p_value == pytest.approx(2 / 8)
    assert res.min_achievable_p == pytest.approx(0.25)
    assert res.underpowered
    assert not res.significant


def test_permutation_with_no_movers_is_p_one():
    res = st.paired_permutation_test([0.0] * 6, noise_band=0.01)
    assert res.n_movers == 0
    assert res.p_value == 1.0
    assert res.min_achievable_p == 1.0
    assert res.underpowered


def test_permutation_falls_back_to_sampling_beyond_the_exact_limit():
    deltas = [0.1 * (1 if i % 2 else -1) + 0.05 for i in range(25)]
    res = st.paired_permutation_test(
        deltas, resamples=500, seed=3, exact_max_movers=20, noise_band=0.0
    )
    assert not res.exact
    assert res.n_permutations == 500
    assert 0.0 < res.p_value <= 1.0


# ---------------------------------------------------------------------------
# effect size
# ---------------------------------------------------------------------------


def test_rank_biserial_saturates_when_every_mover_agrees_in_sign():
    r_pos, n_pos = st.matched_pairs_rank_biserial([0.0, 0.4, 0.28], noise_band=0.01)
    r_neg, _ = st.matched_pairs_rank_biserial([0.0, -0.4, -0.28], noise_band=0.01)
    r_mixed, _ = st.matched_pairs_rank_biserial([0.3, -0.3], noise_band=0.01)
    assert (r_pos, n_pos) == (1.0, 2)
    assert r_neg == -1.0
    assert r_mixed == pytest.approx(0.0)


def test_headroom_capture_is_the_fraction_of_what_was_left():
    pairs = [
        st.PairedDelta("a", 0.5, 0.75),
        st.PairedDelta("b", 0.5, 0.75),
    ]
    # 0.5 of headroom gained out of 1.0 available.
    assert st.headroom_capture(pairs) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# tail statistics -- the mechanism
# ---------------------------------------------------------------------------


def test_tail_statistics_surface_the_mechanism_the_mean_hides():
    base, treat = tail_driven_fixture()
    tail = st.compare(base, treat)
    broad_base, broad_treat = broad_gain_fixture(tail.mean_delta)
    broad = st.compare(broad_base, broad_treat)

    # The two situations are indistinguishable in the mean ...
    assert broad.mean_delta == pytest.approx(tail.mean_delta, abs=1e-9)

    # ... and completely different in everything that matters.
    assert (len(tail.wlt.wins), len(tail.wlt.ties)) == (2, 8)
    assert len(broad.wlt.wins) == 10 and not broad.wlt.ties
    assert tail.rescues.rescued == (TASKS[8], TASKS[9])
    assert broad.rescues.rescued == ()
    assert tail.tail_baseline.zero_runs == 2
    assert tail.tail_treatment.zero_runs == 0
    assert tail.zero_rate_delta < 0
    assert broad.zero_rate_delta == 0.0
    # Variance collapse is the effect: the adapter arm's run-to-run spread is
    # an order of magnitude below the baseline's.
    assert tail.tail_treatment.pooled_seed_sd < tail.tail_baseline.pooled_seed_sd / 10

    # And the paired tests must not pretend to adjudicate two movers.
    assert not tail.bootstrap.reportable
    assert tail.permutation.underpowered
    assert not tail.conclusive


def test_rescue_ledger_uses_the_worst_seed_not_the_mean():
    base = arm("b", {"t": (0.0, 0.9, 0.9)})
    # Mean is well above the threshold, but one seed still falls off the cliff.
    treat = arm("t", {"t": (0.0, 0.95, 0.95)})
    ledger = st.rescue_ledger(base, treat, threshold=0.25)
    assert ledger.rescued == ()
    assert ledger.stayed_below == ("t",)
    mean_ledger = st.rescue_ledger(
        base, treat, threshold=0.25, agg=st.agg_mean, aggregator_name="mean"
    )
    assert mean_ledger.stayed_above == ("t",)


def test_regression_below_the_cliff_is_counted_as_a_loss():
    base = arm("b", {t: (0.8, 0.8, 0.8) for t in TASKS})
    treat_map = {t: (0.8, 0.8, 0.8) for t in TASKS}
    treat_map[TASKS[0]] = (0.0, 0.1, 0.05)
    ledger = st.rescue_ledger(base, arm("t", treat_map), threshold=0.25)
    assert ledger.lost == (TASKS[0],)
    assert ledger.net_rescues == -1


def test_zero_rate_intervals_stay_wide_at_the_boundary():
    perfect = arm("adapter", {t: (0.9, 0.9, 0.9) for t in TASKS})
    tail = st.tail_stats(perfect, resamples=500)
    assert tail.zero_rate == 0.0
    # Zero zeros in 30 clustered runs is not proof of a zero failure rate.
    assert tail.zero_rate_ci_naive.high > 0.05
    assert tail.zero_rate_ci.reportable


def test_noise_band_is_derived_from_across_seed_spread():
    base, treat = tail_driven_fixture()
    band, source = st.noise_band_from_seeds([base, treat])
    assert band >= st.MIN_NOISE_BAND
    assert "median across-seed SD" in source
    single = arm("one seed", {t: (0.5,) for t in TASKS})
    band2, source2 = st.noise_band_from_seeds([single])
    assert band2 == st.DEFAULT_NOISE_BAND
    assert "noise unobservable" in source2


def test_paired_comparison_refuses_mismatched_task_sets():
    a = arm("a", {"t1": (0.5,), "t2": (0.5,)})
    b = arm("b", {"t1": (0.6,)})
    with pytest.raises(ValueError, match="identical task sets"):
        st.paired_deltas(a, b)


# ---------------------------------------------------------------------------
# baselines and the budget ledger
# ---------------------------------------------------------------------------


def test_plan_rounds_k_in_the_baseline_s_favour():
    plan = bl.plan_matched_k(95, 10, 3)
    assert plan.k == 4
    assert plan.rollouts_used == 120
    assert plan.surplus == 25
    under = bl.plan_matched_k(95, 10, 3, favor_baseline=False)
    assert under.k == 3 and under.surplus < 0


def test_seed_control_spends_one_rollout_per_cell():
    runner = ScriptedRunner()
    ledger = bl.BudgetLedger()
    result = bl.SeedControl(runner, make_candidate()).run(TASKS, SEEDS, ledger=ledger)
    assert len(runner.calls) == len(TASKS) * len(SEEDS)
    assert result.budget.rollouts == 30
    # Three attempts per rollout: the initial try plus two stop-hook retries.
    assert result.budget.attempts == 90
    assert ledger.total("control").cost.usd == pytest.approx(7.5)


def test_best_of_k_spends_k_times_the_control_and_selects_per_cell():
    table = {}
    for t in TASKS:
        for rep in (1, 2, 3):
            for j in range(3):
                table[(t, rep * 1000 + j)] = 0.3 + 0.2 * j
    runner = ScriptedRunner(table=table)
    ledger = bl.BudgetLedger()
    result = bl.BestOfK(runner, make_candidate(), k=3).run(TASKS, SEEDS, ledger=ledger)
    assert result.budget.rollouts == 90
    scores = result.arm()
    assert scores.values(TASKS[0]) == (0.7, 0.7, 0.7)
    match = {m.arm: m for m in ledger.match("best_of_k")}
    assert match == {}  # only one arm recorded so far


def test_validator_selector_never_consults_the_score():
    # The highest-scoring draw carries the worst validator evidence, so a
    # selector that peeked would pick it and this test would fail.
    events = {
        ("task00", 1000): [{"severity": "error"}, {"severity": "error"}],
        ("task00", 1001): [{"severity": "info"}],
    }
    table = {("task00", 1000): 0.95, ("task00", 1001): 0.40}
    runner = ScriptedRunner(table=table, events=events)
    result = bl.BestOfK(runner, make_candidate(), k=2).run(("task00",), (1,))
    oracle = result.arm(bl.oracle_best)
    realizable = result.arm(bl.validator_best)
    assert oracle.values("task00") == (0.95,)
    assert realizable.values("task00") == (0.40,)
    # The gap between an upper bound and a deployable selector is itself a result.
    assert result.selection_gap(bl.validator_best) == pytest.approx(0.55)
    assert result.selection_gap(bl.oracle_best) == 0.0


def test_sequential_refinement_spends_its_budget_inside_the_rollout():
    runner = ScriptedRunner(retry_gain=0.05)
    ledger = bl.BudgetLedger()
    result = bl.SequentialRefinement(runner, make_candidate(), passes=4).run(
        TASKS, SEEDS, ledger=ledger
    )
    assert all(retries == 3 for _, _, retries in runner.calls)
    assert result.budget.rollouts == 30
    assert result.budget.attempts == 120
    assert result.arm().values(TASKS[0])[0] == pytest.approx(0.55)


def test_sequential_refinement_refuses_a_budget_the_stop_policy_cannot_spend():
    runner = ScriptedRunner()
    with pytest.raises(bl.BaselineError, match="cannot be budget-matched"):
        bl.SequentialRefinement(runner, make_candidate(), passes=9).run(TASKS, SEEDS)


def test_ledger_reports_every_unit_and_flags_unmeasured_ones():
    ledger = bl.BudgetLedger()
    ledger.record("search", rollouts=90, attempts=270, cost=Cost(tool_calls=900, usd=22.5))
    ledger.record("best_of_k", rollouts=90, attempts=270, cost=Cost(tool_calls=1800, usd=22.5))
    ledger.record("control", rollouts=30, attempts=90, cost=Cost(tool_calls=300, usd=7.5))
    matches = {m.arm: m for m in ledger.match("search")}
    assert matches["best_of_k"].matched_in("rollouts")
    assert not matches["best_of_k"].matched_in("tool_calls")
    assert matches["best_of_k"].ratios["tool_calls"] == pytest.approx(2.0)
    assert not matches["control"].matched_in("rollouts")
    # The reference recorded no tokens, so token ratios are unmeasured, not 1.0x.
    assert "input_tokens" in matches["control"].unmeasured_units
    table = ledger.render_markdown(reference="search")
    assert "| search | 90 | 270 |" in table and "Ratios against `search`" in table


def test_matched_suite_runs_all_arms_at_one_planned_budget():
    runner = ScriptedRunner()
    results, ledger, plan = bl.run_matched_suite(
        runner, make_candidate(), TASKS, search_rollouts=90, seeds=SEEDS
    )
    assert plan.k == 3
    assert set(results) == {
        "seed_control",
        "best_of_k_oracle",
        "best_of_k_validator",
        "sequential_refinement",
    }
    assert ledger.total("best_of_k").rollouts == 90
    assert ledger.total("control").rollouts == 30
    # The realizable selector reuses rollouts already paid for.
    assert results["best_of_k_validator"].budget.rollouts == 90
    assert ledger.arms() == ("control", "best_of_k", "sequential_refinement")


# ---------------------------------------------------------------------------
# slice discipline
# ---------------------------------------------------------------------------


def make_protocol() -> EvaluationProtocol:
    return EvaluationProtocol(
        anchor=("a1", "a2", "a3"), probe=("p1", "p2"), held_out=("h1", "h2")
    )


def test_held_out_is_refused_to_a_selection_call():
    proto = make_protocol()
    with pytest.raises(SliceViolation, match="may never inform selection"):
        proto.request("held_out", "selection", requester="search_loop")
    assert not proto.held_out_released


def test_probe_is_refused_to_a_selection_call():
    proto = make_protocol()
    with pytest.raises(SliceViolation, match="second anchor"):
        proto.request("probe", "selection", requester="search_loop")
    assert proto.tasks_for_evidence(requester="evidence_corpus") == ("p1", "p2")


def test_held_out_is_served_exactly_once():
    proto = make_protocol()
    release = proto.release_held_out(requester="final_eval", candidate_id="cand_a")
    assert release.tasks == ("h1", "h2")
    with pytest.raises(SliceViolation, match="already released"):
        proto.release_held_out(requester="final_eval", candidate_id="cand_a")
    with pytest.raises(SliceViolation, match="served exactly once"):
        proto.request("held_out", "final_report", requester="final_eval")


def test_slices_must_be_disjoint():
    with pytest.raises(SliceViolation, match="disjoint"):
        EvaluationProtocol(anchor=("a1", "h1"), held_out=("h1",))
    with pytest.raises(SliceViolation, match="anchor slice must be non-empty"):
        EvaluationProtocol(anchor=())


def test_selection_rollouts_from_other_slices_are_rejected():
    proto = make_protocol()
    rollouts = [
        Rollout(task="a1", candidate_id="c", seed=1, score=Score("a1", 0.5)),
        Rollout(task="h1", candidate_id="c", seed=1, score=Score("h1", 0.9)),
    ]
    with pytest.raises(SliceViolation, match="h1"):
        proto.assert_selection_safe(rollouts, requester="acceptance_gate")
    proto.assert_selection_safe(rollouts[:1], requester="acceptance_gate")


def test_a_rollout_labelled_non_anchor_is_rejected_even_on_an_anchor_task():
    proto = make_protocol()
    labelled = Rollout(
        task="a1", candidate_id="c", seed=1, score=Score("a1", 0.5), slice="probe"
    )
    with pytest.raises(SliceViolation, match="a1"):
        proto.assert_selection_safe([labelled], requester="acceptance_gate")


def test_final_arm_requires_an_audited_release():
    proto = make_protocol()
    rollouts = [Rollout(task="h1", candidate_id="c", seed=1, score=Score("h1", 0.9))]
    with pytest.raises(SliceViolation, match="before release_held_out"):
        proto.assert_final_arm(rollouts, requester="report")
    proto.release_held_out(requester="final_eval", candidate_id="cand_a")
    proto.assert_final_arm(rollouts, requester="report")
    with pytest.raises(SliceViolation, match="mixed non-held-out"):
        proto.assert_final_arm(
            rollouts + [Rollout(task="a1", candidate_id="c", seed=1, score=Score("a1", 0.4))],
            requester="report",
        )


def test_every_access_is_recorded_in_the_audit_trail():
    proto = make_protocol()
    proto.tasks_for_selection(requester="search_loop", candidate_id="cand_a")
    proto.tasks_for_evidence(requester="evidence_corpus")
    proto.release_held_out(requester="final_eval", candidate_id="cand_a")
    log = proto.access_log
    assert [r.slice_name for r in log] == ["anchor", "probe", "held_out"]
    assert [r.purpose for r in log] == ["selection", "evidence", "final_report"]
    audit = proto.render_audit()
    assert "held-out released: yes" in audit and "cand_a" in audit


def test_from_split_is_deterministic_and_disjoint():
    tasks = [f"t{i:02d}" for i in range(20)]
    a = EvaluationProtocol.from_split(tasks, n_probe=3, n_held_out=5)
    b = EvaluationProtocol.from_split(list(reversed(tasks)), n_probe=3, n_held_out=5)
    assert (a.anchor, a.probe, a.held_out) == (b.anchor, b.probe, b.held_out)
    assert set(a.anchor) & set(a.held_out) == set()
    with pytest.raises(SliceViolation, match="no anchor tasks"):
        EvaluationProtocol.from_split(tasks[:5], n_probe=3, n_held_out=3)


# ---------------------------------------------------------------------------
# report and verdict
# ---------------------------------------------------------------------------


def build_report(
    treatment: st.ArmScores,
    control: st.ArmScores,
    bok: st.ArmScores,
    *,
    ledger: bl.BudgetLedger | None = None,
) -> EvaluationReport:
    cand = make_candidate()
    comparisons = {
        "seed_control": st.compare(control, treatment, resamples=500),
        "best_of_k": st.compare(bok, treatment, resamples=500),
    }
    configs = {
        "evolved": ArmConfig.from_candidate(
            "evolved", cand, label="adapter g3", model="frozen-coder-v1",
            harness="claude-code + adapter", simulator="geos", seeds=SEEDS,
        ),
        "seed_control": ArmConfig(
            key="seed_control", label="seed adapter", model="frozen-coder-v1",
            harness="claude-code + adapter", seeds=SEEDS,
        ),
        "best_of_k": ArmConfig(
            key="best_of_k", label="seed adapter + best-of-3", model="frozen-coder-v1",
            harness="claude-code + adapter", seeds=SEEDS, scaling="parallel k=3",
        ),
    }
    return EvaluationReport(
        title="held-out comparison",
        treatment_key="evolved",
        configs=configs,
        comparisons=comparisons,
        ledger=ledger,
        criterion=VerdictCriterion(),
        plan=bl.plan_matched_k(90, 10, 3),
        selector_gaps={"best_of_k": 0.12},
    )


def matched_ledger() -> bl.BudgetLedger:
    led = bl.BudgetLedger()
    led.record("search", rollouts=90, attempts=270, cost=Cost(tool_calls=900))
    led.record("seed_control", rollouts=30, attempts=90, cost=Cost(tool_calls=300))
    led.record("best_of_k", rollouts=90, attempts=270, cost=Cost(tool_calls=900))
    return led


def test_report_states_the_criterion_before_the_numbers():
    base, treat = tail_driven_fixture()
    bok = arm("seed adapter + best-of-3", {t: (0.82, 0.82, 0.82) for t in TASKS})
    text = build_report(treat, base, bok, ledger=matched_ledger()).render()
    assert text.index("Criterion (fixed before the numbers below)") < text.index(
        "Per-task paired results"
    )
    assert text.index("Per-task paired results") < text.index(
        "Does this survive a compute-matched comparison?"
    )
    # model x harness configuration header, not "system X scores Y"
    assert "| arm | model | harness | adapter |" in text
    assert "frozen-coder-v1" in text
    assert "## Budget ledger" in text and "Ratios against `search`" in text
    assert "## Tail statistics" in text and "zero rate" in text
    assert "no CI" in text  # the guard rail is visible in the rendered report


def test_verdict_is_mechanism_only_when_the_tail_moves_but_power_is_absent():
    base, treat = tail_driven_fixture()
    bok = arm("seed adapter + best-of-3", {t: (0.70, 0.70, 0.70) for t in TASKS})
    verdict = build_report(treat, base, bok, ledger=matched_ledger()).verdict()
    assert verdict.outcome == "mechanism_only"
    assert any("rescued 2" in r for r in verdict.reasons)


def test_verdict_fails_when_a_compute_matched_baseline_keeps_up():
    base, treat = tail_driven_fixture()
    # Best-of-3 on the seed adapter recovers the same tail by resampling.
    strong = arm(
        "seed adapter + best-of-3",
        {t: (max(treat.values(t)),) * 3 for t in TASKS},
    )
    verdict = build_report(treat, base, strong, ledger=matched_ledger()).verdict()
    assert verdict.outcome == "fails"
    assert any("vs `best_of_k`" in r and "fails" in r for r in verdict.reasons)


def test_verdict_will_not_certify_an_unaudited_budget():
    base, treat = tail_driven_fixture()
    bok = arm("seed adapter + best-of-3", {t: (0.70, 0.70, 0.70) for t in TASKS})
    verdict = build_report(treat, base, bok, ledger=None).verdict()
    assert verdict.outcome == "fails"
    assert verdict.unmatched_arms == ("best_of_k",)
    assert any("no ledger supplied" in r for r in verdict.reasons)


def test_verdict_survives_only_with_paired_support():
    broad_base, broad_treat = broad_gain_fixture(0.2)
    bok = arm("seed adapter + best-of-3", {t: (0.65, 0.65, 0.65) for t in TASKS})
    verdict = build_report(broad_treat, broad_base, bok, ledger=matched_ledger()).verdict()
    assert verdict.outcome == "survives"


def test_report_refuses_to_render_without_a_control_comparison():
    base, treat = tail_driven_fixture()
    report = EvaluationReport(
        title="no control",
        treatment_key="evolved",
        configs={},
        comparisons={"best_of_k": st.compare(base, treat, resamples=200)},
    )
    with pytest.raises(KeyError, match="control"):
        report.render()
