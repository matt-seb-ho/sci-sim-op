"""Planning a search budget that its own baselines can actually match.

The first end-to-end protocol run failed budget matching for a structural
reason, not an incidental one. A search spending 126 rollouts on a 6-task anchor,
compared on a 4-task held-out slice at 3 seeds, needs ``k = ceil(126/12) = 11``
parallel draws per cell — which costs 264 rollouts, **2.10x the search**. The
control, spending 24, comes in at **0.19x**. Neither sits inside any sane
tolerance, so neither can carry a verdict, and the central question goes
untested.

The relation is simple once stated:

    search_rollouts  ≈  |held_out| x n_seeds x k        for a small integer k

Parallel scaling can only be matched at *multiples of a cell count*. When the
held-out slice is much smaller than the search slice, the reachable budgets are
sparse and a budget chosen for other reasons will land between them.

This module makes that a planning step rather than a discovery. Choosing the
search budget after the held-out slice, instead of before, costs nothing at
planning time and cannot be repaired afterwards: by the time the mismatch is
visible the rollouts are spent.

A second constraint applies to the sequential arm. It runs through the harness's
own stop policy — initial attempt plus validator-fed retries — because that *is*
the refinement mechanism under study. Beyond the policy's retry cap the arm
cannot be constructed at all without changing the harness, which unfreezes the
thing the claim holds fixed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

#: Fraction by which a baseline's spend may differ from the search's and still
#: be treated as matched. Matches the default verdict criterion.
DEFAULT_TOLERANCE = 0.10

#: Largest `retries` a stop policy will accept, so the sequential arm can spend
#: at most this many extra attempts beyond the first.
MAX_STOP_POLICY_RETRIES = 6


@dataclass(frozen=True)
class BudgetOption:
    """One feasible (k, search budget) pairing for a given experiment shape."""

    k: int
    cells: int
    baseline_rollouts: int
    search_rollouts: int
    tolerance: float = DEFAULT_TOLERANCE

    @property
    def ratio(self) -> float:
        return self.baseline_rollouts / self.search_rollouts

    @property
    def matched(self) -> bool:
        return abs(self.ratio - 1.0) <= self.tolerance

    @property
    def sequential_feasible(self) -> bool:
        """Can the sequential arm express ``k`` attempts through the stop policy?"""
        return self.k <= MAX_STOP_POLICY_RETRIES + 1

    def describe(self) -> str:
        flags = []
        if not self.matched:
            flags.append(f"UNMATCHED {self.ratio:.2f}x")
        if not self.sequential_feasible:
            flags.append(
                f"no sequential arm (k={self.k} > {MAX_STOP_POLICY_RETRIES + 1})"
            )
        suffix = f"  [{'; '.join(flags)}]" if flags else ""
        return (
            f"k={self.k:<3d} search {self.search_rollouts:>5d} rollouts, "
            f"parallel baseline {self.baseline_rollouts:>5d} "
            f"({self.ratio:.2f}x){suffix}"
        )


@dataclass
class BudgetPlanReport:
    """Feasible budgets for one experiment shape, and what constrains them."""

    n_held_out: int
    n_seeds: int
    anchor_size: int
    search_seeds: int
    options: tuple[BudgetOption, ...] = ()
    warnings: list[str] = field(default_factory=list)

    @property
    def cells(self) -> int:
        return self.n_held_out * self.n_seeds

    def feasible(self) -> tuple[BudgetOption, ...]:
        """Options that are both budget-matched and support every arm."""
        return tuple(o for o in self.options if o.matched and o.sequential_feasible)

    def nearest(self, wanted: int) -> BudgetOption | None:
        """The feasible option closest to a desired search budget."""
        pool = self.feasible() or self.options
        if not pool:
            return None
        return min(pool, key=lambda o: abs(o.search_rollouts - wanted))

    def candidates_for(self, option: BudgetOption) -> int:
        """How many candidates that budget buys, at this anchor and seed count."""
        per_candidate = self.anchor_size * self.search_seeds
        return option.search_rollouts // max(per_candidate, 1)

    def render(self, wanted: int | None = None) -> str:
        lines = [
            f"held-out {self.n_held_out} tasks x {self.n_seeds} seeds "
            f"= {self.cells} cells",
            f"search anchor {self.anchor_size} tasks x {self.search_seeds} seeds "
            f"= {self.anchor_size * self.search_seeds} rollouts per candidate",
            "",
            "reachable search budgets (a parallel baseline can only be matched at "
            "multiples of the cell count):",
        ]
        for o in self.options:
            n = self.candidates_for(o)
            lines.append(f"  {o.describe()}   ~{n} candidate(s)")
        if wanted is not None:
            best = self.nearest(wanted)
            lines.append("")
            if best is None:
                lines.append(f"no feasible budget near {wanted}")
            else:
                lines.append(
                    f"nearest feasible to {wanted}: {best.search_rollouts} rollouts "
                    f"(k={best.k}, {self.candidates_for(best)} candidates)"
                )
        for w in self.warnings:
            lines.append(f"WARNING: {w}")
        return "\n".join(lines)


def plan_budget(
    *,
    n_held_out: int,
    n_seeds: int,
    anchor_size: int,
    search_seeds: int = 2,
    max_k: int = 12,
    tolerance: float = DEFAULT_TOLERANCE,
) -> BudgetPlanReport:
    """Enumerate the search budgets whose baselines can be matched.

    Because ``k`` is an integer, only budgets at multiples of the cell count are
    exactly matchable; everything between them lands outside tolerance. The
    report lists them all with their ratios so the choice is visible rather than
    implied.
    """
    if min(n_held_out, n_seeds, anchor_size, search_seeds) <= 0:
        raise ValueError("every dimension must be positive")

    cells = n_held_out * n_seeds
    report = BudgetPlanReport(
        n_held_out=n_held_out, n_seeds=n_seeds,
        anchor_size=anchor_size, search_seeds=search_seeds,
    )
    options = []
    for k in range(1, max_k + 1):
        baseline = k * cells
        # The exactly-matched search budget for this k is the baseline's own
        # spend; that is the only point where the ratio is 1.0.
        options.append(
            BudgetOption(k=k, cells=cells, baseline_rollouts=baseline,
                         search_rollouts=baseline, tolerance=tolerance)
        )
    report.options = tuple(options)

    per_candidate = anchor_size * search_seeds
    if cells < per_candidate:
        report.warnings.append(
            f"each candidate costs {per_candidate} rollouts but a full baseline "
            f"cell sweep costs only {cells}; budgets are quantised more coarsely "
            "than candidates, so some candidate counts are unreachable"
        )
    reachable = [o for o in options if o.sequential_feasible]
    if reachable:
        top = max(reachable, key=lambda o: o.search_rollouts)
        report.warnings.append(
            f"the sequential arm exists only up to k={MAX_STOP_POLICY_RETRIES + 1}, "
            f"i.e. a search of at most {top.search_rollouts} rollouts "
            f"({top.search_rollouts // per_candidate} candidates). Beyond that the "
            "arm cannot be constructed without changing the harness."
        )
    return report


def estimate_cost(
    rollouts: int, *, usd_per_rollout: float = 0.066, minutes_per_rollout: float = 25.0,
    workers: int = 4,
) -> dict[str, float]:
    """Rough cost and wall-clock for a rollout count.

    Defaults come from previously observed per-task-run figures. They are an
    order-of-magnitude aid for choosing between budgets, not a quotation.
    """
    return {
        "rollouts": rollouts,
        "usd": rollouts * usd_per_rollout,
        "wall_hours": rollouts * minutes_per_rollout / 60.0 / max(workers, 1),
    }
