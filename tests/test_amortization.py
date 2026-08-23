"""Amortization arithmetic, its quality gate, and the zero-marginal ledger.

Every fixture is inline. The suite must run on a laptop with no data volume,
and the shapes that matter -- an evolved arm that is behind its scaling
baseline, a mechanism that derives nothing -- are easier to construct than to
find.

The numbers in the crossover tests are hand-computed in the docstrings rather
than recomputed by the test, because a test that reimplements the function it
checks proves only that the function is self-consistent.
"""

from __future__ import annotations

import pytest

from harness_evolve.core.candidate import Candidate
from harness_evolve.core.manifest import ComponentSpec, Manifest, StopPolicy
from harness_evolve.evaluation import baselines as bl
from harness_evolve.evaluation import stats as st
from harness_evolve.evaluation.amortization import (
    AMORTIZED_UNITS,
    AmortizationAnalysis,
    ArmEconomics,
    Crossover,
    OneTimeCost,
    QualityPrecondition,
    crossover_n,
)
from harness_evolve.evaluation.report import ArmConfig, EvaluationReport, VerdictCriterion
from harness_evolve.evaluation.zero_marginal import (
    DerivedConstraints,
    Improvement,
    ZeroMarginalLedger,
    constraint_key,
)
from harness_evolve.types import Cost, Rollout, Score

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

TASKS = tuple(f"task{i:02d}" for i in range(10))
SEEDS = (1, 2, 3)


def arm(label: str, per_task: dict[str, tuple[float, ...]]) -> st.ArmScores:
    return st.ArmScores(label=label, per_task=per_task)


def flat(label: str, value: float, *, jitter: float = 0.002) -> st.ArmScores:
    """An arm that scores the same everywhere, with a little across-seed noise.

    The noise is not decoration: the win/loss band is derived from across-seed
    spread, and an arm with zero spread would produce a band at the floor and
    make every fixture's ties into wins.
    """
    return arm(
        label,
        {t: (value, value + jitter, value - jitter) for t in TASKS},
    )


def tail_rescue_arms() -> tuple[st.ArmScores, st.ArmScores]:
    """Seed control vs an evolved adapter that rescues the two failing tasks.

    The measured shape this whole protocol exists for: eight tasks inside noise,
    two catastrophic terminations pulled off the floor.
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
    return arm("seed adapter (control)", base), arm("adapter g3", treat)


def passing_precondition() -> QualityPrecondition:
    """Evolved beats the seed on the tail and ties the scaling arm task for task."""
    control, evolved = tail_rescue_arms()
    # The scaling arm recovers the same two tasks by drawing five samples, which
    # is the situation the amortization question is *for*: same quality, one
    # arm paying k x for it on every task forever.
    bok = arm("seed adapter + best-of-5", dict(evolved.per_task))
    return QualityPrecondition.from_comparisons(
        vs_seed=st.compare(control, evolved, resamples=200),
        vs_tts=st.compare(bok, evolved, resamples=200),
    )


def search_cost() -> OneTimeCost:
    """A 90-rollout search: $90 and one wall hour, in round numbers."""
    return OneTimeCost(label="search", rollouts=90, usd=90.0, wall_seconds=3600.0)


def evolved_economics() -> ArmEconomics:
    return ArmEconomics(
        label="adapter g3",
        k=1,
        rollouts_per_task=1.0,
        usd_per_task=0.5,
        wall_seconds_per_task=100.0,
    )


def tts_economics() -> ArmEconomics:
    return ArmEconomics(
        label="seed adapter + best-of-5",
        k=5,
        rollouts_per_task=5.0,
        usd_per_task=3.0,
        wall_seconds_per_task=400.0,
    )


def analysis(**overrides) -> AmortizationAnalysis:
    kwargs = dict(
        evolved=evolved_economics(),
        tts=tts_economics(),
        one_time=search_cost(),
        precondition=passing_precondition(),
        task_solutions_per_day=4.0,
    )
    kwargs.update(overrides)
    return AmortizationAnalysis(**kwargs)


# ---------------------------------------------------------------------------
# crossover arithmetic
# ---------------------------------------------------------------------------


def test_crossover_matches_hand_computed_values_in_every_unit():
    """One-time 90 rollouts, 1/task vs 5/task: saves 4/task, so n* = 90//4 + 1 = 23.

    USD: 90 one-time, 0.5 vs 3.0 per task, saves 2.5, n* = 90//2.5 + 1 = 37.
    Wall: 3600 one-time, 100 vs 400 per task, saves 300, n* = 3600//300 + 1 = 13.
    """
    res = analysis().result()
    assert res.defined
    assert {u: res.crossovers[u].n_task_solutions for u in AMORTIZED_UNITS} == {
        "rollouts": 23,
        "usd": 37,
        "wall_seconds": 13,
    }


def test_the_crossing_point_is_strict_and_off_by_one_the_other_way_is_a_tie():
    """At n = 22 the two arms have spent 112 and 110 rollouts; at 23, 113 and 115.

    Reporting the tie point as the crossover would credit the evolved arm with
    a win at the exact budget where it has spent the same and additionally run
    a search.
    """
    c = analysis().result().crossover("rollouts")
    assert c.savings_at(22) < 0
    assert c.savings_at(23) > 0
    assert c.cumulative_evolved(22) == pytest.approx(112.0)
    assert c.cumulative_tts(22) == pytest.approx(110.0)


def test_units_can_disagree_and_all_of_them_are_reported():
    """Rollouts cross at 23 and USD at 37 here, because the evolved arm's own
    rollouts are not proportionally cheaper. Publishing only the earliest unit
    would be the same selective reporting `BudgetLedger.match` refuses."""
    res = analysis().result()
    assert set(res.crossovers) == set(AMORTIZED_UNITS)
    assert len({c.n_task_solutions for c in res.crossovers.values()}) > 1


def test_crossover_is_immediate_at_the_boundary_and_one_later_beyond_it():
    """Immediate means ahead from the first task, which needs one_time < savings.

    With savings of 2.5/task: a one-time cost of 2.4 crosses at n=1, and 2.5
    exactly is a tie at n=1 and so crosses at n=2.
    """
    assert crossover_n(2.4, 0.5, 3.0) == 1
    assert crossover_n(2.5, 0.5, 3.0) == 2
    assert crossover_n(0.0, 0.5, 3.0) == 1


def test_a_zero_cost_artifact_is_ahead_from_the_first_task_solution():
    """The bridge to `zero_marginal.py`: an improvement mined from rollouts
    already spent has no constant term at all, so a cheaper-per-task arm carrying
    it is ahead immediately rather than eventually. This is the shape a
    compute-matched comparison cannot argue with."""
    res = analysis(
        one_time=OneTimeCost(label="derived constraints", rollouts=0, usd=0.0,
                             wall_seconds=0.0),
    ).result()
    assert all(c.immediate for c in res.crossovers.values())
    assert "immediate" in res.crossover("rollouts").render()
    assert res.horizon is not None
    assert res.horizon.upfront_days == 0.0


def test_an_evolved_arm_that_is_also_cheaper_per_rollout_crosses_much_sooner():
    """Cheatsheet cells cut exploratory reads roughly in half, so the evolved
    rollout is individually cheaper as well as unique. That widens the per-task
    gap and pulls the USD crossover in; the test pins the direction and the
    size, since the effect is the reason per-rollout cost is measured rather
    than assumed equal."""
    expensive = analysis()
    # Same k=1, half the per-rollout cost: 0.25/task against the same 3.0.
    cheap = analysis(
        evolved=ArmEconomics(
            label="adapter g3",
            k=1,
            rollouts_per_task=1.0,
            usd_per_task=0.25,
            wall_seconds_per_task=50.0,
        )
    )
    assert expensive.result().crossover("usd").n_task_solutions == 37
    assert cheap.result().crossover("usd").n_task_solutions == 33
    # Rollout count is untouched by per-rollout price, so that unit does not move.
    assert cheap.result().crossover("rollouts").n_task_solutions == 23


def test_it_never_crosses_when_the_evolved_arm_is_not_cheaper_per_task():
    """A k=1 arm whose rollouts cost more than five cheap ones never recovers a
    one-time cost, however long the horizon. The result says so instead of
    returning a very large number that a reader would take for a plan."""
    res = analysis(
        evolved=ArmEconomics(
            label="adapter g3 (bloated)",
            k=1,
            rollouts_per_task=1.0,
            usd_per_task=4.0,
            wall_seconds_per_task=900.0,
        )
    ).result()
    usd = res.crossover("usd")
    assert usd.never and usd.n_task_solutions is None
    assert "never crosses" in usd.render()
    # The rollout unit still crosses; the two facts coexist and both print.
    assert res.crossover("rollouts").n_task_solutions == 23


def test_never_crossing_in_the_horizon_unit_yields_no_calendar_horizon():
    res = analysis(
        horizon_unit="usd",
        evolved=ArmEconomics(label="x", k=1, rollouts_per_task=1.0, usd_per_task=4.0),
    ).result()
    assert res.horizon is not None
    assert res.horizon.days_after_deployment is None
    assert "never cross" in res.horizon.render()


# ---------------------------------------------------------------------------
# wall-clock horizon
# ---------------------------------------------------------------------------


def test_breakeven_horizon_is_reported_in_calendar_days_with_the_search_separate():
    """23 task-solutions at 4/day is 5.75 days, after a 3600 s search = 0.0417 d.

    The search delay is not folded into the horizon: it is a wait before the
    first deployed task, which is a different scheduling fact from the rate at
    which the artifact pays back.
    """
    h = analysis().result().horizon
    assert h is not None
    assert h.days_after_deployment == pytest.approx(5.75)
    assert h.upfront_days == pytest.approx(3600.0 / 86400.0)
    assert h.total_days == pytest.approx(5.75 + 3600.0 / 86400.0)


def test_without_a_deployment_rate_the_horizon_refuses_a_calendar():
    h = analysis(task_solutions_per_day=0.0).result().horizon
    assert h is not None and h.days_after_deployment is None
    assert "cannot be put on a calendar" in h.render()


# ---------------------------------------------------------------------------
# the quality precondition
# ---------------------------------------------------------------------------


def test_no_crossover_when_the_evolved_arm_is_behind_the_scaling_arm():
    """arXiv:2607.12227's own numbers: evolution 67.4 against parallel sampling
    72.3. The analysis must refuse rather than compute how many tasks it takes
    for the worse system to become cheap."""
    control, evolved = tail_rescue_arms()
    stronger = arm(
        "seed adapter + best-of-5",
        {t: tuple(v + 0.049 for v in evolved.values(t)) for t in evolved.tasks},
    )
    pre = QualityPrecondition.from_comparisons(
        vs_seed=st.compare(control, evolved, resamples=200),
        vs_tts=st.compare(stronger, evolved, resamples=200),
    )
    assert pre.beats_seed and not pre.matches_tts and not pre.holds

    res = analysis(precondition=pre).result()
    assert not res.defined
    assert res.crossovers == {}
    assert "category error" in res.refusal
    with pytest.raises(ValueError, match="no crossover is defined"):
        res.crossover("rollouts")


def test_no_crossover_when_the_evolved_arm_does_not_beat_its_own_seed():
    """The gate that comes first. If the search returned something no better
    than the seed at k=1 -- the pre-registered likely outcome -- there is no
    one-time gain to spread over any horizon, and the refusal must say that
    rather than the milder thing about the scaling arm."""
    control, _ = tail_rescue_arms()
    returned_seed = arm("adapter g3", dict(control.per_task))
    pre = QualityPrecondition.from_comparisons(
        vs_seed=st.compare(control, returned_seed, resamples=200),
        vs_tts=st.compare(control, returned_seed, resamples=200),
    )
    assert not pre.beats_seed
    assert "does not beat the seed adapter at k=1" in pre.refusal

    res = analysis(precondition=pre).result()
    assert not res.defined and res.crossovers == {}
    assert "no one-time gain to amortize" in res.refusal
    # The refusal, not a number, is what renders.
    assert "crosses at" not in analysis(precondition=pre).render()


def test_a_new_catastrophic_task_fails_the_seed_gate_even_with_a_positive_mean():
    """Same rule the verdict applies to the control: a mean that rose while a
    task fell off a cliff is not an improvement to amortize."""
    control, evolved = tail_rescue_arms()
    broken = dict(evolved.per_task)
    broken[TASKS[0]] = (0.0, 0.05, 0.0)
    pre = QualityPrecondition.from_comparisons(
        vs_seed=st.compare(control, arm("adapter g3", broken), resamples=200),
        vs_tts=st.compare(control, arm("adapter g3", broken), resamples=200),
    )
    assert not pre.beats_seed
    assert any("catastrophic threshold" in r for r in pre.reasons)


def test_equal_quality_passes_the_scaling_gate_because_that_is_the_whole_question():
    """A tie is a failure for the matched-budget verdict and stays one. Here it
    is the interesting case: same result, one arm paying 5x for it forever."""
    pre = passing_precondition()
    assert pre.matches_tts and pre.holds
    assert pre.tts_delta == pytest.approx(0.0, abs=1e-9)
    assert pre.refusal == ""


# ---------------------------------------------------------------------------
# the assumption amortization cannot check for itself
# ---------------------------------------------------------------------------


def test_a_short_artifact_lifetime_means_the_crossover_is_never_reached():
    """The one-time cost is one-time only while the artifact stays valid. If a
    model upgrade re-opens the search every 10 task-solutions and the crossover
    is at 23, the constant term resets before it is ever recovered."""
    res = analysis(revalidation_interval=10).result()
    rollouts = res.crossover("rollouts")
    assert rollouts.n_task_solutions == 23
    assert not rollouts.outlives_revalidation
    assert "never reached in practice" in rollouts.render()
    assert "not reached within it" in analysis(revalidation_interval=10).render()


def test_a_long_artifact_lifetime_leaves_the_crossover_intact():
    res = analysis(revalidation_interval=500).result()
    assert all(c.outlives_revalidation for c in res.crossovers.values())


def test_an_unstated_lifetime_is_flagged_as_an_assumption_rather_than_assumed():
    assert "assumes the artifact stays valid indefinitely" in analysis().render()


# ---------------------------------------------------------------------------
# reading costs off what was actually spent
# ---------------------------------------------------------------------------


def test_one_time_cost_comes_from_the_ledger_the_search_recorded():
    ledger = bl.BudgetLedger()
    ledger.record("search", rollouts=90, cost=Cost(usd=5.94, wall_seconds=135000.0))
    one_time = OneTimeCost.from_ledger(ledger)
    assert one_time.rollouts == 90
    assert one_time.usd == pytest.approx(5.94)
    with pytest.raises(KeyError):
        OneTimeCost.from_ledger(ledger, "never_ran")


def test_per_task_economics_divide_a_measured_total_by_task_solutions():
    econ = ArmEconomics.from_measured(
        "best-of-5", k=5, rollouts=150.0, cost=Cost(usd=9.9, wall_seconds=225000.0),
        task_solutions=30,
    )
    assert econ.rollouts_per_task == pytest.approx(5.0)
    assert econ.usd_per_task == pytest.approx(0.33)
    with pytest.raises(ValueError):
        ArmEconomics.from_measured("x", k=1, rollouts=1.0, cost=Cost(), task_solutions=0)


def test_an_unknown_unit_is_an_error_rather_than_a_zero():
    with pytest.raises(KeyError):
        search_cost().unit("tool_calls")
    with pytest.raises(KeyError):
        evolved_economics().unit("input_tokens")


# ---------------------------------------------------------------------------
# the zero-marginal ledger
# ---------------------------------------------------------------------------

#: GEOS naming the legal action space at the point of failure. This is the text
#: the mechanism is free because of: it arrives whether or not anyone is
#: searching.
VALIDATOR_TEXT = (
    "Error: XML Node Solvers/SinglePhaseFVM contains unused attribute "
    "'totallyBogusAttribute'. Valid attributes are:\n"
    "  cflFactor, discretization, initialDt, logLevel, name, targetRegions\n"
)

SILENT_TEXT = "Error: input deck rejected.\n"

FORBID_ATTR_KEY = "forbid_attr:Solvers/SinglePhaseFVM:totallyBogusAttribute"


def donor_rollout(i: int, text: str) -> Rollout:
    """One rollout of a baseline arm, carrying whatever its validator said."""
    return Rollout(
        task=TASKS[i % len(TASKS)],
        candidate_id="seed",
        seed=i,
        score=Score(task=TASKS[i % len(TASKS)], value=0.0),
        slice="held_out",
        cost=Cost(tool_calls=40.0, usd=0.066),
        validator_events=[{"severity": "error", "validator_output": text}],
    )


def test_constraints_are_derivable_from_the_baselines_own_rollouts():
    """The strongest form of the claim: the improvement is mined from rollouts
    the compute-matched baseline spent on itself, so no budget buys it away."""
    ledger = ZeroMarginalLedger(donor_arm="best_of_k", donor_is_baseline=True)
    ledger.add_donor_rollouts(donor_rollout(i, VALIDATOR_TEXT) for i in range(4))
    ledger.add_improvement(
        Improvement(
            key=FORBID_ATTR_KEY, component="constraints", delta=0.06,
            search_rollouts=12, description="derived, then regression-gated",
        )
    )
    ledger.add_improvement(
        Improvement(key="primer:worked_example", component="primer", delta=0.02,
                    search_rollouts=36)
    )
    report = ledger.account()
    assert [i.key for i in report.zero_marginal] == [FORBID_ATTR_KEY]
    assert [i.key for i in report.search_funded] == ["primer:worked_example"]
    assert report.zero_marginal_fraction == pytest.approx(0.75)
    assert report.strictly_additive
    assert "strictly additive" in report.render()


def test_the_ledger_reports_zero_when_nothing_was_derivable():
    """A validator that emits verdicts rather than legal action spaces gives the
    mechanism nothing, and the honest number is zero, printed as prominently as
    a favourable one would be."""
    ledger = ZeroMarginalLedger()
    ledger.add_donor_rollouts(donor_rollout(i, SILENT_TEXT) for i in range(6))
    ledger.add_improvement(
        Improvement(key="primer:worked_example", component="primer", delta=0.07,
                    search_rollouts=36)
    )
    report = ledger.account()
    assert report.derivable == ()
    assert report.zero_marginal == ()
    assert report.zero_marginal_delta == 0.0
    assert report.zero_marginal_fraction == 0.0
    assert not report.strictly_additive
    assert "**Nothing was derivable from them: zero improvements" in report.render()


def test_an_improvement_cannot_be_declared_free_without_being_derived():
    """Attribution is by key minted from mined evidence. A constraint nobody's
    validator ever named is search-funded no matter what it is called."""
    ledger = ZeroMarginalLedger()
    ledger.add_donor_rollouts(donor_rollout(i, VALIDATOR_TEXT) for i in range(4))
    ledger.add_improvement(
        Improvement(key="forbid_attr:Solvers/SinglePhaseFVM:somethingElse",
                    component="constraints", delta=0.09, search_rollouts=24)
    )
    report = ledger.account()
    assert report.zero_marginal == ()
    assert len(report.search_funded) == 1
    assert report.zero_marginal_fraction == 0.0


def test_a_single_observation_is_not_yet_a_derivable_constraint():
    """Support accumulates before a complaint becomes a rule; one slip is one
    agent's slip. The unsupported case must not be credited as free."""
    ledger = ZeroMarginalLedger()
    ledger.add_donor_rollouts([donor_rollout(0, VALIDATOR_TEXT)])
    ledger.add_improvement(
        Improvement(key=FORBID_ATTR_KEY, component="constraints", delta=0.05)
    )
    assert ledger.account().zero_marginal == ()


def test_confirmation_rollouts_are_reported_separately_from_free_discovery():
    """Zero marginal cost is a claim about discovery only. The regression gate
    still costs rollouts, and hiding that would be the special pleading this
    accounting exists to prevent."""
    ledger = ZeroMarginalLedger()
    ledger.add_donor_rollouts(donor_rollout(i, VALIDATOR_TEXT) for i in range(4))
    ledger.add_improvement(
        Improvement(key=FORBID_ATTR_KEY, component="constraints", delta=0.06,
                    search_rollouts=12)
    )
    report = ledger.account()
    assert report.confirmation_rollouts == 12
    assert "Discovery was free; confirmation was not" in report.render()


def test_mining_the_searchs_own_rollouts_is_cheap_but_not_strictly_additive():
    """Rollouts the search spent came out of the same envelope the baseline is
    handed, so the no-budget-can-beat-it argument does not apply to them."""
    ledger = ZeroMarginalLedger(donor_arm="search", donor_is_baseline=False)
    ledger.add_donor_rollouts(donor_rollout(i, VALIDATOR_TEXT) for i in range(4))
    ledger.add_improvement(
        Improvement(key=FORBID_ATTR_KEY, component="constraints", delta=0.06)
    )
    report = ledger.account()
    assert report.zero_marginal and not report.strictly_additive
    assert "cheap rather than free" in report.render()


def test_no_fraction_is_reported_when_the_total_gain_is_not_positive():
    """A fraction of a zero or negative total is a large flattering number, not
    a small honest one, so it is refused instead of divided."""
    ledger = ZeroMarginalLedger()
    ledger.add_donor_rollouts(donor_rollout(i, VALIDATOR_TEXT) for i in range(4))
    ledger.add_improvement(
        Improvement(key=FORBID_ATTR_KEY, component="constraints", delta=0.04)
    )
    ledger.add_improvement(
        Improvement(key="primer:verbose", component="primer", delta=-0.04)
    )
    report = ledger.account()
    assert not report.fraction_reportable
    assert report.zero_marginal_fraction == 0.0
    assert "no share can be reported" in report.render()


def test_two_mechanisms_deriving_the_same_item_do_not_count_it_twice():
    ledger = ZeroMarginalLedger(
        mechanisms=[DerivedConstraints(), DerivedConstraints(name="duplicate")]
    )
    ledger.add_donor_rollouts(donor_rollout(i, VALIDATOR_TEXT) for i in range(4))
    assert len(ledger.account().derivable) == 1


def test_constraint_keys_are_stable_across_the_three_directive_kinds():
    from harness_evolve.evidence.directives import DerivedConstraint

    keys = [
        constraint_key(DerivedConstraint(
            kind="forbid_attr", prose="",
            entry={"kind": "forbid_attr", "tag": "Solvers", "attr": "bogus"})),
        constraint_key(DerivedConstraint(
            kind="forbid_element", prose="",
            entry={"kind": "forbid_element", "parent": "Solvers", "tag": "Bogus"})),
        constraint_key(DerivedConstraint(
            kind="require_reference", prose="",
            entry={"kind": "require_reference", "container": "regions",
                   "referenced": "region"})),
    ]
    assert keys == [
        "forbid_attr:Solvers:bogus",
        "forbid_element:Solvers:Bogus",
        "require_reference:regions:region",
    ]
    assert len(set(keys)) == 3


# ---------------------------------------------------------------------------
# report rendering
# ---------------------------------------------------------------------------


def make_candidate() -> Candidate:
    manifest = Manifest(
        components={
            "primer": ComponentSpec(
                name="primer", kind="prose", path="PRIMER.md", budget_tokens=1000
            ),
            "stop_policy": ComponentSpec(name="stop_policy", kind="config"),
        },
        stop_policy=StopPolicy(retries=2),
    )
    return Candidate(manifest=manifest, files={"PRIMER.md": "grounding primer"})


def zero_marginal_report():
    ledger = ZeroMarginalLedger(donor_arm="best_of_k", donor_is_baseline=True)
    ledger.add_donor_rollouts(donor_rollout(i, VALIDATOR_TEXT) for i in range(4))
    ledger.add_improvement(
        Improvement(key=FORBID_ATTR_KEY, component="constraints", delta=0.06,
                    search_rollouts=12)
    )
    ledger.add_improvement(
        Improvement(key="primer:worked_example", component="primer", delta=0.02,
                    search_rollouts=36)
    )
    return ledger.account()


def make_report(*, tts: st.ArmScores | None = None, **overrides) -> EvaluationReport:
    control, evolved = tail_rescue_arms()
    bok = tts if tts is not None else flat("seed adapter + best-of-5", 0.74)
    comparisons = {
        "seed_control": st.compare(control, evolved, resamples=200),
        "best_of_k": st.compare(bok, evolved, resamples=200),
    }
    ledger = bl.BudgetLedger()
    ledger.record("search", rollouts=90, attempts=270, cost=Cost(usd=90.0))
    ledger.record("best_of_k", rollouts=90, attempts=270, cost=Cost(usd=90.0))
    cand = make_candidate()
    kwargs = dict(
        title="held-out comparison",
        treatment_key="evolved",
        configs={
            "evolved": ArmConfig.from_candidate(
                "evolved", cand, label="adapter g3", model="frozen-coder-v1",
                harness="claude-code + adapter", simulator="geos", seeds=SEEDS,
            ),
        },
        comparisons=comparisons,
        ledger=ledger,
        criterion=VerdictCriterion(),
        amortization=analysis(),
        zero_marginal=zero_marginal_report(),
    )
    kwargs.update(overrides)
    return EvaluationReport(**kwargs)


def test_report_renders_an_amortization_and_a_zero_marginal_section():
    report = make_report()
    assert report.verdict().outcome != "fails"
    text = report.render()
    assert "## Amortization: when does the one-time search cost pay for itself?" in text
    assert "## Zero-marginal-cost improvements" in text
    assert "crosses at **n = 23**" in text
    assert "breakeven horizon" in text
    assert "**75%**" in text
    # Both sections sit after the verdict, never in place of it.
    assert text.index("Verdict:") < text.index("## Amortization")
    assert text.index("## Amortization") < text.index("## Zero-marginal-cost")


def test_a_failing_verdict_suppresses_the_crossover_rather_than_softening_it():
    """A compute-matched baseline that beat us is the finding. The amortization
    section must print that, not the number of tasks after which the losing
    system becomes the cheaper way to lose."""
    stronger = flat("seed adapter + best-of-5", 0.95)
    report = make_report(tts=stronger)
    assert report.verdict().outcome == "fails"
    text = report.render()
    assert "## Amortization: when does the one-time search cost pay for itself?" in text
    assert "**Not applicable: the verdict is `fails`.**" in text
    assert "crosses at" not in text
    # The zero-marginal accounting is still reported: it is a fact about where
    # the gain came from, not a defence of the verdict.
    assert "## Zero-marginal-cost improvements" in text


def test_both_sections_say_so_plainly_when_nothing_was_supplied():
    report = make_report(amortization=None, zero_marginal=None)
    text = report.render()
    assert "No amortization analysis supplied" in text
    assert "No zero-marginal accounting supplied" in text


def test_report_dict_carries_both_new_sections():
    d = make_report().to_dict()
    assert d["amortization"]["result"]["defined"] is True
    assert d["amortization"]["result"]["crossovers"]["rollouts"]["n_task_solutions"] == 23
    assert d["zero_marginal"]["zero_marginal_fraction"] == pytest.approx(0.75)
    assert make_report(amortization=None, zero_marginal=None).to_dict()["amortization"] is None


def test_crossover_dataclass_round_trips_to_a_dict():
    c = Crossover(unit="rollouts", one_time=90.0, evolved_per_task=1.0,
                  tts_per_task=5.0, n_task_solutions=23)
    d = c.to_dict()
    assert d["savings_per_task"] == pytest.approx(4.0)
    assert d["never"] is False and d["immediate"] is False
