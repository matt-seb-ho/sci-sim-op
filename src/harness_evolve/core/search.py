"""The search loop.

Structure, and which finding each piece answers:

* **Pareto parent selection over per-task scores** -- the measured effect in
  this task is a small number of catastrophic-failure rescues, with everything
  else inside run-to-run noise. Mean-based hill climbing discards the candidate
  that produced a rescue if its average is unremarkable; a frontier keeps it.

* **Free gates before paid gates** -- manifest validity, token budgets, hygiene,
  and check-plugin tests all run before a single rollout is spent, because a
  rollout here costs ~25 minutes.

* **Gated screening** (arXiv:2607.13683) -- a cheap partial evaluation filters
  offspring before full evaluation. With a budget measured in tens of
  candidates, the dominant cost is fully evaluating proposals that a two-task
  look would have killed.

* **Regression gate, not mean improvement** (arXiv:2606.09498; arXiv:2606.31121)
  -- accept only when nothing fell off a cliff, no new zero-score termination
  appeared, and cost did not inflate.

* **Explore on stagnation** (arXiv:2605.13941) -- revert-on-regression alone
  converges to a local optimum and then quietly does nothing. After K barren
  rounds the loop deliberately widens.

* **Demonstration conditioning** (arXiv:2605.24539) -- self-rollout evolution is
  reported to break down under sparse, high-variance reward where failures are
  hard to attribute. That describes this task. Expert traces give the proposer
  something to diagnose against when reward alone is too noisy.

The loop takes its evidence builder as a callable rather than importing an
evidence module, so the search can run against a mock, a cached corpus, or the
real thing without knowing which.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence

from harness_evolve.core.acceptance import RegressionGate
from harness_evolve.core.archive import Archive, ArchiveEntry
from harness_evolve.core.candidate import Candidate
from harness_evolve.evidence.directives import ConstraintLedger
from harness_evolve.core.decision import (
    DecisionLog, DecisionRecord, EditType, Prediction, classify_edit, content_hash,
)
from harness_evolve.proposers.base import Demonstration, Proposer, ProposerError
from harness_evolve.runners.base import RolloutRunner
from harness_evolve.types import Cost, Rollout, TaskId


class EvidenceBuilder(Protocol):
    """Builds the corpus a proposer reasons over, from a candidate's rollouts."""

    def __call__(
        self, entry: ArchiveEntry, rollouts: Sequence[Rollout]
    ) -> Any: ...


class HygieneGate(Protocol):
    """Returns an object with ``.blocked`` and ``.findings``."""

    def __call__(self, candidate: Candidate) -> Any: ...


@dataclass
class SearchConfig:
    """Knobs, with the reasoning for each default.

    Attributes
    ----------
    budget_candidates:
        Total proposals. Deliberately small: at ~25 min and a container per
        task-run, a budget of hundreds is not a tuning choice, it is a
        different project.
    seeds:
        Seeds per candidate on the full anchor evaluation. Two during search
        (cost), more for the final head-to-head, where the claim is made.
    screen_tasks / screen_seeds:
        The cheap pre-filter. A child scoring far below its parent on a couple
        of tasks at one seed is very unlikely to survive the full gate, and
        killing it here saves most of the budget.
    screen_margin:
        How far below the parent a child may screen before being dropped. Loose
        on purpose -- at one seed the noise is large, and a tight margin would
        discard good candidates on a coin flip.
    stagnation_rounds:
        Barren rounds before the loop widens its search.
    probe_tasks / probe_seeds / probe_every:
        Fresh-evidence sampling. Kept small and infrequent because probe
        rollouts cost the same as anchor rollouts while contributing nothing to
        selection -- they buy the proposer new failure modes to reason about,
        which is worth some budget but not much of it.
    """

    budget_candidates: int = 20
    seeds: tuple[int, ...] = (1, 2)
    screen_tasks: int = 3
    screen_seeds: tuple[int, ...] = (1,)
    screen_margin: float = 0.15
    stagnation_rounds: int = 4
    max_consecutive_proposer_failures: int = 5
    probe_tasks: int = 2
    probe_seeds: tuple[int, ...] = (1,)
    probe_every: int = 3


@dataclass
class SearchResult:
    archive: Archive
    log: DecisionLog
    best: ArchiveEntry | None
    n_proposed: int = 0
    n_screened_out: int = 0
    n_hygiene_blocked: int = 0
    n_proposer_failures: int = 0
    n_probe_rollouts: int = 0
    constraint_summary: str = ""
    total_cost: Cost = field(default_factory=Cost)
    stagnated: bool = False
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"proposed {self.n_proposed}, "
            f"screened out {self.n_screened_out}, "
            f"hygiene-blocked {self.n_hygiene_blocked}, "
            f"proposer failures {self.n_proposer_failures}, "
            f"probe rollouts {self.n_probe_rollouts}",
            self.archive.summary(),
            self.log.summary(),
            f"total rollout cost: {self.total_cost.to_dict()}",
        ]
        if self.constraint_summary:
            lines.append(f"validator constraints: {self.constraint_summary}")
        if self.stagnated:
            lines.append("search stagnated before exhausting its budget")
        lines += self.notes
        return "\n".join(lines)


class Search:
    """Run one adapter search."""

    def __init__(
        self,
        runner: RolloutRunner,
        proposer: Proposer,
        *,
        gate: RegressionGate | None = None,
        hygiene: HygieneGate | None = None,
        evidence_builder: EvidenceBuilder | None = None,
        config: SearchConfig | None = None,
        demonstrations: Sequence[Demonstration] = (),
        decision_log_path: Path | None = None,
        ledger: Any = None,
        mine_directives: bool = True,
    ) -> None:
        self.runner = runner
        self.proposer = proposer
        self.gate = gate or RegressionGate()
        self.hygiene = hygiene
        self.evidence_builder = evidence_builder
        self.cfg = config or SearchConfig()
        self.demonstrations = list(demonstrations)
        # The search records its own spend so budget matching is auditable
        # rather than asserted. Every rollout counts, including those spent on
        # candidates that were screened out or rejected -- a search that only
        # counts its successes is exactly the accounting error that lets
        # "harness evolution beat the baseline" mean "harness evolution had more
        # inference compute" (arXiv:2607.12227).
        self.ledger = ledger
        # Constraints the validator states are mined from rollouts already paid
        # for, so the marginal cost of one is zero. They are fed forward to the
        # proposer as settled fact rather than left for it to guess -- writing a
        # constraint is cheap, learning whether one is true costs a full round.
        self.constraints = ConstraintLedger() if mine_directives else None
        self.log = DecisionLog(path=decision_log_path)
        self.archive = Archive()
        self._rollouts: dict[str, list[Rollout]] = {}
        # Per-task, per-seed scores. The gate needs the distribution, not the
        # mean: with stochastic zero-score terminations, a mean-based cliff test
        # rejects almost every candidate, including genuine improvements.
        self._by_seed: dict[str, dict[TaskId, list[float]]] = {}
        self._seen_hashes: dict[str, set[str]] = {}

    # -- evaluation -------------------------------------------------------
    def _evaluate(
        self, candidate: Candidate, tasks: Sequence[TaskId], seeds: Sequence[int]
    ) -> tuple[dict[TaskId, float], Cost, list[Rollout]]:
        """Score a candidate on the anchor slice.

        Every rollout is tagged ``anchor`` and the aggregation refuses anything
        else. The refusal is deliberate belt-and-braces: the failure it prevents
        -- selecting on data that was also shown to the proposer as evidence --
        produces a search that appears to improve and has only memorised its own
        feedback, which no downstream metric would reveal.
        """
        rollouts = [
            replace(r, slice="anchor")
            for r in self.runner.run_many(candidate, tasks, seeds)
        ]
        by_task: dict[TaskId, list[float]] = {}
        cost = Cost()
        for r in rollouts:
            if not r.selectable:
                raise ValueError(
                    f"rollout for {r.task!r} is slice={r.slice!r} and cannot be "
                    "used for selection"
                )
            by_task.setdefault(r.task, []).append(r.score.value)
            cost = cost + r.cost
        scores = {t: statistics.mean(v) for t, v in by_task.items()}
        self._by_seed[candidate.cid] = {t: list(v) for t, v in by_task.items()}
        self._observe_directives(rollouts)
        self._record_spend(rollouts, note="anchor evaluation")
        return scores, cost, rollouts

    def _observe_directives(self, rollouts: Sequence[Rollout]) -> None:
        if self.constraints is None:
            return
        events = [ev for r in rollouts for ev in r.validator_events]
        if events:
            self.constraints.observe(events)

    def _publish_constraints(self) -> None:
        """Hand the proposer everything the validator has settled so far.

        Duck-typed rather than added to the ``Proposer`` protocol: a proposer
        that has no use for them (a scripted one, or the random control) should
        not have to declare that.
        """
        if self.constraints is None:
            return
        if hasattr(self.proposer, "derived_constraints"):
            self.proposer.derived_constraints = self.constraints.constraints()

    def _record_spend(self, rollouts: Sequence[Rollout], *, note: str) -> None:
        if self.ledger is None or not rollouts:
            return
        self.ledger.record_rollouts("search", list(rollouts), note=note)

    def _probe(
        self, candidate: Candidate, tasks: Sequence[TaskId]
    ) -> tuple[Cost, list[Rollout]]:
        """Run probe tasks for evidence only. Returns no scores, by design.

        There is no scores dict to accidentally pass to the gate. Probe exists
        so the proposer keeps seeing failure modes the anchor slice has already
        been optimised against -- an anchor-only loop goes blind to everything
        it has already fixed, and then has nothing left to propose about.
        """
        if not tasks:
            return Cost(), []
        n = min(self.cfg.probe_tasks, len(tasks))
        chosen = self.archive.rng.sample(list(tasks), n)
        rollouts = [
            replace(r, slice="probe")
            for r in self.runner.run_many(candidate, chosen, self.cfg.probe_seeds)
        ]
        cost = Cost()
        for r in rollouts:
            cost = cost + r.cost
        self._record_spend(rollouts, note="probe evidence (not scored)")
        return cost, rollouts

    def _screen(
        self, child: Candidate, parent: ArchiveEntry, tasks: Sequence[TaskId]
    ) -> tuple[bool, str, Cost]:
        """Cheap partial evaluation. Returns ``(survives, reason, cost)``.

        Screens on the parent's *weakest* tasks rather than a random subset:
        those are where a real improvement should show first, and where a
        regression is most consequential.
        """
        if not self.cfg.screen_tasks or self.cfg.screen_tasks >= len(tasks):
            return True, "screening disabled", Cost()
        weakest = sorted(tasks, key=lambda t: parent.scores.get(t, 0.0))
        subset = weakest[: self.cfg.screen_tasks]
        scores, cost, _ = self._evaluate(child, subset, self.cfg.screen_seeds)
        deltas = [scores[t] - parent.scores.get(t, 0.0) for t in subset if t in scores]
        if not deltas:
            return True, "no comparable screening scores", cost
        worst = min(deltas)
        if worst < -self.cfg.screen_margin:
            return (
                False,
                f"screened out: {worst:+.3f} on {subset[deltas.index(worst)]} "
                f"(margin -{self.cfg.screen_margin:.2f})",
                cost,
            )
        return True, f"screened in (worst {worst:+.3f})", cost

    # -- one iteration ----------------------------------------------------
    def _record(
        self,
        child: Candidate,
        parent: ArchiveEntry,
        *,
        accepted: bool,
        reasons: Sequence[str],
        deltas: dict[str, float] | None = None,
        metrics: dict[str, Any] | None = None,
    ) -> DecisionRecord:
        pred = child.predictions[0] if child.predictions else None
        component = pred.component if pred else "?"
        spec = child.manifest.components.get(component)
        before = parent.candidate.files.get(spec.path, "") if spec and spec.path else ""
        after = child.files.get(spec.path, "") if spec and spec.path else ""
        seen = self._seen_hashes.setdefault(component, set())
        edit_type = classify_edit(before, after, seen_hashes=seen)
        seen.add(content_hash(before))

        return self.log.append(
            DecisionRecord(
                candidate_id=child.cid,
                parent_id=parent.cid,
                component=component,
                edit_type=edit_type,
                prediction=Prediction.from_dict(pred.to_dict()) if pred else None,
                observed_deltas=dict(deltas or {}),
                accepted=accepted,
                reasons=list(reasons),
                metrics=dict(metrics or {}),
            )
        )

    # -- the loop ---------------------------------------------------------
    def run(
        self,
        seed: Candidate,
        anchor_tasks: Sequence[TaskId],
        probe_tasks: Sequence[TaskId] = (),
    ) -> SearchResult:
        if not anchor_tasks:
            raise ValueError("anchor slice is empty; nothing to score against")
        overlap = set(anchor_tasks) & set(probe_tasks)
        if overlap:
            raise ValueError(
                f"anchor and probe slices overlap on {sorted(overlap)}; a task "
                "cannot both be selected on and used as fresh evidence"
            )

        result = SearchResult(archive=self.archive, log=self.log, best=None)

        seed.validate()
        scores, cost, rollouts = self._evaluate(seed, anchor_tasks, self.cfg.seeds)
        result.total_cost = result.total_cost + cost
        seed_entry = self.archive.add(
            ArchiveEntry(seed, scores=scores, cost=cost.to_dict(), reason="seed")
        )
        self._rollouts[seed.cid] = rollouts

        barren = 0
        consecutive_failures = 0

        while result.n_proposed < self.cfg.budget_candidates:
            result.n_proposed += 1

            # Stagnation widens the search rather than letting it idle: with a
            # strict gate, "no accepted candidate" is the expected steady state,
            # not an anomaly.
            exploratory = barren >= self.cfg.stagnation_rounds
            parent = self._select_parent(exploratory)
            if parent is None:
                result.notes.append("archive empty; aborting")
                break

            # (n-1) % every, not n % every: with every=1 the latter is never
            # true, which would silently disable probing at its most aggressive
            # setting -- the failure mode being that a knob turned all the way
            # up does nothing at all.
            if probe_tasks and (result.n_proposed - 1) % self.cfg.probe_every == 0:
                probe_cost, probe_rollouts = self._probe(
                    parent.candidate, probe_tasks
                )
                result.total_cost = result.total_cost + probe_cost
                result.n_probe_rollouts += len(probe_rollouts)
                self._rollouts.setdefault(parent.cid, []).extend(probe_rollouts)

            evidence = self._build_evidence(parent)
            self._publish_constraints()
            try:
                child = self.proposer.propose(
                    parent.candidate,
                    evidence,
                    history=[r.to_dict() for r in self.log.records[-6:]],
                    demonstrations=self.demonstrations,
                )
                consecutive_failures = 0
            except (ProposerError, Exception) as exc:  # noqa: BLE001
                result.n_proposer_failures += 1
                consecutive_failures += 1
                result.notes.append(f"proposal {result.n_proposed} failed: {exc}")
                if consecutive_failures >= self.cfg.max_consecutive_proposer_failures:
                    result.notes.append(
                        f"{consecutive_failures} consecutive proposer failures; "
                        "aborting rather than burning the budget"
                    )
                    break
                continue

            if self.archive.get(child.cid):
                result.notes.append(f"duplicate candidate {child.cid}; skipped")
                barren += 1
                continue

            # free gate: contamination
            if self.hygiene is not None:
                report = self.hygiene(child)
                if getattr(report, "blocked", False):
                    result.n_hygiene_blocked += 1
                    findings = getattr(report, "findings", [])
                    reason = f"hygiene: {findings[0] if findings else 'blocked'}"
                    self.archive.add(
                        ArchiveEntry(child, accepted=False, reason=reason,
                                     generation=child.generation)
                    )
                    self._record(child, parent, accepted=False, reasons=[reason])
                    barren += 1
                    continue

            # cheap paid gate
            survives, screen_reason, screen_cost = self._screen(
                child, parent, anchor_tasks
            )
            result.total_cost = result.total_cost + screen_cost
            if not survives:
                result.n_screened_out += 1
                self.archive.add(
                    ArchiveEntry(child, accepted=False, reason=screen_reason,
                                 generation=child.generation)
                )
                self._record(child, parent, accepted=False, reasons=[screen_reason])
                barren += 1
                continue

            # full paid gate
            scores, cost, rollouts = self._evaluate(
                child, anchor_tasks, self.cfg.seeds
            )
            result.total_cost = result.total_cost + cost
            verdict = self.gate.evaluate(
                scores,
                parent.scores,
                child_cost=cost.to_dict(),
                parent_cost=parent.cost,
                child_by_seed=self._by_seed.get(child.cid),
                parent_by_seed=self._by_seed.get(parent.cid),
                root_scores=seed_entry.scores,
                root_by_seed=self._by_seed.get(seed_entry.cid),
            )
            entry = self.archive.add(
                ArchiveEntry(
                    child,
                    scores=scores,
                    cost=cost.to_dict(),
                    accepted=verdict.accepted,
                    reason=verdict.reason,
                    generation=child.generation,
                )
            )
            self._rollouts[child.cid] = rollouts
            self._record(
                child, parent,
                accepted=verdict.accepted,
                reasons=verdict.reasons or [screen_reason],
                deltas=verdict.metrics.get("per_task_deltas", {}),
                metrics={k: v for k, v in verdict.metrics.items()
                         if k != "per_task_deltas"},
            )
            barren = 0 if verdict.accepted else barren + 1

        result.best = self.archive.best()
        result.stagnated = barren >= self.cfg.stagnation_rounds
        if self.constraints is not None:
            result.constraint_summary = self.constraints.summary()
        return result

    # -- helpers ----------------------------------------------------------
    def _select_parent(self, exploratory: bool) -> ArchiveEntry | None:
        """Frontier sample normally; a wider draw once the frontier goes barren.

        The exploratory draw includes non-frontier accepted candidates, so the
        loop can back out of a corner it has hill-climbed into instead of
        re-proposing against the same parent forever.
        """
        if not exploratory:
            return self.archive.select_parent()
        pool = self.archive.accepted or self.archive.entries
        return self.archive.rng.choice(pool) if pool else None

    def _build_evidence(self, entry: ArchiveEntry) -> Any:
        if self.evidence_builder is None:
            return None
        return self.evidence_builder(entry, self._rollouts.get(entry.cid, []))
