"""Run several evolution strategies against each other, or refuse to.

arXiv:2607.12227's charge against automatic harness evolution is not that the
methods are bad. It is that the comparisons are unsound: an arm that had more
inference compute than the baseline it beat has demonstrated nothing about its
strategy. The compute usually leaks in quietly — through rollouts spent on
candidates that were screened out and never counted, through a baseline that
stopped early, through a method whose per-candidate cost is lower and which
therefore silently receives a smaller share of a nominally shared cap.

So this module has one job beyond running the arms: it **refuses** to report a
comparison whose arms did not actually spend the same. Refusal is a
:class:`BudgetMismatch` carrying the partial comparison, so the numbers are
still inspectable — they are simply not allowed to be presented as a result.

The second thing it does is measure every arm's *selection* on one common slice
at one common seed set, out of a separate budget. Without that, the arms cannot
be ranked at all: a strict-improvement method that accepted on a held-out
validation slice and a control that kept the best anchor mean have reported
numbers from different populations, and putting them in one column would be the
same error in a smaller font. The search budget is matched; the measurement is
identical; and the two are never drawn from the same purse.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from harness_evolve.core.candidate import Candidate
from harness_evolve.evolvers.base import (
    BudgetedRunner,
    Evolver,
    EvolverResult,
    RolloutBudget,
    TaskSlices,
    evaluate_on,
)
from harness_evolve.runners.base import RolloutRunner

#: Relative spread in rollout spend that still counts as a matched comparison.
#: Matches the tolerance the evaluation protocol uses for compute-matched
#: baselines, so "matched" means one thing across the repository.
DEFAULT_TOLERANCE = 0.10


class BudgetMismatch(RuntimeError):
    """Arms did not spend comparably, so the comparison is not reportable.

    Carries the :class:`Comparison` it refused, because the diagnosis — which
    arm under-spent, and on what — is what a caller needs in order to fix the
    setup, and re-running four searches to find out would cost the whole budget
    again.
    """

    def __init__(self, message: str, comparison: "Comparison") -> None:
        super().__init__(message)
        self.comparison = comparison


@dataclass
class ArmOutcome:
    """One method's result, plus its score on the common measurement slice."""

    name: str
    result: EvolverResult
    #: Mean of the arm's *selected* candidate on the shared slice, or ``None``
    #: when no common measurement was taken. Never compare ``result.selected.mean``
    #: across arms: those means come from whichever slice each arm chose to
    #: select on, which is not the same slice for every arm here.
    common_score: float | None = None

    @property
    def spent(self) -> int:
        return self.result.spent

    @property
    def selected_cid(self) -> str:
        return self.result.selected.cid if self.result.selected else ""

    @property
    def returned_the_seed(self) -> bool:
        return self.result.returned_the_seed


@dataclass
class Comparison:
    """Several methods, one budget, one measurement — and whether it holds up."""

    budget_cap: int
    tolerance: float
    outcomes: tuple[ArmOutcome, ...]
    measurement_budget: RolloutBudget | None = None
    common_tasks: tuple[str, ...] = ()
    common_seeds: tuple[int, ...] = ()
    notes: list[str] = field(default_factory=list)

    @property
    def spends(self) -> dict[str, int]:
        return {o.name: o.spent for o in self.outcomes}

    @property
    def spread(self) -> float:
        """Largest relative gap between any two arms' spend.

        Relative to the *largest* spend: an arm that spent 90 against another's
        100 was short by 10% of what was available, which is the quantity a
        matching tolerance is about.
        """
        values = [o.spent for o in self.outcomes]
        if not values or max(values) == 0:
            return 0.0
        return (max(values) - min(values)) / max(values)

    @property
    def matched(self) -> bool:
        return self.spread <= self.tolerance

    def winner(self) -> ArmOutcome | None:
        """The arm whose selection measures best on the common slice.

        Refuses on an unmatched comparison and on a comparison with no common
        measurement, rather than returning the arm that looks best on numbers
        that are not comparable.
        """
        if not self.matched:
            raise BudgetMismatch(
                f"spend differs by {self.spread:.1%} across arms "
                f"(tolerance {self.tolerance:.0%}): {self.spends}",
                self,
            )
        scored = [o for o in self.outcomes if o.common_score is not None]
        if len(scored) != len(self.outcomes):
            raise ValueError(
                "no common measurement was taken, so arms selected on different "
                "slices cannot be ranked; pass measure_seeds to compare_evolvers"
            )
        return max(scored, key=lambda o: o.common_score or 0.0, default=None)

    def render(self) -> str:
        lines = [
            f"comparison at a {self.budget_cap}-rollout cap, "
            f"tolerance {self.tolerance:.0%}: "
            f"{'MATCHED' if self.matched else 'UNMATCHED'} "
            f"(spread {self.spread:.1%})"
        ]
        if self.common_tasks:
            lines.append(
                f"common measurement: {len(self.common_tasks)} task(s) x "
                f"{len(self.common_seeds)} seed(s)"
                + (
                    f", {self.measurement_budget.spent} rollouts off-budget"
                    if self.measurement_budget
                    else ""
                )
            )
        header = f"{'arm':<22}{'spent':>7}{'score':>9}  selection"
        lines += ["", header, "-" * len(header)]
        for o in sorted(self.outcomes, key=lambda o: -(o.common_score or 0.0)):
            score = "n/a" if o.common_score is None else f"{o.common_score:.4f}"
            tag = " (its seed)" if o.returned_the_seed else ""
            lines.append(
                f"{o.name:<22}{o.spent:>7}{score:>9}  {o.selected_cid}{tag}"
            )
        for o in self.outcomes:
            lines += ["", f"{o.name}: {o.result.trace.selection_reason}"]
            for note in o.result.notes:
                lines.append(f"  - {note}")
        lines += self.notes
        return "\n".join(lines)


def compare_evolvers(
    evolvers: Sequence[Evolver],
    seed: Candidate,
    slices: TaskSlices,
    runner: RolloutRunner,
    *,
    budget_rollouts: int,
    tolerance: float = DEFAULT_TOLERANCE,
    measure_tasks: Sequence[str] = (),
    measure_seeds: Sequence[int] = (1, 2),
    strict: bool = True,
) -> Comparison:
    """Run every arm from the same seed at the same rollout cap and compare them.

    Parameters
    ----------
    measure_tasks / measure_seeds:
        The common measurement. Defaults to the anchor slice, which is the one
        slice every arm's selection is meant to generalise over. Spent from a
        separate budget so measurement can never be confused with search: an arm
        is not penalised for being measured, and cannot be credited for it
        either. Pass ``measure_seeds=()`` to skip it, in which case the arms are
        reported but not ranked.
    strict:
        Raise :class:`BudgetMismatch` when the arms' spend differs by more than
        ``tolerance``. Turning it off returns the comparison with
        :attr:`Comparison.matched` false; :meth:`Comparison.winner` still
        refuses, so an unmatched comparison cannot become a verdict by accident.

    Raises
    ------
    BudgetMismatch
        When ``strict`` and the arms did not spend comparably.
    """
    names = [e.name for e in evolvers]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise ValueError(
            f"arm names must be unique; {duplicates} appear more than once and "
            "would collide in the ledger"
        )

    outcomes: list[ArmOutcome] = []
    for evolver in evolvers:
        budget = RolloutBudget(cap=budget_rollouts)
        result = evolver.evolve(seed, slices, BudgetedRunner(runner, budget), budget)
        outcomes.append(ArmOutcome(name=evolver.name, result=result))

    comparison = Comparison(
        budget_cap=budget_rollouts,
        tolerance=tolerance,
        outcomes=tuple(outcomes),
    )
    if not comparison.matched:
        message = (
            f"arms spent {comparison.spends}, a spread of {comparison.spread:.1%} "
            f"against a tolerance of {tolerance:.0%}; an unmatched comparison "
            "cannot carry a verdict"
        )
        if strict:
            raise BudgetMismatch(message, comparison)
        comparison.notes.append(f"WARNING: {message}")
        return comparison

    tasks = tuple(measure_tasks or slices.anchor)
    seeds = tuple(measure_seeds)
    if tasks and seeds:
        # A budget of its own, sized to exactly what the measurement needs.
        # Charging it against the search cap would make an arm pay to be
        # measured, and the measurement is identical for every arm — it is the
        # one thing in the comparison that must not be a variable.
        measurement = RolloutBudget(cap=len(tasks) * len(seeds) * len(outcomes))
        paid = BudgetedRunner(runner, measurement, note="measure")
        for outcome in outcomes:
            selection = outcome.result.selected_candidate
            if selection is None:
                continue
            outcome.common_score = evaluate_on(paid, selection, tasks, seeds).mean
        comparison.measurement_budget = measurement
        comparison.common_tasks = tasks
        comparison.common_seeds = seeds
    return comparison
