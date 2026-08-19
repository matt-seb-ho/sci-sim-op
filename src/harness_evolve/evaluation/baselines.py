"""Compute-matched task-level search baselines, and the ledger that proves it.

The published critique of harness evolution (arXiv:2607.12227) is not that
evolved harnesses fail; it is that harness evolution *is itself* an iterative
search that spends inference compute evaluating candidates against task
feedback, so a gain over a single un-evolved run is not evidence of better
design until the same compute has been handed to the dumbest possible
alternative -- parallel sampling and sequential refinement at the task level.
The predecessor system in this lineage reported "+0.069 from self-evolution"
with no such comparison anywhere, which makes the number unfalsifiable rather
than wrong.

So this module provides three baselines and one ledger:

* :class:`SeedControl` -- the un-evolved seed adapter, same seeds, no extra
  budget. The cheapest and by far the most important: if the evolved candidate
  does not beat this, nothing else needs computing.
* :class:`BestOfK` -- k independent rollouts of the *seed* adapter per task,
  keep one. Parallel test-time scaling.
* :class:`SequentialRefinement` -- k in-rollout attempts driven by validator
  feedback, expressed through the seed adapter's own stop policy. Sequential
  test-time scaling.
* :class:`BudgetLedger` -- rollouts, in-rollout attempts, and :class:`Cost` for
  the search *and* every baseline in the same units, so "budget-matched" is
  something a reader can check rather than something we assert.

A note the ledger makes unavoidable: parallel and sequential scaling are not
matchable in the same unit. Best-of-k spends k rollouts per task-seed;
refinement spends one rollout containing k attempts. Any claim of matching must
name its unit, and :meth:`BudgetLedger.match` reports every unit rather than
picking the flattering one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Callable, Iterable, Mapping, Sequence

from harness_evolve.core.candidate import Candidate
from harness_evolve.evaluation.stats import ArmScores
from harness_evolve.runners.base import RolloutRunner
from harness_evolve.types import Cost, Rollout, TaskId

__all__ = [
    "BaselineError",
    "BaselineResult",
    "BestOfK",
    "BudgetEntry",
    "BudgetLedger",
    "BudgetMatch",
    "BudgetPlan",
    "Cell",
    "SeedControl",
    "SequentialRefinement",
    "Selector",
    "ValidatorBest",
    "oracle_best",
    "plan_matched_k",
    "run_matched_suite",
    "validator_best",
]

#: Units a budget can be matched in. Reported together, always.
BUDGET_UNITS: tuple[str, ...] = (
    "rollouts",
    "attempts",
    "tool_calls",
    "wall_seconds",
    "input_tokens",
    "output_tokens",
    "usd",
)


class BaselineError(RuntimeError):
    """A baseline cannot be run honestly under the requested budget.

    Raised rather than degraded. A baseline that silently spends less than the
    search it is being compared against is worse than no baseline, because it
    manufactures the very result the comparison exists to test.
    """


# --------------------------------------------------------------------------
# budget accounting
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class BudgetEntry:
    """What one arm spent, in every unit we can account.

    ``attempts`` counts agent attempts *inside* rollouts (initial try plus stop
    hook retries). It exists because sequential refinement hides its compute
    there: without it, a refinement baseline looks free next to best-of-k.
    """

    arm: str
    rollouts: int
    attempts: int
    cost: Cost = field(default_factory=Cost)
    note: str = ""

    def merged(self, other: "BudgetEntry") -> "BudgetEntry":
        return BudgetEntry(
            arm=self.arm,
            rollouts=self.rollouts + other.rollouts,
            attempts=self.attempts + other.attempts,
            cost=self.cost + other.cost,
            note="; ".join(n for n in (self.note, other.note) if n),
        )

    def unit(self, name: str) -> float:
        if name == "rollouts":
            return float(self.rollouts)
        if name == "attempts":
            return float(self.attempts)
        return float(getattr(self.cost, name))

    def to_dict(self) -> dict[str, object]:
        return {
            "arm": self.arm,
            "rollouts": self.rollouts,
            "attempts": self.attempts,
            "cost": self.cost.to_dict(),
            "note": self.note,
        }


@dataclass(frozen=True)
class BudgetMatch:
    """How one arm's spend compares to the reference arm, unit by unit."""

    arm: str
    reference: str
    tolerance: float
    ratios: Mapping[str, float]
    matched_units: tuple[str, ...]
    unmatched_units: tuple[str, ...]
    unmeasured_units: tuple[str, ...]

    def matched_in(self, unit: str) -> bool:
        return unit in self.matched_units

    def render(self) -> str:
        parts = [f"{u}={self.ratios[u]:.2f}x" for u in sorted(self.ratios)]
        return f"{self.arm} vs {self.reference}: " + ", ".join(parts)

    def to_dict(self) -> dict[str, object]:
        return {
            "arm": self.arm,
            "reference": self.reference,
            "tolerance": self.tolerance,
            "ratios": dict(self.ratios),
            "matched_units": list(self.matched_units),
            "unmatched_units": list(self.unmatched_units),
            "unmeasured_units": list(self.unmeasured_units),
        }


@dataclass
class BudgetLedger:
    """Rollouts, attempts, and cost per arm, in one auditable place.

    Every arm in a comparison -- including the search itself -- records here,
    and the report prints it. That is the whole mechanism: budget matching is
    made checkable by a third party rather than claimed in prose.
    """

    entries: list[BudgetEntry] = field(default_factory=list)

    def record(
        self,
        arm: str,
        *,
        rollouts: int,
        attempts: int | None = None,
        cost: Cost | None = None,
        note: str = "",
    ) -> BudgetEntry:
        """Record a spend for ``arm``. Repeated calls accumulate."""
        entry = BudgetEntry(
            arm=arm,
            rollouts=rollouts,
            attempts=rollouts if attempts is None else attempts,
            cost=cost or Cost(),
            note=note,
        )
        self.entries.append(entry)
        return entry

    def record_rollouts(
        self,
        arm: str,
        rollouts: Sequence[Rollout],
        *,
        attempts_per_rollout: int = 1,
        note: str = "",
    ) -> BudgetEntry:
        """Record from actual rollouts, so the ledger reflects what was spent.

        Costs are summed from the rollouts themselves rather than estimated: an
        estimated ledger would be exactly as trustworthy as the assertion it is
        meant to replace.
        """
        total = Cost()
        for r in rollouts:
            total = total + r.cost
        return self.record(
            arm,
            rollouts=len(rollouts),
            attempts=len(rollouts) * attempts_per_rollout,
            cost=total,
            note=note,
        )

    def arms(self) -> tuple[str, ...]:
        seen: list[str] = []
        for e in self.entries:
            if e.arm not in seen:
                seen.append(e.arm)
        return tuple(seen)

    def total(self, arm: str) -> BudgetEntry:
        """Accumulated spend for ``arm``."""
        acc = BudgetEntry(arm=arm, rollouts=0, attempts=0, cost=Cost())
        found = False
        for e in self.entries:
            if e.arm == arm:
                acc = acc.merged(e)
                found = True
        if not found:
            raise KeyError(f"no budget recorded for arm {arm!r}")
        return acc

    def match(
        self,
        reference: str,
        *,
        tolerance: float = 0.10,
        units: Sequence[str] = BUDGET_UNITS,
    ) -> list[BudgetMatch]:
        """Ratio of every other arm's spend to ``reference``, unit by unit.

        Units where the reference spent nothing are reported as *unmeasured*
        rather than as a ratio: a runner that does not populate ``usd`` must not
        thereby appear to be perfectly matched.
        """
        ref = self.total(reference)
        out: list[BudgetMatch] = []
        for arm in self.arms():
            if arm == reference:
                continue
            spent = self.total(arm)
            ratios: dict[str, float] = {}
            unmeasured: list[str] = []
            for u in units:
                denom = ref.unit(u)
                if denom <= 0:
                    unmeasured.append(u)
                else:
                    ratios[u] = spent.unit(u) / denom
            matched = tuple(
                u for u, r in ratios.items() if abs(r - 1.0) <= tolerance
            )
            out.append(
                BudgetMatch(
                    arm=arm,
                    reference=reference,
                    tolerance=tolerance,
                    ratios=ratios,
                    matched_units=matched,
                    unmatched_units=tuple(u for u in ratios if u not in matched),
                    unmeasured_units=tuple(unmeasured),
                )
            )
        return out

    def render_markdown(self, reference: str | None = None) -> str:
        """Markdown table of every arm's spend, plus ratios to ``reference``."""
        lines = [
            "| arm | rollouts | attempts | tool calls | wall (s) | in tok | out tok | USD | note |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
        for arm in self.arms():
            e = self.total(arm)
            c = e.cost
            lines.append(
                f"| {arm} | {e.rollouts} | {e.attempts} | {c.tool_calls:g} | "
                f"{c.wall_seconds:g} | {c.input_tokens:g} | {c.output_tokens:g} | "
                f"{c.usd:.2f} | {e.note} |"
            )
        if reference is not None:
            lines.append("")
            lines.append(f"Ratios against `{reference}`:")
            lines.append("")
            lines.append("| arm | " + " | ".join(BUDGET_UNITS) + " |")
            lines.append("|---|" + "---:|" * len(BUDGET_UNITS))
            for m in self.match(reference):
                cells = [
                    (f"{m.ratios[u]:.2f}x" if u in m.ratios else "n/a")
                    for u in BUDGET_UNITS
                ]
                lines.append(f"| {m.arm} | " + " | ".join(cells) + " |")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, object]:
        return {
            "entries": [e.to_dict() for e in self.entries],
            "totals": {a: self.total(a).to_dict() for a in self.arms()},
        }


@dataclass(frozen=True)
class BudgetPlan:
    """How a search's rollout budget converts into a baseline's k."""

    search_rollouts: int
    n_tasks: int
    n_replicates: int
    k: int
    rollouts_used: int
    note: str

    @property
    def surplus(self) -> int:
        """Rollouts the baseline spends beyond the search (negative = under-spent)."""
        return self.rollouts_used - self.search_rollouts

    def to_dict(self) -> dict[str, object]:
        return {
            "search_rollouts": self.search_rollouts,
            "n_tasks": self.n_tasks,
            "n_replicates": self.n_replicates,
            "k": self.k,
            "rollouts_used": self.rollouts_used,
            "surplus": self.surplus,
            "note": self.note,
        }


def plan_matched_k(
    search_rollouts: int,
    n_tasks: int,
    n_replicates: int,
    *,
    favor_baseline: bool = True,
) -> BudgetPlan:
    """Convert a search's rollout spend into a per-task k for the baselines.

    ``favor_baseline`` rounds k *up*, so leftover budget is given to the
    baseline rather than quietly withheld. Rounding the other way would shave
    the comparison in the direction of our own claim, which is the failure this
    whole module exists to prevent; the resulting over-spend is recorded as
    ``surplus`` and printed in the report.
    """
    if min(search_rollouts, n_tasks, n_replicates) <= 0:
        raise BaselineError(
            "budget planning needs positive search_rollouts, n_tasks, n_replicates"
        )
    cells = n_tasks * n_replicates
    exact = search_rollouts / cells
    k = max(1, math.ceil(exact) if favor_baseline else int(exact))
    used = k * cells
    if used > search_rollouts:
        direction = f"{used - search_rollouts} more than"
    elif used < search_rollouts:
        direction = f"{search_rollouts - used} fewer than"
    else:
        direction = "exactly"
    rounding = "ceil" if favor_baseline else "floor"
    return BudgetPlan(
        search_rollouts=search_rollouts,
        n_tasks=n_tasks,
        n_replicates=n_replicates,
        k=k,
        rollouts_used=used,
        note=(
            f"k = {rounding}({search_rollouts}/{cells}) = {k}; baseline spends "
            f"{used} rollouts, {direction} the search's {search_rollouts}"
        ),
    )


# --------------------------------------------------------------------------
# selectors
# --------------------------------------------------------------------------

Selector = Callable[[Sequence[Rollout]], Rollout]


def oracle_best(rollouts: Sequence[Rollout]) -> Rollout:
    """Pick the highest-scoring rollout. **Not achievable at deployment time.**

    "Best-of-k" is only a method if something can pick the best without seeing
    the ground-truth score, and on this task nothing can: the score is a
    similarity to a held-out reference deck. So this selector is an *upper
    bound* on parallel sampling, and it must be labelled as one wherever it
    appears. It is still the right thing to compute -- if the evolved candidate
    does not beat oracle best-of-k, the case is closed without further argument;
    if it beats the realizable :class:`ValidatorBest` but not the oracle, the
    honest reading is that the gain is partly a selection gain that better
    test-time selection could also capture.
    """
    if not rollouts:
        raise BaselineError("cannot select from an empty rollout set")
    return max(rollouts, key=lambda r: (r.score.value, -r.cost.tool_calls))


@dataclass(frozen=True)
class ValidatorBest:
    """Realizable selector: pick by validator evidence, never by score.

    This is what a deployed best-of-k could actually do -- run the simulator's
    own validator over each candidate deck and keep the one with the fewest
    unresolved errors. It deliberately has no access to :class:`Score`; the gap
    between this and :func:`oracle_best` measures how much of parallel sampling's
    apparent strength is unreachable in practice, and that gap is a result worth
    reporting rather than a nuisance.

    ``proxy`` returns "higher is better" evidence quality for one rollout. The
    default reads ``Rollout.validator_events``, whose schema is owned by the
    runner workstream; a runner emitting a different shape should pass its own.
    """

    proxy: Callable[[Rollout], float] | None = None
    name: str = "validator_best"

    def __call__(self, rollouts: Sequence[Rollout]) -> Rollout:
        if not rollouts:
            raise BaselineError("cannot select from an empty rollout set")
        proxy = self.proxy or validator_error_proxy
        # Ties break on cost, then on original order: never on score, which
        # would smuggle the oracle back in.
        best_idx = min(
            range(len(rollouts)),
            key=lambda i: (-proxy(rollouts[i]), rollouts[i].cost.tool_calls, i),
        )
        return rollouts[best_idx]


def validator_error_proxy(rollout: Rollout) -> float:
    """Default proxy: negative count of unresolved validator errors.

    Reads defensively because the validator-event schema is not frozen by the
    shared contracts: any of ``severity``/``level``/``kind`` naming an error is
    counted. A rollout that errored out or produced nothing is pushed to the
    bottom, which is the same failures-as-zero stance the scoring uses.
    """
    if rollout.error:
        return float("-inf")
    errors = 0
    for event in rollout.validator_events:
        level = str(
            event.get("severity") or event.get("level") or event.get("kind") or ""
        ).lower()
        if level in ("error", "fatal", "critical"):
            errors += 1
        elif "errors" in event:
            try:
                errors += int(event["errors"])
            except (TypeError, ValueError):
                errors += 1
    return -float(errors)


#: Module-level convenience instance of the realizable selector.
validator_best = ValidatorBest()


# --------------------------------------------------------------------------
# baseline results
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Cell:
    """All rollouts spent on one (task, replicate) pair of a baseline."""

    task: TaskId
    replicate: int
    rollouts: tuple[Rollout, ...]


@dataclass(frozen=True)
class BaselineResult:
    """What one baseline produced, kept at full resolution.

    The raw rollouts are retained per cell so a different selector can be
    applied afterwards without spending another rollout -- which is what makes
    the oracle-vs-validator gap free to report.
    """

    name: str
    arm_label: str
    cells: tuple[Cell, ...]
    budget: BudgetEntry
    selector_name: str
    selector: Selector = oracle_best
    notes: tuple[str, ...] = ()

    def all_rollouts(self) -> list[Rollout]:
        return [r for c in self.cells for r in c.rollouts]

    def arm(
        self, selector: Selector | None = None, *, label: str | None = None
    ) -> ArmScores:
        """Per-task, per-replicate selected scores as an :class:`ArmScores`."""
        chosen = selector or self.selector
        per_task: dict[TaskId, list[float]] = {}
        for cell in self.cells:
            per_task.setdefault(cell.task, []).append(
                chosen(cell.rollouts).score.value
            )
        return ArmScores(
            label=label or self.arm_label,
            per_task={t: tuple(v) for t, v in per_task.items()},
        )

    def selection_gap(self, selector: Selector | None = None) -> float:
        """Mean score the chosen selector leaves on the table versus the oracle.

        Zero means the proxy selector is as good as omniscient on this data;
        large means the parallel-sampling baseline's headline number is an upper
        bound nobody could realize.
        """
        chosen = selector or self.selector
        gaps = [
            oracle_best(c.rollouts).score.value - chosen(c.rollouts).score.value
            for c in self.cells
        ]
        return sum(gaps) / len(gaps) if gaps else 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "arm_label": self.arm_label,
            "selector": self.selector_name,
            "n_cells": len(self.cells),
            "budget": self.budget.to_dict(),
            "notes": list(self.notes),
        }


def _attempts_per_rollout(candidate: Candidate) -> int:
    """Agent attempts inside one rollout: the initial try plus stop-hook retries."""
    return int(candidate.manifest.stop_policy.retries) + 1


def _draw_seed(replicate: int, draw: int) -> int:
    """Distinct, reproducible rollout seed per (replicate, draw).

    Independence across draws is what makes best-of-k *parallel sampling* rather
    than the same rollout counted k times; a cached runner keyed on seed would
    otherwise return k identical rollouts and the baseline would look weak for a
    purely mechanical reason.
    """
    return replicate * 1000 + draw


# --------------------------------------------------------------------------
# the three baselines
# --------------------------------------------------------------------------


@dataclass
class SeedControl:
    """The un-evolved seed adapter at the same seed count, no extra budget.

    The single most important comparison in the whole protocol and the cheapest
    to run. Everything the search claims is a claim *relative to this arm*; the
    scaled baselines only become interesting once this one has been beaten.
    """

    runner: RolloutRunner
    candidate: Candidate
    arm_label: str = "seed adapter (control)"

    def run(
        self,
        tasks: Sequence[TaskId],
        seeds: Sequence[int] = (1, 2, 3),
        *,
        ledger: BudgetLedger | None = None,
        arm_key: str = "control",
    ) -> BaselineResult:
        cells = [
            Cell(
                task=t,
                replicate=s,
                rollouts=(self.runner.run(self.candidate, t, s),),
            )
            for t in tasks
            for s in seeds
        ]
        result_rollouts = [r for c in cells for r in c.rollouts]
        per_rollout = _attempts_per_rollout(self.candidate)
        entry = (ledger or BudgetLedger()).record_rollouts(
            arm_key,
            result_rollouts,
            attempts_per_rollout=per_rollout,
            note=f"seed adapter, {len(seeds)} seeds, no scaling",
        )
        return BaselineResult(
            name="seed_control",
            arm_label=self.arm_label,
            cells=tuple(cells),
            budget=entry,
            selector_name="none (single rollout per cell)",
            selector=oracle_best,
            notes=("no test-time scaling; this is the reference the claim is about",),
        )


@dataclass
class BestOfK:
    """Parallel sampling: k independent rollouts of the seed adapter per cell.

    Reported under both selectors by construction -- see :func:`oracle_best` for
    why a single "best-of-k" number is not an honest object.
    """

    runner: RolloutRunner
    candidate: Candidate
    k: int
    selector: Selector = oracle_best
    selector_name: str = "oracle_best"
    arm_label: str = "seed adapter + best-of-k"

    def run(
        self,
        tasks: Sequence[TaskId],
        replicates: Sequence[int] = (1, 2, 3),
        *,
        ledger: BudgetLedger | None = None,
        arm_key: str = "best_of_k",
    ) -> BaselineResult:
        if self.k < 1:
            raise BaselineError(f"best-of-k needs k >= 1, got {self.k}")
        cells = [
            Cell(
                task=t,
                replicate=rep,
                rollouts=tuple(
                    self.runner.run(self.candidate, t, _draw_seed(rep, j))
                    for j in range(self.k)
                ),
            )
            for t in tasks
            for rep in replicates
        ]
        rollouts = [r for c in cells for r in c.rollouts]
        entry = (ledger or BudgetLedger()).record_rollouts(
            arm_key,
            rollouts,
            attempts_per_rollout=_attempts_per_rollout(self.candidate),
            note=f"k={self.k} independent draws per (task, replicate)",
        )
        return BaselineResult(
            name="best_of_k",
            arm_label=f"{self.arm_label} (k={self.k}, {self.selector_name})",
            cells=tuple(cells),
            budget=entry,
            selector_name=self.selector_name,
            selector=self.selector,
            notes=(
                "oracle selection is an upper bound, not a deployable method",
            ),
        )


@dataclass
class SequentialRefinement:
    """Sequential scaling: ``passes`` in-rollout attempts driven by validator feedback.

    Expressed through the seed adapter's own stop policy rather than a bespoke
    loop, because that policy *is* this system's refinement mechanism (initial
    attempt plus ``retries`` validator-fed retries). Doing it any other way
    would compare the search against a refinement loop the harness does not
    actually have.

    The stop policy caps retries at 6, so more than 7 passes cannot be spent
    honestly this way; that raises rather than silently clamps, because a
    clamped baseline under-spends exactly the budget it was supposed to match.
    """

    runner: RolloutRunner
    candidate: Candidate
    passes: int
    arm_label: str = "seed adapter + sequential refinement"

    def refined_candidate(self) -> Candidate:
        """Seed adapter with its stop policy widened to ``passes`` attempts."""
        if self.passes < 1:
            raise BaselineError(f"sequential refinement needs passes >= 1, got {self.passes}")
        manifest = self.candidate.manifest
        policy = replace(manifest.stop_policy, retries=self.passes - 1)
        try:
            policy.validate()
        except Exception as exc:  # ManifestError; re-raised as a budget failure
            raise BaselineError(
                f"cannot spend {self.passes} refinement passes through the stop "
                f"policy ({exc}); the sequential baseline cannot be budget-matched "
                "at this k without changing the harness, which would unfreeze it"
            ) from exc
        widened = replace(
            manifest, components=dict(manifest.components), stop_policy=policy
        )
        return self.candidate.with_edits({}, manifest=widened)

    def run(
        self,
        tasks: Sequence[TaskId],
        seeds: Sequence[int] = (1, 2, 3),
        *,
        ledger: BudgetLedger | None = None,
        arm_key: str = "sequential_refinement",
    ) -> BaselineResult:
        candidate = self.refined_candidate()
        cells = [
            Cell(task=t, replicate=s, rollouts=(self.runner.run(candidate, t, s),))
            for t in tasks
            for s in seeds
        ]
        rollouts = [r for c in cells for r in c.rollouts]
        entry = (ledger or BudgetLedger()).record_rollouts(
            arm_key,
            rollouts,
            attempts_per_rollout=self.passes,
            note=(
                f"{self.passes} attempts inside each rollout "
                f"(stop_policy.retries={self.passes - 1})"
            ),
        )
        return BaselineResult(
            name="sequential_refinement",
            arm_label=f"{self.arm_label} (passes={self.passes})",
            cells=tuple(cells),
            budget=entry,
            selector_name="none (last attempt wins)",
            selector=oracle_best,
            notes=(
                "matched in attempts, not in rollouts: the compute is inside "
                "one rollout, which is why the ledger reports both units",
            ),
        )


def run_matched_suite(
    runner: RolloutRunner,
    seed_candidate: Candidate,
    tasks: Sequence[TaskId],
    *,
    search_rollouts: int,
    seeds: Sequence[int] = (1, 2, 3),
    ledger: BudgetLedger | None = None,
    include_sequential: bool = True,
    validator_selector: Selector | None = None,
) -> tuple[dict[str, BaselineResult], BudgetLedger, BudgetPlan]:
    """Run control, best-of-k, and sequential refinement at a matched budget.

    Returns the results keyed by baseline name, the ledger they recorded into,
    and the plan that fixed k -- all three, because a reader needs the plan to
    check the ledger and the ledger to check the claim.

    ``include_sequential`` exists only for the case where the planned k exceeds
    what the stop policy can express; the caller is expected to report that the
    sequential arm is missing rather than to omit it quietly.
    """
    ledger = ledger if ledger is not None else BudgetLedger()
    plan = plan_matched_k(search_rollouts, len(tasks), len(seeds))
    results: dict[str, BaselineResult] = {}
    results["seed_control"] = SeedControl(runner, seed_candidate).run(
        tasks, seeds, ledger=ledger
    )
    results["best_of_k_oracle"] = BestOfK(
        runner, seed_candidate, plan.k, selector=oracle_best, selector_name="oracle_best"
    ).run(tasks, seeds, ledger=ledger, arm_key="best_of_k")
    # Reuses the rollouts already spent: the realizable selector costs nothing
    # extra, so there is no excuse for not reporting it alongside the oracle.
    results["best_of_k_validator"] = replace(
        results["best_of_k_oracle"],
        selector=validator_selector or validator_best,
        selector_name="validator_best",
        arm_label=f"seed adapter + best-of-k (k={plan.k}, validator_best)",
    )
    if include_sequential:
        seq = SequentialRefinement(runner, seed_candidate, plan.k)
        results["sequential_refinement"] = seq.run(tasks, seeds, ledger=ledger)
    return results, ledger, plan
