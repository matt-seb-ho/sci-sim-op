"""Amortizing a one-time search cost against a recurring test-time-scaling cost.

arXiv:2607.12227 hands harness evolution and test-time scaling the same budget
and finds evolution behind on Terminal-Bench 2.1 -- 68.2 direct sampling, 72.3
parallel, 69.3 sequential, **67.4 harness evolution** at K=5, pass@1 averaged
over three models, and +0.6 on held-out tasks. Charging the whole search to a
single benchmark run is the right conservative check; `baselines.py` runs it
against us and `report.py` renders the verdict. Nothing in this module softens
that verdict, and the report prints the two next to each other precisely so it
cannot be read as a replacement for it.

What the matched-budget framing does hide is an asymmetry in *when* the compute
is spent. Best-of-k costs k x on every task it will ever see; a harness artifact
is paid for once and is free at inference forever after. So a deployment's
actual question is when the cumulative costs cross:

    cumulative_evolved(n) = one_time_search + n * evolved_per_task
    cumulative_tts(n)     =                   n * tts_per_task

and n* is the smallest n where the first is strictly below the second.

That arithmetic is only meaningful **at equal or better quality**, which two
gates enforce, in this order:

1. **The evolved harness must beat the seed at k=1.** If it does not, there is
   nothing to amortize -- the one-time cost bought nothing, and dividing nothing
   over a longer horizon still yields nothing. Checked first, reported first,
   and on its own sufficient to refuse.
2. **It must match or beat the TTS arm it is being amortized against.** A
   crossover point for a worse system is a category error, so
   :meth:`AmortizationAnalysis.result` returns an explicit refusal rather than a
   number -- the same stance :class:`~harness_evolve.evaluation.stats.BootstrapResult`
   takes when n is too small to license an interval.

The weak point of the argument is stated in the arithmetic rather than left for
a reader to find: a one-time cost is only one-time for as long as the artifact
stays valid. A model upgrade or a simulator release re-opens the search.
``revalidation_interval`` makes that assumption a number, and if the harness has
to be re-searched more often than the crossover arrives, this module reports
that it never amortizes at all.

`docs/NOTES_2607.12227.md` §C states the argument and the condition it depends
on. Stdlib only, by project constraint.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping

from harness_evolve.evaluation.baselines import BaselineResult, BudgetEntry, BudgetLedger
from harness_evolve.evaluation.stats import Comparison
from harness_evolve.types import Cost

__all__ = [
    "AMORTIZED_UNITS",
    "AmortizationAnalysis",
    "AmortizationResult",
    "ArmEconomics",
    "BreakevenHorizon",
    "Crossover",
    "OneTimeCost",
    "QualityPrecondition",
    "crossover_n",
]

#: Units a crossover is reported in. All of them, always: a system can cross in
#: rollouts long before it crosses in USD if its rollouts are more expensive,
#: and reporting only the flattering unit is the failure `BudgetLedger.match`
#: already refuses to commit for budget matching.
AMORTIZED_UNITS: tuple[str, ...] = ("rollouts", "usd", "wall_seconds")

#: Seconds per day, for turning a task count into a calendar horizon.
_SECONDS_PER_DAY = 86_400.0


# ---------------------------------------------------------------------------
# the quality gate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QualityPrecondition:
    """Whether an amortization question may be asked at all.

    Two conditions, and the first is the one the critique actually turns on.
    Amortization divides a fixed cost over a horizon; if the evolved harness
    does not beat its own seed at k=1 there is no numerator, and a crossover
    computed anyway would be a statement about arithmetic rather than about the
    system. So this is a hard gate, not a caveat printed underneath a number.
    """

    beats_seed: bool
    matches_tts: bool
    seed_delta: float
    tts_delta: float
    noise_band: float
    reasons: tuple[str, ...] = ()

    @property
    def holds(self) -> bool:
        return self.beats_seed and self.matches_tts

    @property
    def refusal(self) -> str:
        """Why no crossover may be reported, or ``""`` if one may."""
        if not self.beats_seed:
            return (
                "the evolved harness does not beat the seed adapter at k=1 "
                f"(mean paired delta {self.seed_delta:+.4f}); there is no one-time "
                "gain to amortize, and no horizon makes a system that did not "
                "improve cheaper than one that did"
            )
        if not self.matches_tts:
            return (
                "the evolved harness is behind the test-time-scaling arm "
                f"(mean paired delta {self.tts_delta:+.4f}, noise band "
                f"+-{self.noise_band:.4f}); a crossover point for a worse system "
                "is a category error, not a cheaper option"
            )
        return ""

    @classmethod
    def from_comparisons(
        cls,
        *,
        vs_seed: Comparison,
        vs_tts: Comparison,
        require_no_new_catastrophes: bool = True,
    ) -> "QualityPrecondition":
        """Read both gates off paired comparisons whose treatment is the evolved arm.

        Both comparisons are required rather than optional. Making the seed
        comparison optional would let a caller amortize against a scaling
        baseline while never checking the one thing the whole argument rests on.

        The seed gate is the same rule ``report.decide`` applies to the control
        (more wins than losses, positive mean, no task newly pushed off a
        cliff), so the two cannot disagree. The TTS gate is deliberately weaker:
        *equal* quality passes, because equal quality at lower recurring cost is
        exactly the claim being tested here, whereas the matched-budget verdict
        counts a tie as a failure and continues to.
        """
        band = vs_tts.wlt.noise_band
        reasons: list[str] = []

        seed_wlt = vs_seed.wlt
        beats_seed = (
            vs_seed.mean_delta > 0 and len(seed_wlt.wins) > len(seed_wlt.losses)
        )
        reasons.append(
            f"(1) beats the seed at k=1: {seed_wlt.render()}, mean delta "
            f"{vs_seed.mean_delta:+.4f} -> "
            + ("passes" if beats_seed else "**fails**")
        )
        new_catastrophes = tuple(
            t
            for t in vs_seed.tail_treatment.tasks_with_any_catastrophe
            if t not in vs_seed.tail_baseline.tasks_with_any_catastrophe
        )
        if require_no_new_catastrophes and new_catastrophes:
            beats_seed = False
            reasons.append(
                f"(1) beats the seed at k=1: tasks newly below the catastrophic "
                f"threshold: {list(new_catastrophes)} -> **fails**"
            )

        tts_wlt = vs_tts.wlt
        # "Not worse" rather than "better": behind by more than run-to-run noise,
        # or losing on more tasks than it wins, is worse. Anything else is a tie
        # the recurring-cost difference is allowed to break.
        matches_tts = not (
            vs_tts.mean_delta < -band or len(tts_wlt.losses) > len(tts_wlt.wins)
        )
        reasons.append(
            f"(2) matches or beats `{vs_tts.baseline.label}`: {tts_wlt.render()}, "
            f"mean delta {vs_tts.mean_delta:+.4f} against a noise band of "
            f"+-{band:.4f} -> " + ("passes" if matches_tts else "**fails**")
        )

        return cls(
            beats_seed=beats_seed,
            matches_tts=matches_tts,
            seed_delta=vs_seed.mean_delta,
            tts_delta=vs_tts.mean_delta,
            noise_band=band,
            reasons=tuple(reasons),
        )

    def render(self) -> str:
        lines = ["Quality precondition (checked before any cost arithmetic):", ""]
        lines += [f"- {r}" for r in self.reasons]
        if not self.holds:
            lines += ["", f"**No crossover is defined**: {self.refusal}."]
        return "\n".join(lines)

    def to_dict(self) -> dict[str, object]:
        return {
            "holds": self.holds,
            "beats_seed": self.beats_seed,
            "matches_tts": self.matches_tts,
            "seed_delta": self.seed_delta,
            "tts_delta": self.tts_delta,
            "noise_band": self.noise_band,
            "reasons": list(self.reasons),
            "refusal": self.refusal,
        }


# ---------------------------------------------------------------------------
# costs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OneTimeCost:
    """What the search spent once and will not spend again.

    Held separately from :class:`ArmEconomics` because the whole argument is
    that these two quantities have different shapes: this one is a constant, the
    other is a slope.
    """

    label: str
    rollouts: float
    usd: float = 0.0
    wall_seconds: float = 0.0

    def unit(self, name: str) -> float:
        if name == "rollouts":
            return float(self.rollouts)
        if name == "usd":
            return float(self.usd)
        if name == "wall_seconds":
            return float(self.wall_seconds)
        raise KeyError(f"{name!r} is not an amortizable unit; expected {AMORTIZED_UNITS}")

    @classmethod
    def from_entry(cls, entry: BudgetEntry, *, label: str | None = None) -> "OneTimeCost":
        """Read the one-time cost off the ledger entry the search actually recorded."""
        return cls(
            label=label or entry.arm,
            rollouts=float(entry.rollouts),
            usd=entry.cost.usd,
            wall_seconds=entry.cost.wall_seconds,
        )

    @classmethod
    def from_ledger(cls, ledger: BudgetLedger, arm: str = "search") -> "OneTimeCost":
        """Read the one-time cost off a :class:`BudgetLedger`.

        Raises through :meth:`BudgetLedger.total` when the arm recorded nothing,
        which is the correct outcome: an unrecorded search cost would amortize to
        an instant crossover for free.
        """
        return cls.from_entry(ledger.total(arm))

    def to_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "rollouts": self.rollouts,
            "usd": self.usd,
            "wall_seconds": self.wall_seconds,
        }


@dataclass(frozen=True)
class ArmEconomics:
    """What one *deployed* arm costs per task-solution, recurring forever.

    ``k`` is carried because it is the whole recurring-cost story: the evolved
    arm deploys at k=1 and the parallel arm at its matched k, and the ratio
    between their per-task costs is roughly that k unless per-rollout costs also
    differ. They can: a cheatsheet that names the file the agent needs removes
    the exploratory reads it would otherwise spend finding it, so the evolved
    arm's rollouts can be individually cheaper as well as fewer. That widens the
    per-task gap and pulls the crossover in, which is why per-rollout cost is
    measured here rather than assumed equal.
    """

    label: str
    k: int
    rollouts_per_task: float
    usd_per_task: float = 0.0
    wall_seconds_per_task: float = 0.0

    def unit(self, name: str) -> float:
        if name == "rollouts":
            return float(self.rollouts_per_task)
        if name == "usd":
            return float(self.usd_per_task)
        if name == "wall_seconds":
            return float(self.wall_seconds_per_task)
        raise KeyError(f"{name!r} is not an amortizable unit; expected {AMORTIZED_UNITS}")

    @classmethod
    def from_measured(
        cls,
        label: str,
        *,
        k: int,
        rollouts: float,
        cost: Cost,
        task_solutions: int,
    ) -> "ArmEconomics":
        """Divide a measured total by the task-solutions it produced.

        Measured rather than estimated, for the reason
        :meth:`BudgetLedger.record_rollouts` gives: an estimated per-task cost
        would be exactly as trustworthy as the assertion it replaces, and this
        one sets the slope that decides the crossover.
        """
        if task_solutions <= 0:
            raise ValueError("task_solutions must be positive to derive a per-task cost")
        n = float(task_solutions)
        return cls(
            label=label,
            k=k,
            rollouts_per_task=rollouts / n,
            usd_per_task=cost.usd / n,
            wall_seconds_per_task=cost.wall_seconds / n,
        )

    @classmethod
    def from_result(cls, result: BaselineResult, *, k: int, label: str | None = None) -> "ArmEconomics":
        """Per-task economics of a baseline arm, from the cells it actually ran.

        One cell is one task-solution: k draws collapsed by a selector into the
        single answer a deployment would ship.
        """
        return cls.from_measured(
            label or result.arm_label,
            k=k,
            rollouts=float(result.budget.rollouts),
            cost=result.budget.cost,
            task_solutions=len(result.cells),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "k": self.k,
            "rollouts_per_task": self.rollouts_per_task,
            "usd_per_task": self.usd_per_task,
            "wall_seconds_per_task": self.wall_seconds_per_task,
        }


# ---------------------------------------------------------------------------
# the crossover
# ---------------------------------------------------------------------------


def crossover_n(one_time: float, evolved_per_task: float, tts_per_task: float) -> int | None:
    """Smallest ``n >= 1`` with ``one_time + n*evolved < n*tts``; ``None`` if none exists.

    Strict inequality on purpose. At the exact tie point the two arms have spent
    the same amount and the evolved one has additionally consumed a search; the
    horizon at which it is *ahead* is one task later, and rounding that away
    would shave the arithmetic in the direction of our own claim.
    """
    savings = tts_per_task - evolved_per_task
    if not math.isfinite(savings) or savings <= 0:
        return None
    return max(1, math.floor(one_time / savings) + 1)


@dataclass(frozen=True)
class Crossover:
    """When the evolved arm's cumulative spend passes below the TTS arm's, in one unit."""

    unit: str
    one_time: float
    evolved_per_task: float
    tts_per_task: float
    n_task_solutions: int | None
    revalidation_interval: int | None = None

    @property
    def savings_per_task(self) -> float:
        """Recurring cost the evolved arm avoids on every task-solution."""
        return self.tts_per_task - self.evolved_per_task

    @property
    def never(self) -> bool:
        """True when no horizon is long enough, because the slope does not favour us."""
        return self.n_task_solutions is None

    @property
    def immediate(self) -> bool:
        """True when the evolved arm is ahead from the very first task-solution.

        The interesting case rather than a degenerate one: it is what a
        mechanism with no search cost of its own looks like on this axis (see
        `zero_marginal.py`), and it is also reachable when the artifact is cheap
        to find relative to a single task's scaling cost.
        """
        return self.n_task_solutions == 1

    @property
    def outlives_revalidation(self) -> bool:
        """Does the crossover arrive before the artifact must be re-searched?

        The one assumption amortization cannot check for itself. A model upgrade
        or a simulator release invalidates the artifact and re-opens the search,
        which resets the constant term; if that happens more often than n*
        task-solutions, the crossing point is never reached in practice however
        good the arithmetic looks.
        """
        if self.revalidation_interval is None:
            return True
        if self.n_task_solutions is None:
            return False
        return self.n_task_solutions <= self.revalidation_interval

    def cumulative_evolved(self, n: int) -> float:
        return self.one_time + n * self.evolved_per_task

    def cumulative_tts(self, n: int) -> float:
        return n * self.tts_per_task

    def savings_at(self, n: int) -> float:
        """TTS spend minus evolved spend after ``n`` task-solutions; negative = behind."""
        return self.cumulative_tts(n) - self.cumulative_evolved(n)

    def render(self) -> str:
        if self.never:
            return (
                f"{self.unit}: **never crosses** -- the evolved arm costs "
                f"{self.evolved_per_task:g} per task against the scaling arm's "
                f"{self.tts_per_task:g}, so the recurring cost is not lower and "
                "the one-time cost is never recovered"
            )
        n = self.n_task_solutions
        head = (
            f"{self.unit}: crosses at **n = {n}** task-solution(s) "
            f"(one-time {self.one_time:g}, then {self.evolved_per_task:g}/task "
            f"vs {self.tts_per_task:g}/task, saving {self.savings_per_task:g}/task)"
        )
        if self.immediate:
            head += " -- **immediate**: ahead from the first task"
        if not self.outlives_revalidation:
            head += (
                f" -- but the artifact must be re-searched every "
                f"{self.revalidation_interval} task-solution(s), so **this "
                "crossover is never reached in practice**"
            )
        return head

    def to_dict(self) -> dict[str, object]:
        return {
            "unit": self.unit,
            "one_time": self.one_time,
            "evolved_per_task": self.evolved_per_task,
            "tts_per_task": self.tts_per_task,
            "n_task_solutions": self.n_task_solutions,
            "savings_per_task": self.savings_per_task,
            "never": self.never,
            "immediate": self.immediate,
            "revalidation_interval": self.revalidation_interval,
            "outlives_revalidation": self.outlives_revalidation,
        }


@dataclass(frozen=True)
class BreakevenHorizon:
    """The crossover put on a calendar, which is what a person plans against.

    A count of task-solutions is not a plannable quantity; "eleven weeks, of
    which the first two are the search" is. The up-front term is kept separate
    because it is a delay before the first deployed task rather than something
    the horizon absorbs -- a 16-37 hour search is a scheduling fact on its own.
    """

    unit: str
    n_task_solutions: int | None
    task_solutions_per_day: float
    upfront_days: float

    @property
    def days_after_deployment(self) -> float | None:
        if self.n_task_solutions is None or self.task_solutions_per_day <= 0:
            return None
        return self.n_task_solutions / self.task_solutions_per_day

    @property
    def total_days(self) -> float | None:
        after = self.days_after_deployment
        return None if after is None else self.upfront_days + after

    def render(self) -> str:
        if self.n_task_solutions is None:
            return "breakeven horizon: none -- the arms never cross"
        if self.task_solutions_per_day <= 0:
            return (
                f"breakeven horizon: {self.n_task_solutions} task-solution(s) in "
                f"`{self.unit}`; no deployment rate supplied, so this cannot be "
                "put on a calendar"
            )
        after = self.days_after_deployment or 0.0
        # Sub-day searches print in hours: a 16-37 hour search rounded to "0.0
        # days" reads as free, and the delay before the first deployed task is
        # exactly the part a schedule has to absorb.
        upfront = (
            f"{self.upfront_days * 24.0:.1f} hour(s)"
            if self.upfront_days < 1.0
            else f"{self.upfront_days:.1f} day(s)"
        )
        return (
            f"breakeven horizon: **{after:.1f} day(s)** of deployment at "
            f"{self.task_solutions_per_day:g} task-solution(s)/day, after "
            f"{upfront} of search -- {self.total_days:.1f} day(s) from a "
            "standing start"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "unit": self.unit,
            "n_task_solutions": self.n_task_solutions,
            "task_solutions_per_day": self.task_solutions_per_day,
            "upfront_days": self.upfront_days,
            "days_after_deployment": self.days_after_deployment,
            "total_days": self.total_days,
        }


@dataclass(frozen=True)
class AmortizationResult:
    """Either a crossover schedule or an explicit refusal to produce one.

    Modelled on :class:`~harness_evolve.evaluation.stats.BootstrapResult`: the
    refusal is a first-class value that renders as prominently as a number
    would, because the situation it describes -- an evolved arm that did not
    earn its search -- is the one arXiv:2607.12227 reports as typical.
    """

    defined: bool
    precondition: QualityPrecondition
    refusal: str = ""
    crossovers: Mapping[str, Crossover] = field(default_factory=dict)
    horizon: BreakevenHorizon | None = None

    def crossover(self, unit: str = "rollouts") -> Crossover:
        if not self.defined:
            raise ValueError(
                f"no crossover is defined: {self.refusal}. Ask `defined` before "
                "asking for a number."
            )
        return self.crossovers[unit]

    def to_dict(self) -> dict[str, object]:
        return {
            "defined": self.defined,
            "refusal": self.refusal,
            "precondition": self.precondition.to_dict(),
            "crossovers": {u: c.to_dict() for u, c in self.crossovers.items()},
            "horizon": self.horizon.to_dict() if self.horizon else None,
        }


@dataclass(frozen=True)
class AmortizationAnalysis:
    """After how many task-solutions does a one-time search beat recurring scaling?

    Answers that question only when the evolved arm has earned the right to be
    asked it -- see :class:`QualityPrecondition`. The analysis holds no
    statistics of its own; the quality gate arrives already computed, so the
    numbers here are exactly the numbers the protocol produced.
    """

    evolved: ArmEconomics
    tts: ArmEconomics
    one_time: OneTimeCost
    precondition: QualityPrecondition
    #: Task-solutions between forced re-searches (model upgrade, simulator
    #: release). ``None`` asserts the artifact stays valid indefinitely, which
    #: is an assumption and is labelled as one in the rendered output.
    revalidation_interval: int | None = None
    #: Deployment throughput, used only to turn n* into a calendar horizon.
    task_solutions_per_day: float = 0.0
    #: Wall-clock the search occupied, as a delay before the first deployed task.
    #: Defaults to the one-time cost's own wall seconds.
    search_days: float | None = None
    horizon_unit: str = "rollouts"

    def _upfront_days(self) -> float:
        if self.search_days is not None:
            return self.search_days
        return self.one_time.wall_seconds / _SECONDS_PER_DAY

    def result(self) -> AmortizationResult:
        """Compute the crossover in every unit, or refuse and say why."""
        if not self.precondition.holds:
            return AmortizationResult(
                defined=False,
                precondition=self.precondition,
                refusal=self.precondition.refusal,
            )
        crossovers = {
            unit: Crossover(
                unit=unit,
                one_time=self.one_time.unit(unit),
                evolved_per_task=self.evolved.unit(unit),
                tts_per_task=self.tts.unit(unit),
                n_task_solutions=crossover_n(
                    self.one_time.unit(unit),
                    self.evolved.unit(unit),
                    self.tts.unit(unit),
                ),
                revalidation_interval=self.revalidation_interval,
            )
            for unit in AMORTIZED_UNITS
        }
        pivot = crossovers[self.horizon_unit]
        horizon = BreakevenHorizon(
            unit=self.horizon_unit,
            n_task_solutions=pivot.n_task_solutions,
            task_solutions_per_day=self.task_solutions_per_day,
            upfront_days=self._upfront_days(),
        )
        return AmortizationResult(
            defined=True,
            precondition=self.precondition,
            crossovers=crossovers,
            horizon=horizon,
        )

    def render(self) -> str:
        """Markdown block: the gate first, then the arithmetic it licenses."""
        res = self.result()
        lines = [
            "Test-time scaling is a **recurring** per-task cost; a harness "
            "artifact is a **one-time** cost that is free at inference "
            "thereafter. The matched-budget comparison charges the whole search "
            "to one benchmark run, which is the right conservative check and is "
            "the verdict above. This section asks the different question a "
            "deployment asks, and it is only askable if the verdict allowed it.",
            "",
            self.precondition.render(),
            "",
        ]
        if not res.defined:
            return "\n".join(lines).rstrip()
        lines += [
            "| arm | k | rollouts/task | USD/task | wall s/task |",
            "|---|---:|---:|---:|---:|",
            f"| {self.evolved.label} (deployed) | {self.evolved.k} | "
            f"{self.evolved.rollouts_per_task:g} | {self.evolved.usd_per_task:.4f} | "
            f"{self.evolved.wall_seconds_per_task:g} |",
            f"| {self.tts.label} | {self.tts.k} | {self.tts.rollouts_per_task:g} | "
            f"{self.tts.usd_per_task:.4f} | {self.tts.wall_seconds_per_task:g} |",
            "",
            f"One-time cost (`{self.one_time.label}`): "
            f"{self.one_time.rollouts:g} rollouts, ${self.one_time.usd:.2f}, "
            f"{self.one_time.wall_seconds / 3600.0:.1f} wall hours.",
            "",
            "Crossover -- cumulative evolved cost below cumulative scaling cost, "
            "at equal or better quality:",
            "",
        ]
        lines += [f"- {res.crossovers[u].render()}" for u in AMORTIZED_UNITS]
        if res.horizon is not None:
            lines.append(f"- {res.horizon.render()}")
        if self.revalidation_interval is None:
            lines += [
                "",
                "This assumes the artifact stays valid indefinitely. It does not: "
                "a base-model upgrade or a simulator release re-opens the search "
                "and resets the one-time term. Set `revalidation_interval` to the "
                "expected artifact lifetime in task-solutions to see whether the "
                "crossover is reached before then.",
            ]
        else:
            stale = [
                u for u in AMORTIZED_UNITS
                if not res.crossovers[u].outlives_revalidation
            ]
            lines += [
                "",
                f"Artifact lifetime: {self.revalidation_interval} task-solution(s) "
                "between forced re-searches."
                + (
                    f" The crossover is **not reached within it** in: {stale}."
                    if stale
                    else " Every crossover above is reached within it."
                ),
            ]
        return "\n".join(lines)

    def to_dict(self) -> dict[str, object]:
        return {
            "evolved": self.evolved.to_dict(),
            "tts": self.tts.to_dict(),
            "one_time": self.one_time.to_dict(),
            "revalidation_interval": self.revalidation_interval,
            "task_solutions_per_day": self.task_solutions_per_day,
            "horizon_unit": self.horizon_unit,
            "result": self.result().to_dict(),
        }
