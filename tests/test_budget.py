"""Search-budget planning against the baselines that must match it.

Every case here traces to a failure in the first end-to-end protocol run, where
budget matching failed structurally: a 126-rollout search against a 4-task
held-out slice at 3 seeds needed k=11, costing 2.10x the search, while the
control spent 0.19x. Neither could carry a verdict.
"""

from __future__ import annotations

import pytest

from harness_evolve.evaluation.budget import (
    DEFAULT_TOLERANCE, MAX_STOP_POLICY_RETRIES, BudgetOption, estimate_cost,
    plan_budget,
)


def test_matchable_budgets_are_multiples_of_the_cell_count():
    """Parallel scaling spends k draws per cell, so only multiples are reachable.
    A budget chosen for any other reason lands between them."""
    r = plan_budget(n_held_out=10, n_seeds=5, anchor_size=8)
    assert r.cells == 50
    assert [o.search_rollouts for o in r.options[:4]] == [50, 100, 150, 200]
    assert all(o.matched for o in r.options)


def test_the_failing_case_from_the_dry_run_is_diagnosed():
    """126 search rollouts against 4 held-out tasks at 3 seeds is not matchable."""
    r = plan_budget(n_held_out=4, n_seeds=3, anchor_size=6)
    assert r.cells == 12
    reachable = {o.search_rollouts for o in r.options}
    assert 126 not in reachable
    # `nearest` prefers a budget where *every* arm can be built, not merely one
    # where the ratio works out: a k the sequential arm cannot express leaves the
    # comparison short an arm, which is the same problem in a different place.
    nearest = r.nearest(126)
    assert nearest is not None
    assert nearest.sequential_feasible
    assert nearest.search_rollouts == 84, (
        "at 12 cells the fully-feasible budgets stop at k=7 (84 rollouts); "
        "126 is not merely unmatched, it is past where all three arms exist"
    )


def test_an_unmatched_option_is_flagged_not_hidden():
    o = BudgetOption(k=11, cells=12, baseline_rollouts=264, search_rollouts=126)
    assert not o.matched
    assert o.ratio == pytest.approx(2.095, abs=0.01)
    assert "UNMATCHED" in o.describe()


def test_the_sequential_arm_has_a_hard_ceiling():
    """It runs through the harness's own retry cap. Matching beyond that would
    mean changing the harness, which unfreezes what the claim holds fixed."""
    ok = BudgetOption(k=MAX_STOP_POLICY_RETRIES + 1, cells=50,
                      baseline_rollouts=350, search_rollouts=350)
    too_big = BudgetOption(k=MAX_STOP_POLICY_RETRIES + 2, cells=50,
                           baseline_rollouts=400, search_rollouts=400)
    assert ok.sequential_feasible
    assert not too_big.sequential_feasible
    assert "no sequential arm" in too_big.describe()


def test_feasible_excludes_options_missing_an_arm():
    r = plan_budget(n_held_out=10, n_seeds=5, anchor_size=8, max_k=12)
    assert all(o.sequential_feasible for o in r.feasible())
    assert len(r.feasible()) < len(r.options)


def test_the_ceiling_is_stated_as_a_warning():
    r = plan_budget(n_held_out=10, n_seeds=5, anchor_size=8, max_k=12)
    ceiling = [w for w in r.warnings if "sequential arm exists only" in w]
    assert ceiling, r.warnings
    assert "350 rollouts" in ceiling[0]


def test_budgets_convert_to_candidate_counts():
    """The number a person actually chooses is candidates, not rollouts."""
    r = plan_budget(n_held_out=10, n_seeds=5, anchor_size=8, search_seeds=2)
    k3 = next(o for o in r.options if o.k == 3)
    assert r.candidates_for(k3) == 150 // 16


def test_coarse_quantisation_is_warned_about():
    """When a cell sweep is cheaper than a candidate, some candidate counts are
    simply unreachable and the plan should say so."""
    r = plan_budget(n_held_out=2, n_seeds=1, anchor_size=8, search_seeds=3)
    assert any("quantised more coarsely" in w for w in r.warnings)


def test_render_shows_the_reasoning():
    r = plan_budget(n_held_out=10, n_seeds=5, anchor_size=8)
    text = r.render(wanted=150)
    assert "multiples of the cell count" in text
    assert "nearest feasible to 150" in text
    assert "candidate(s)" in text


def test_dimensions_must_be_positive():
    with pytest.raises(ValueError, match="positive"):
        plan_budget(n_held_out=0, n_seeds=5, anchor_size=8)


def test_cost_estimate_scales_and_is_labelled_as_an_aid():
    a = estimate_cost(150)
    b = estimate_cost(300)
    assert b["usd"] == pytest.approx(2 * a["usd"])
    assert b["wall_hours"] == pytest.approx(2 * a["wall_hours"])
    assert estimate_cost(150, workers=8)["wall_hours"] < a["wall_hours"]
