"""Does the harness still help once you also scale test-time compute?

arXiv:2607.12227 compares harness evolution *against* test-time scaling, as
alternatives competing for one budget, and finds evolution losing. That is a
fair question and its answer stands. But it is not the question a deployment
faces, because **the two compose**: a deployed system runs the best harness it
has *and* whatever inference budget it can afford. Nobody runs a deliberately
worse harness in order to afford more samples.

So the question that decides whether harness work is worth doing is:

    does the evolved harness still help when test-time scaling is applied to
    **both** arms?

This module runs that as a factorial: ``{seed, evolved} x {k = 1 ... K}``, at a
matched total budget, and reports the **interaction**.

## Why the interaction is the whole point

The two mechanisms fix different error classes, and the grid separates them.

* **Test-time scaling fixes stochastic failure.** Draw k samples and keep the
  best; this helps exactly when the agent *sometimes* gets it right. The gain
  shrinks as the per-sample success probability approaches 0 or 1.
* **A harness fixes systematic failure.** When the agent does not know the
  simulator's contract, every sample makes the same mistake. Resampling a
  confident, uniform error yields k copies of it, and no selector — oracle or
  otherwise — can pick a good one out of a set that contains none.

That predicts something falsifiable. If the harness gain **persists at large k**,
it is repairing errors resampling cannot reach, and harness work buys something
inference budget cannot. If the gain **collapses as k grows**, the harness was
only ever making a stochastic failure a bit less likely, and the honest
conclusion is that the compute was better spent on samples.

Either outcome is publishable and the second is a cleaner null than "evolution
lost a matched comparison", because it says *why*.

## What this does not do

It does not rescue a harness that fails the matched comparison at k=1. If the
evolved arm does not beat the seed at k=1, there is no gain whose persistence
could be measured, and :meth:`CompositionGrid.analyse` says so rather than
fitting a trend through noise.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Callable, Literal, Mapping, Sequence

from harness_evolve.evaluation.stats import ArmScores
from harness_evolve.types import Rollout, TaskId

#: How a harness gain behaves as test-time compute grows.
Persistence = Literal["persists", "decays", "vanishes", "undetermined"]


@dataclass(frozen=True)
class Cell:
    """One (harness, k) point of the factorial."""

    harness: str
    k: int
    scores: ArmScores
    rollouts: int

    @property
    def mean(self) -> float:
        vals = [v for t in self.scores.tasks for v in self.scores.values(t)]
        return statistics.mean(vals) if vals else 0.0

    @property
    def zero_rate(self) -> float:
        vals = [v for t in self.scores.tasks for v in self.scores.values(t)]
        if not vals:
            return 0.0
        return sum(1 for v in vals if v <= 1e-9) / len(vals)


@dataclass
class CompositionResult:
    """The grid, the interaction, and what it licenses saying."""

    cells: dict[tuple[str, int], Cell] = field(default_factory=dict)
    ks: tuple[int, ...] = ()
    seed_label: str = "seed"
    evolved_label: str = "evolved"
    notes: list[str] = field(default_factory=list)

    # -- the quantity of interest -----------------------------------------
    def gain_at(self, k: int) -> float | None:
        """Evolved minus seed at one k, or ``None`` if the cell is missing."""
        s = self.cells.get((self.seed_label, k))
        e = self.cells.get((self.evolved_label, k))
        if s is None or e is None:
            return None
        return e.mean - s.mean

    def gains(self) -> dict[int, float]:
        return {k: g for k in self.ks if (g := self.gain_at(k)) is not None}

    @property
    def retention(self) -> float | None:
        """Fraction of the k=1 harness gain still present at the largest k.

        The headline number. Above 1.0 means scaling and the harness *amplify*
        each other, which is possible: a harness that makes a task solvable at
        all gives resampling something to work with.
        """
        g = self.gains()
        if not g or 1 not in g:
            return None
        base = g[1]
        if abs(base) < 1e-9:
            return None
        return g[max(g)] / base

    def classify(
        self, *, persist_floor: float = 0.6, vanish_ceiling: float = 0.15
    ) -> Persistence:
        """Does the harness gain survive test-time scaling?

        Thresholds are conventions, not measurements, and are stated in the
        report so a reader can disagree with them rather than having to
        reverse-engineer them.
        """
        g = self.gains()
        if len(g) < 2 or 1 not in g:
            return "undetermined"
        if g[1] <= 0:
            return "undetermined"
        r = self.retention
        if r is None:
            return "undetermined"
        if r >= persist_floor:
            return "persists"
        if r <= vanish_ceiling:
            return "vanishes"
        return "decays"

    # -- error-class attribution ------------------------------------------
    def systematic_tasks(self, k: int) -> list[TaskId]:
        """Tasks the seed harness fails at *every* draw, at this k.

        A task the seed never solves in k independent attempts is failing
        systematically rather than stochastically: the model is making the same
        mistake each time, which is what a harness is for and what resampling
        cannot reach.
        """
        cell = self.cells.get((self.seed_label, k))
        if cell is None:
            return []
        return [t for t in cell.scores.tasks
                if max(cell.scores.values(t)) <= 1e-9]

    def systematic_rescues(self, k: int) -> list[TaskId]:
        """Systematically-failing tasks the evolved harness rescues at this k.

        The cleanest evidence available that the harness is doing something
        resampling cannot: the seed failed every attempt, the evolved arm did not.
        """
        evolved = self.cells.get((self.evolved_label, k))
        if evolved is None:
            return []
        return [t for t in self.systematic_tasks(k)
                if t in evolved.scores.per_task
                and max(evolved.scores.values(t)) > 1e-9]

    # -- reporting ---------------------------------------------------------
    def budget_matched(self, tolerance: float = 0.10) -> bool:
        """Do the two harnesses spend the same at each k?

        They must, or the grid measures budget rather than harness. Compared
        within a k, not across: comparing across k is the whole point.
        """
        for k in self.ks:
            s = self.cells.get((self.seed_label, k))
            e = self.cells.get((self.evolved_label, k))
            if s is None or e is None or not s.rollouts:
                continue
            if abs(e.rollouts / s.rollouts - 1.0) > tolerance:
                return False
        return True

    def render(self) -> str:
        lines = [
            "## Does the harness still help under test-time scaling?",
            "",
            "The two compose, so the question a deployment faces is not "
            "harness *or* scaling but whether the harness still pays once both "
            "arms get the same inference budget.",
            "",
            "| k | seed | evolved | gain | seed zero-rate | evolved zero-rate |",
            "|---:|---:|---:|---:|---:|---:|",
        ]
        for k in self.ks:
            s = self.cells.get((self.seed_label, k))
            e = self.cells.get((self.evolved_label, k))
            if s is None or e is None:
                lines.append(f"| {k} | — | — | — | — | — |")
                continue
            lines.append(
                f"| {k} | {s.mean:.4f} | {e.mean:.4f} | {e.mean - s.mean:+.4f} "
                f"| {s.zero_rate:.3f} | {e.zero_rate:.3f} |"
            )

        verdict = self.classify()
        r = self.retention
        lines += ["", f"**Gain retention at k={max(self.ks) if self.ks else '?'}:** "
                      + (f"{r:.0%}" if r is not None else "undetermined")
                      + f" → `{verdict}`", ""]

        explanation = {
            "persists": (
                "The harness gain survives test-time scaling, so it is repairing "
                "errors resampling cannot reach — the systematic kind, where "
                "every draw makes the same mistake. Harness work buys something "
                "inference budget cannot."
            ),
            "decays": (
                "The gain shrinks as sampling grows: the harness and resampling "
                "are partly fixing the same failures. Whether the harness is "
                "worth its search cost depends on the inference budget the "
                "deployment can actually afford."
            ),
            "vanishes": (
                "Test-time scaling absorbs the harness gain entirely. The honest "
                "conclusion is that the compute spent searching for a harness "
                "would have bought more by being spent on samples."
            ),
            "undetermined": (
                "There is no k=1 gain whose persistence could be measured. The "
                "matched comparison at k=1 has to be won before this question "
                "means anything."
            ),
        }[verdict]
        lines += [explanation, ""]

        if self.ks:
            k_max = max(self.ks)
            sysfail = self.systematic_tasks(k_max)
            rescued = self.systematic_rescues(k_max)
            lines += [
                f"**Systematic failures at k={k_max}:** {len(sysfail)} task(s) the "
                f"seed harness fails on *every* draw"
                + (f" ({', '.join(sysfail)})" if sysfail else "")
                + ".",
                "",
                f"**Of those, the evolved harness rescues {len(rescued)}**"
                + (f": {', '.join(rescued)}" if rescued else "")
                + ". A task the seed never solves in "
                f"{k_max} independent attempts is not failing by chance, so a "
                "rescue there is the cleanest available evidence that the "
                "harness reaches something resampling does not.",
                "",
            ]

        if not self.budget_matched():
            lines.append(
                "**WARNING:** the two harnesses did not spend equally at every k, "
                "so this grid partly measures budget rather than harness."
            )
        lines += self.notes
        return "\n".join(lines)


@dataclass
class CompositionGrid:
    """Run ``{seed, evolved} x {k}`` and analyse the interaction.

    ``select`` is the selector applied within a k-sample draw. It matters
    enormously and is injected rather than assumed: with an oracle it is an
    unrealizable upper bound, and with the simulator's validator it is what a
    deployment could actually do. Report both — the gap between them is how much
    of test-time scaling's advantage is unavailable in a domain with no cheap
    way to tell a good artifact from a bad one.
    """

    ks: tuple[int, ...] = (1, 3, 5)
    seed_label: str = "seed"
    evolved_label: str = "evolved"

    def run(
        self,
        *,
        draw: Callable[[str, TaskId, int, int], Rollout],
        tasks: Sequence[TaskId],
        replicates: Sequence[int] = (1, 2, 3),
        select: Callable[[Sequence[Rollout]], Rollout] | None = None,
    ) -> CompositionResult:
        """Populate the grid.

        ``draw(harness, task, replicate, draw_index)`` returns one rollout. The
        caller owns what a "harness" means, so this works against a mock, a
        cached corpus, or the real runner without knowing which.
        """
        chooser = select or _best_by_score
        result = CompositionResult(
            ks=tuple(sorted(self.ks)),
            seed_label=self.seed_label,
            evolved_label=self.evolved_label,
        )
        for harness in (self.seed_label, self.evolved_label):
            for k in result.ks:
                per_task: dict[TaskId, list[float]] = {}
                spent = 0
                for task in tasks:
                    for rep in replicates:
                        draws = [draw(harness, task, rep, i) for i in range(k)]
                        spent += len(draws)
                        per_task.setdefault(task, []).append(
                            chooser(draws).score.value
                        )
                result.cells[(harness, k)] = Cell(
                    harness=harness, k=k, rollouts=spent,
                    scores=ArmScores(
                        label=f"{harness} k={k}",
                        per_task={t: tuple(v) for t, v in per_task.items()},
                    ),
                )
        return result


def _best_by_score(draws: Sequence[Rollout]) -> Rollout:
    """Oracle selection: an upper bound, not something a deployment can do."""
    return max(draws, key=lambda r: r.score.value)


def validator_selector(
    draws: Sequence[Rollout],
) -> Rollout:
    """Pick the first draw whose validator raised no error; else the first.

    What a real system can actually do, and much weaker than the oracle: it
    separates artifacts that load from artifacts that do not, and says nothing
    about whether a loading artifact is the *right* one. In a domain where
    scoring requires the ground truth you are trying to produce, this gap is not
    an implementation shortcoming — it is the problem.
    """
    for r in draws:
        errors = [
            ev for ev in r.validator_events
            if str(ev.get("severity", "error")).lower() == "error"
            or ev.get("decision") == "block"
        ]
        if not errors and r.score.status in ("success", "ok"):
            return r
    return draws[0]
