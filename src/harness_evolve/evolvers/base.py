"""The evolution strategy, made pluggable — and the budget that makes arms comparable.

Until this package existed there was exactly one evolution strategy, hardcoded
inside :mod:`harness_evolve.core.search`: Pareto parent selection, gated
screening, regression gate. That is a defensible strategy, but it is one point
in a space, and a point that cannot be compared to its neighbours is a claim
without a control. arXiv:2607.12227 reports that automatic harness evolution
frequently fails to beat trivial baselines, and that the failures are usually
invisible because the arms were never run under one protocol at one budget. The
only honest response is to be able to run several methods against each other.

Three things in here are load-bearing rather than convenient.

**Budget is in rollouts, and it is enforced by construction.** Not a counter a
method promises to respect: :class:`BudgetedRunner` wraps the runner an evolver
was handed and refuses the rollout that would cross the cap. A method cannot
overspend without going around its own runner, and there is no other way to
reach the simulator. Spend is recorded for *every* rollout — including those
spent on candidates that were screened out, rejected, or thrown away — because
a method that counts only its successes understates its budget, which is
precisely how "harness evolution beat the baseline" comes to mean "harness
evolution had more compute".

**Selection is one rule for every method.** Each evolver returns
``archive.best()``: the highest-mean entry among those it accepted. Methods
differ in *which candidates they put in the archive and on which slice they
scored them*, not in how the winner is read off. That keeps the difference
between arms located in the strategy rather than in the reporting.

**The protocol does not mention a proposer.** Random search does not use one;
neither does the component-cycling arm. A protocol that required one would make
the control impossible to express, and the control is the most important arm.
"""

from __future__ import annotations

import itertools
import statistics
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Iterator, Mapping, Protocol, Sequence, runtime_checkable

from harness_evolve.core.archive import Archive, ArchiveEntry
from harness_evolve.core.candidate import Candidate, CandidateError, Prediction
from harness_evolve.proposers.edits import Edit, EditError, Op, apply_edit
from harness_evolve.runners.base import RolloutRunner, RunnerCapabilities
from harness_evolve.types import Cost, Rollout, TaskId

#: Scores this far apart are the same score. Selection and strict-improvement
#: tests both need a floor, or floating-point noise decides the comparison.
EPSILON = 1e-9


# ---------------------------------------------------------------------------
# budget
# ---------------------------------------------------------------------------


class BudgetExhausted(RuntimeError):
    """A rollout was requested past the cap.

    Raised rather than returning a sentinel: a method that ignores a "no" and
    keeps going produces an unmatched comparison, and an unmatched comparison
    is worse than no comparison. Every evolver here catches it at its own loop
    boundary and returns what it has.
    """


@dataclass(frozen=True)
class SpendEntry:
    """Rollouts and cost charged under one label."""

    note: str
    rollouts: int
    cost: Cost


@dataclass
class RolloutBudget:
    """A hard cap in rollouts, plus the record of where they went.

    Rollouts are the unit because rollouts are the cost: ~25 minutes and a
    container per task-run, against ~17 search tasks. Wall-clock and USD are
    carried alongside because they are what a reader checks, but they are
    *derived* from the rollouts and cannot be the thing that is matched — a
    method whose candidates happen to be cheaper per rollout would otherwise be
    allowed more of them.
    """

    cap: int
    spent: int = 0
    cost: Cost = field(default_factory=Cost)
    rollouts_by_note: dict[str, int] = field(default_factory=dict)
    cost_by_note: dict[str, Cost] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.cap < 0:
            raise ValueError("a rollout budget cannot be negative")

    @property
    def remaining(self) -> int:
        return max(0, self.cap - self.spent)

    @property
    def exhausted(self) -> bool:
        return self.remaining <= 0

    def can_afford(self, n: int = 1) -> bool:
        """Would ``n`` more rollouts fit?"""
        return n <= self.remaining

    def charge(self, n: int = 1, *, note: str = "") -> None:
        """Reserve ``n`` rollouts, or refuse.

        Called *before* the rollout runs, so the cap bounds what is executed
        rather than what is reported.
        """
        if n < 0:
            raise ValueError("cannot charge a negative number of rollouts")
        if not self.can_afford(n):
            raise BudgetExhausted(
                f"{n} rollout(s) requested with {self.remaining} of {self.cap} "
                f"left (note={note!r})"
            )
        self.spent += n
        self.rollouts_by_note[note] = self.rollouts_by_note.get(note, 0) + n

    def attribute(self, cost: Cost, *, note: str = "") -> None:
        """Record what a charged rollout actually cost, once it is known."""
        self.cost = self.cost + cost
        self.cost_by_note[note] = self.cost_by_note.get(note, Cost()) + cost

    def breakdown(self) -> tuple[SpendEntry, ...]:
        """Spend per label, in first-charged order."""
        return tuple(
            SpendEntry(note, n, self.cost_by_note.get(note, Cost()))
            for note, n in self.rollouts_by_note.items()
        )

    def summary(self) -> str:
        parts = [f"{self.spent}/{self.cap} rollouts"]
        for e in self.breakdown():
            parts.append(f"{e.note or 'unlabelled'}={e.rollouts}")
        return ", ".join(parts)


class BudgetedRunner(RolloutRunner):
    """A runner that charges a :class:`RolloutBudget` before every rollout.

    Enforcement lives here rather than in the evolvers because there is exactly
    one place a rollout can happen, and putting the check anywhere else makes it
    something each new method has to remember. ``run_many`` is overridden rather
    than inherited so that an inner runner with its own batched implementation
    still gets charged per rollout: a batch that is refused half-way through has
    still spent what it spent, and the ledger says so.
    """

    def __init__(
        self, inner: RolloutRunner, budget: RolloutBudget, *, note: str = ""
    ) -> None:
        self.inner = inner
        self.budget = budget
        self.note = note

    @property
    def capabilities(self) -> RunnerCapabilities:
        return self.inner.capabilities

    def for_phase(self, note: str) -> "BudgetedRunner":
        """A view on the same budget that labels its spend differently.

        Phase labels are what make "SkillOpt accepted on validation rollouts,
        not on the rollouts that produced the edit" checkable after the fact
        rather than asserted in a docstring.
        """
        return BudgetedRunner(self.inner, self.budget, note=note)

    def run(self, candidate: Candidate, task: TaskId, seed: int = 1) -> Rollout:
        self.budget.charge(1, note=self.note)
        rollout = self.inner.run(candidate, task, seed)
        self.budget.attribute(rollout.cost, note=self.note)
        return rollout

    def run_many(
        self,
        candidate: Candidate,
        tasks: Sequence[TaskId],
        seeds: Sequence[int] = (1,),
    ) -> list[Rollout]:
        return [self.run(candidate, t, s) for s in seeds for t in tasks]

    def preflight(self) -> list[str]:
        return self.inner.preflight()


def budgeted(runner: RolloutRunner, budget: RolloutBudget) -> BudgetedRunner:
    """Wrap ``runner`` so it charges ``budget``. Idempotent.

    Idempotence matters because :mod:`~harness_evolve.evolvers.compare` hands
    every arm an already-budgeted runner while a caller running one evolver
    directly will not — and double-wrapping would double-charge, which reads as
    a method spending twice what it did.
    """
    if isinstance(runner, BudgetedRunner) and runner.budget is budget:
        return runner
    return BudgetedRunner(runner, budget)


# ---------------------------------------------------------------------------
# slices
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TaskSlices:
    """The task splits an evolver may see, and the disjointness between them.

    ``anchor`` is the fixed slice every method scores on, so round-over-round
    and arm-over-arm numbers are comparable by construction. ``probe`` supplies
    fresh failure modes and is never scored for selection. ``validation`` exists
    because one of the methods here (SkillOpt, arXiv:2605.23904) makes its
    accept decision on data that did not produce the edit, and that separation
    is only real if the two slices are actually disjoint — so it is enforced at
    construction rather than trusted.
    """

    anchor: tuple[TaskId, ...]
    probe: tuple[TaskId, ...] = ()
    validation: tuple[TaskId, ...] = ()

    def __post_init__(self) -> None:
        if not self.anchor:
            raise ValueError("anchor slice is empty; nothing to score against")
        for name, other in (("probe", self.probe), ("validation", self.validation)):
            overlap = sorted(set(self.anchor) & set(other))
            if overlap:
                raise ValueError(
                    f"anchor and {name} slices overlap on {overlap}; a task "
                    f"cannot both be selected on and serve as {name} data"
                )

    @classmethod
    def of(
        cls,
        anchor: Iterable[TaskId],
        *,
        probe: Iterable[TaskId] = (),
        validation: Iterable[TaskId] = (),
    ) -> "TaskSlices":
        """Build from any iterables, normalising to tuples."""
        return cls(tuple(anchor), tuple(probe), tuple(validation))

    def split_anchor(self, *, hold_out: int = 1) -> "TaskSlices":
        """Carve a validation slice out of the anchor by interleaving.

        Interleaved rather than a head/tail cut: task order in these slices is
        not arbitrary — the tail tasks that drive the whole effect tend to be
        grouped — and a contiguous cut can put every cliff task on one side,
        which makes the validation slice measure something the anchor does not
        contain.
        """
        if self.validation:
            return self
        if hold_out < 1 or hold_out >= len(self.anchor):
            raise ValueError(
                f"cannot hold out {hold_out} of {len(self.anchor)} anchor tasks"
            )
        step = max(1, len(self.anchor) // hold_out)
        held = tuple(self.anchor[i] for i in range(0, len(self.anchor), step))[:hold_out]
        kept = tuple(t for t in self.anchor if t not in set(held))
        return TaskSlices(anchor=kept, probe=self.probe, validation=held)


@dataclass(frozen=True)
class SliceScores:
    """One candidate's outcome on one slice: per-task means and the distribution.

    Both are kept because they answer different questions. The mean is what
    selection reads; the per-seed lists are what tells an unlucky zero-score
    termination apart from a candidate that reliably fails, which at two seeds
    is the difference between rejecting an improvement and accepting a
    regression.
    """

    by_task: dict[TaskId, float]
    by_seed: dict[TaskId, tuple[float, ...]]
    cost: Cost
    n_rollouts: int

    @property
    def mean(self) -> float:
        return statistics.mean(self.by_task.values()) if self.by_task else 0.0


def evaluate_on(
    runner: RolloutRunner,
    candidate: Candidate,
    tasks: Sequence[TaskId],
    seeds: Sequence[int],
) -> SliceScores:
    """Score ``candidate`` on ``tasks`` and fold the rollouts into per-task means.

    Rollouts are re-tagged ``anchor`` — the tag means "may influence selection",
    which is true of the anchor slice and equally true of the validation slice a
    strict-improvement method accepts on. What it excludes is probe data, and
    that exclusion is the one this tag exists to enforce.
    """
    rollouts = [
        replace(r, slice="anchor") for r in runner.run_many(candidate, tasks, seeds)
    ]
    by_seed: dict[TaskId, list[float]] = {}
    cost = Cost()
    for r in rollouts:
        by_seed.setdefault(r.task, []).append(r.score.value)
        cost = cost + r.cost
    return SliceScores(
        by_task={t: statistics.mean(v) for t, v in by_seed.items()},
        by_seed={t: tuple(v) for t, v in by_seed.items()},
        cost=cost,
        n_rollouts=len(rollouts),
    )


# ---------------------------------------------------------------------------
# the shared move set
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MoveOutcome:
    """One attempted edit: the child it produced, or why it produced none.

    A move that cannot be applied — a duplicate line, a missing anchor, a
    component over its token budget — is a *free* rejection, costing no
    rollouts. Distinguishing it from a paid rejection is what keeps the spend
    ledger interpretable: an arm that mostly fails for free has not been given
    a fair share of the budget by accident.
    """

    edit: Edit
    child: Candidate | None
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.child is not None


@dataclass(frozen=True)
class EditVocabulary:
    """The bounded add/delete/replace move set, shared by every arm that has no
    proposer.

    Every method that does not call a model draws from *this* object, which is
    what makes the random control a control: it gets the same reachable set of
    candidates as the methods it is there to test, so a difference between them
    is a difference in search strategy and nothing else. Giving the sophisticated
    arms a richer action space than the baseline is the standard way to
    manufacture a win, and it is exactly the failure arXiv:2607.12227 documents.

    The unit is a line, following :mod:`harness_evolve.proposers.edits`: these
    artifacts are line-structured lists of assertions and a line is what a
    negative constraint occupies.
    """

    lines: tuple[str, ...]
    components: tuple[str, ...] = ()
    include_replace: bool = True

    def editable_components(self, candidate: Candidate) -> tuple[str, ...]:
        """Text components this vocabulary may touch, in manifest order."""
        names = [
            name
            for name, spec in candidate.manifest.components.items()
            if spec.is_text and spec.path
        ]
        if self.components:
            wanted = set(self.components)
            names = [n for n in names if n in wanted]
        return tuple(names)

    def moves(self, candidate: Candidate, component: str) -> tuple[Edit, ...]:
        """Every legal edit on ``component``, in a deterministic order.

        Deterministic because two arms drawing from the same vocabulary with the
        same seed must see the same neighbourhood — otherwise a difference in
        outcome could be a difference in which moves each happened to be offered.
        """
        spec = candidate.manifest.components.get(component)
        if spec is None or not spec.path:
            return ()
        present = [l for l in candidate.files.get(spec.path, "").splitlines() if l.strip()]
        unused = [l for l in self.lines if l not in present]

        out: list[Edit] = [Edit(component, Op.ADD, text=l) for l in unused]
        out += [Edit(component, Op.DELETE, anchor=l) for l in present]
        if self.include_replace:
            out += [
                Edit(component, Op.REPLACE, text=new, anchor=old)
                for old in present
                for new in unused
            ]
        return tuple(out)


def apply_move(
    candidate: Candidate, edit: Edit, *, prediction: Prediction | None = None
) -> MoveOutcome:
    """Apply one bounded edit, returning the child or the reason there is none.

    Validation runs here, before the caller can spend anything: a candidate over
    its token budget is rejected for free, which is the only kind of rejection
    this regime can afford in quantity.
    """
    spec = candidate.manifest.components.get(edit.component)
    if spec is None or not spec.path:
        return MoveOutcome(edit, None, f"unknown or pathless component {edit.component!r}")
    try:
        text = apply_edit(candidate.files.get(spec.path, ""), edit)
    except EditError as exc:
        return MoveOutcome(edit, None, str(exc))
    child = candidate.with_edits(
        {spec.path: text}, predictions=[prediction] if prediction else []
    )
    try:
        child.validate()
    except CandidateError as exc:
        return MoveOutcome(edit, None, str(exc))
    return MoveOutcome(edit, child)


#: Which failure category a bare edit operation is implicitly claiming to fix.
#: Coarse on purpose — without a model in the loop there is no diagnosis behind
#: the move, and inventing a finer claim would corrupt the calibration record
#: these predictions exist to produce.
OP_CATEGORY: Mapping[Op, str] = {
    Op.ADD: "missing_block",
    Op.DELETE: "extra_block",
    Op.REPLACE: "structural_mismatch",
}


def declare(
    edit: Edit,
    *,
    beneficiaries: Sequence[TaskId] = (),
    delta: float = 0.0,
    rationale: str = "",
) -> Prediction:
    """The falsifiable contract attached to a move before it is evaluated."""
    return Prediction(
        component=edit.component,
        targets_category=OP_CATEGORY.get(edit.op, "no_failure"),
        predicted_beneficiaries=tuple(beneficiaries),
        predicted_delta=delta,
        rationale=rationale or edit.describe(),
    )


# ---------------------------------------------------------------------------
# traces and results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TraceStep:
    """One thing a method did, and what it learned by doing it."""

    index: int
    phase: str
    detail: str
    candidate_id: str = ""
    component: str = ""
    accepted: bool | None = None
    metrics: dict[str, float] = field(default_factory=dict)
    spent: int = 0

    def render(self) -> str:
        mark = "" if self.accepted is None else ("  accept" if self.accepted else "  reject")
        where = f" [{self.component}]" if self.component else ""
        nums = (
            "  " + " ".join(f"{k}={v:+.3f}" for k, v in sorted(self.metrics.items()))
            if self.metrics
            else ""
        )
        return f"{self.index:>3d} {self.phase:<12}{where} {self.detail}{mark}{nums}"


@dataclass
class EvolverTrace:
    """Why a method selected what it selected.

    Per-method rather than uniform, because the interesting differences between
    these arms are not in their scores — at this sample size the scores will
    mostly overlap — but in what each one *did* with its budget. A comparison
    that reports only the winner cannot distinguish "the gate rejected
    everything" from "the proposer never produced anything applicable", and
    those call for opposite responses.
    """

    method: str
    steps: list[TraceStep] = field(default_factory=list)
    selection_reason: str = ""
    #: Method-specific structured facts (SkillOpt's slice split, AHE's final
    #: component order). Deliberately open: the whole point of a per-method
    #: trace is that methods have things to say that no shared schema anticipates.
    metadata: dict[str, Any] = field(default_factory=dict)

    def add(self, phase: str, detail: str, **kw: Any) -> TraceStep:
        step = TraceStep(index=len(self.steps), phase=phase, detail=detail, **kw)
        self.steps.append(step)
        return step

    def phases(self) -> tuple[str, ...]:
        return tuple(s.phase for s in self.steps)

    def render(self, limit: int = 40) -> str:
        head = [f"trace [{self.method}] {len(self.steps)} step(s)"]
        head += [s.render() for s in self.steps[:limit]]
        if len(self.steps) > limit:
            head.append(f"  ... {len(self.steps) - limit} more")
        if self.selection_reason:
            head.append(f"selected because: {self.selection_reason}")
        return "\n".join(head)


@dataclass
class EvolverResult:
    """What one method produced, what it spent, and why.

    ``archive`` carries *everything tried*, accepted or not. A result object
    holding only the winner cannot answer the question that decides whether a
    null result is informative — how many candidates were even distinguishable
    from the seed — which arXiv:2608.02636 measures as 55 of 388.
    """

    method: str
    selected: ArchiveEntry | None
    archive: Archive
    budget: RolloutBudget
    trace: EvolverTrace
    notes: list[str] = field(default_factory=list)

    @property
    def spent(self) -> int:
        return self.budget.spent

    @property
    def cost(self) -> Cost:
        return self.budget.cost

    @property
    def selected_candidate(self) -> Candidate | None:
        return self.selected.candidate if self.selected else None

    @property
    def returned_the_seed(self) -> bool:
        """Did the method fail to improve on what it started with?

        The predicted outcome in this regime, and pre-registered as such — so it
        needs to be a first-class property rather than something a reader infers
        from two identical ids.
        """
        if self.selected is None or not self.archive.entries:
            return True
        return self.selected.cid == self.archive.entries[0].cid

    def summary(self) -> str:
        lines = [
            f"[{self.method}] spent {self.budget.summary()}",
            self.archive.summary(),
        ]
        if self.selected is not None:
            lines.append(
                f"selected {self.selected.cid} mean={self.selected.mean:.4f}"
                + ("  (the seed)" if self.returned_the_seed else "")
            )
        if self.trace.selection_reason:
            lines.append(f"reason: {self.trace.selection_reason}")
        lines += self.notes
        return "\n".join(lines)


@runtime_checkable
class Evolver(Protocol):
    """One evolution strategy, runnable as an arm of a matched comparison.

    Implementations must hold to three things, all of which the comparison
    depends on and none of which the type system can check:

    1. **Spend only through the runner they are given.** It is budgeted; going
       around it produces a number that cannot be compared to anything.
    2. **Stop cleanly on :class:`BudgetExhausted`** and return what they have.
       An arm that dies on its cap contributes nothing, and the cap is a normal
       operating condition, not an error.
    3. **Select with ``archive.best()``.** Methods differ in what they put in the
       archive, not in how the winner is read out of it.
    """

    @property
    def name(self) -> str:
        """Short arm label, used as the ledger key and the comparison column."""

    def evolve(
        self,
        seed: Candidate,
        slices: TaskSlices,
        runner: RolloutRunner,
        budget: RolloutBudget,
    ) -> EvolverResult:
        """Search from ``seed`` within ``budget`` and return the result."""


# ---------------------------------------------------------------------------
# residual spend
# ---------------------------------------------------------------------------


def extra_seeds(base: Sequence[int]) -> Iterator[int]:
    """Seeds beyond those a search used, for spending a residual budget."""
    return itertools.count(max(base, default=0) + 1)


def exhaust_budget(
    runner: BudgetedRunner,
    entry: ArchiveEntry | None,
    tasks: Sequence[TaskId],
    seeds: Sequence[int],
    *,
    by_seed: Mapping[TaskId, Sequence[float]] | None = None,
) -> int:
    """Spend whatever is left re-measuring the selected candidate at new seeds.

    Methods have different per-candidate costs — SkillOpt pays for a propose
    pass plus a validation pass, the component-cycling arm pays for one anchor
    pass — so each stops with a different remainder, and remainders of a few
    percent are enough to push a comparison outside the matching tolerance.
    Leaving them unspent is not neutral: the arm whose candidates are cheaper is
    silently handed the smaller budget.

    Extra seeds on the incumbent is the most defensible use of the remainder. It
    cannot manufacture a better candidate — nothing new is proposed — it only
    sharpens the estimate of the one already chosen, which is the quantity
    everything downstream is about at n=2 seeds.

    ``by_seed`` is the selected candidate's per-seed scores, so the new rollouts
    are averaged in at their true weight. Without it the archive's per-task mean
    is the only record available and has to be folded in as a single
    observation, which over-weights the new draws; callers that have the
    distribution should pass it.

    Returns the number of rollouts spent.
    """
    budget = runner.budget
    if entry is None or not tasks or budget.exhausted:
        return 0
    phase = runner.for_phase("residual")
    samples: dict[TaskId, list[float]] = {
        t: list((by_seed or {}).get(t) or ([entry.scores[t]] if t in entry.scores else []))
        for t in tasks
    }
    spent = 0
    for seed in extra_seeds(seeds):
        if budget.exhausted:
            break
        for task in tasks:
            if budget.exhausted:
                break
            try:
                rollout = phase.run(entry.candidate, task, seed)
            except BudgetExhausted:
                break
            samples.setdefault(task, []).append(rollout.score.value)
            spent += 1
    if spent:
        entry.scores = {t: statistics.mean(v) for t, v in samples.items() if v}
    return spent
