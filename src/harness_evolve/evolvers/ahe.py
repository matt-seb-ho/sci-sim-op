"""AHE-style component-wise evolution (arXiv:2604.25850), with consolidation.

AHE's contribution here is not a search algorithm, it is *observability*: every
edit is paired with a self-declared prediction, verified against the next
round's outcomes, so evolution proceeds by falsifiable claims instead of trial
and error. Its ablation is the other reason it earns an arm — the gains localise
to structural components rather than to the system prompt, which is the argument
for widening the search space past prose and for not letting a proposer decide
where to look.

So this arm differs from the gated search in three ways:

* **The schedule is explicit, not emergent.** A proposer picking its own target
  concentrates on whatever it finds easiest to write about, which is prose. Here
  the components are visited in a declared, configurable order, so the search
  spends its budget where the ablation says the gains are, and an ablation of
  the schedule itself becomes possible. The default order puts list-structured
  components ahead of prose for exactly that reason.

* **Prediction accuracy steers attention.** Each edit names the tasks it expects
  to help; after every full cycle the schedule is re-sorted by how often each
  component's predictions came true. A component the method can predict about is
  one it has a working model of, and budget spent there converts into knowledge;
  a component it is always wrong about is one it is editing blind. This is
  cheap — the decision log already computes hit rates — and it is the only use
  of the prediction channel that changes what the search *does* rather than what
  it reports.

* **Consolidation at the end.** HarnessCompass (arXiv:2608.01918), which
  outperforms AHE on both effectiveness and evolution efficiency, adds
  component-wise-then-consolidate to fix AHE's overfitting. Consolidation here
  strips accepted-but-*unearned* additions — content whose named beneficiaries
  never moved — and re-measures. That is the over-specification failure mode
  caught at the end of a run rather than left in an always-on artifact where it
  costs tokens on every future rollout (v1: 270 B to 3159 B in three rounds).

The accept rule is deliberately weaker than the repository's regression gate:
no aggregate drop beyond a small tolerance, and no task newly reduced to a
failures-as-zero outcome. Two clauses, not six. If the four-clause gate is
carrying the gated-search arm, that shows up as a difference between the arms
rather than as an untested assumption.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Sequence

from harness_evolve.core.archive import Archive, ArchiveEntry
from harness_evolve.core.candidate import Candidate
from harness_evolve.core.decision import (
    DecisionLog,
    DecisionRecord,
    Prediction,
    classify_edit,
    content_hash,
)
from harness_evolve.evolvers.base import (
    EPSILON,
    BudgetExhausted,
    BudgetedRunner,
    EditVocabulary,
    EvolverResult,
    EvolverTrace,
    RolloutBudget,
    SliceScores,
    TaskSlices,
    apply_move,
    budgeted,
    declare,
    evaluate_on,
    exhaust_budget,
)
from harness_evolve.proposers.edits import Edit, Op
from harness_evolve.runners.base import RolloutRunner
from harness_evolve.types import TaskId

#: Component kinds in the order the ablation says they are worth attending to:
#: list-structured artifacts (cheatsheets, derived constraints, checked lists)
#: before free prose. Not a claim that prose never matters — a claim about where
#: a starved budget should look first.
KIND_PRIORITY: tuple[str, ...] = ("itemized", "checked", "prose")

#: Prediction hit rate assumed for a component that has not been visited yet.
#: Optimistic on purpose — see :meth:`AHEStyleEvolver._reorder`.
UNMEASURED_PRIORITY: float = 1.0


def default_schedule(candidate: Candidate, vocabulary: EditVocabulary) -> tuple[str, ...]:
    """Editable components, structural ones first, manifest order within a kind."""
    editable = vocabulary.editable_components(candidate)

    def rank(name: str) -> int:
        kind = candidate.manifest.components[name].kind
        return KIND_PRIORITY.index(kind) if kind in KIND_PRIORITY else len(KIND_PRIORITY)

    return tuple(sorted(editable, key=rank))


@dataclass
class AHEStyleEvolver:
    """Cycle components one at a time, predict each edit, consolidate at the end.

    Parameters
    ----------
    component_schedule:
        The visiting order. Empty means :func:`default_schedule`. Configurable
        because "which component binds is interface-dependent" — structural
        completeness binds on some simulators, value correctness on others — so
        the right order is a property of the simulator, not of the method.
    accept_margin:
        Aggregate drop tolerated. Non-zero so a lateral move that trades a
        little mean for tail safety can still be adopted; the tail is the
        quantity being optimised and it does not show up in a mean.
    reorder_by_prediction:
        Re-sort the schedule by per-component prediction hit rate after each
        full cycle.
    consolidate:
        Run the final pruning pass. It costs one full anchor evaluation, which
        the loop reserves in advance rather than discovering it cannot afford.
    """

    vocabulary: EditVocabulary
    component_schedule: tuple[str, ...] = ()
    seeds: tuple[int, ...] = (1, 2)
    accept_margin: float = 0.005
    n_beneficiaries: int = 2
    predicted_delta: float = 0.02
    reorder_by_prediction: bool = True
    consolidate: bool = True
    max_free_retries: int = 12
    rng_seed: int = 0
    name: str = "ahe_component_wise"
    exhaust: bool = True

    def evolve(
        self,
        seed: Candidate,
        slices: TaskSlices,
        runner: RolloutRunner,
        budget: RolloutBudget,
    ) -> EvolverResult:
        """Run one component-wise search with decision observability."""
        paid = budgeted(runner, budget)
        rng = random.Random(self.rng_seed)
        trace = EvolverTrace(method=self.name)
        log = DecisionLog()
        notes: list[str] = []
        archive = Archive(rng=random.Random(self.rng_seed))
        anchor = list(slices.anchor)

        schedule = list(self.component_schedule or default_schedule(seed, self.vocabulary))
        if not schedule:
            raise ValueError("no editable text component to schedule")
        trace.metadata["initial_schedule"] = list(schedule)

        seed.validate()
        per_candidate = len(anchor) * len(self.seeds)
        reserve = per_candidate if self.consolidate else 0

        try:
            scores = self._score(paid, seed, anchor)
        except BudgetExhausted as exc:
            notes.append(f"budget could not fund the seed evaluation: {exc}")
            return EvolverResult(self.name, None, archive, budget, trace, notes)

        incumbent = archive.add(
            ArchiveEntry(
                seed, scores=dict(scores.by_task), cost=scores.cost.to_dict(), reason="seed"
            )
        )
        by_seed = {seed.cid: dict(scores.by_seed)}
        edits_by_cid: dict[str, Edit] = {}
        seen_hashes: dict[str, set[str]] = {}
        trace.add(
            "seed",
            f"anchor mean {scores.mean:.4f}",
            candidate_id=seed.cid,
            metrics={"mean": scores.mean},
            spent=budget.spent,
        )

        tried: set[tuple[str, str, str, str]] = set()
        cursor = 0
        cycles = 0

        while budget.remaining >= per_candidate + reserve:
            component = schedule[cursor % len(schedule)]
            cursor += 1
            if cursor % len(schedule) == 0:
                cycles += 1
                if self.reorder_by_prediction:
                    schedule = self._reorder(schedule, log, trace, budget)

            move = self._draw(incumbent, component, rng, tried)
            if move is None:
                trace.add(
                    "skip",
                    "no applicable unexplored edit on this component",
                    component=component,
                    spent=budget.spent,
                )
                if self._exhausted_everywhere(incumbent.candidate, schedule, tried):
                    notes.append(
                        "every scheduled component's neighbourhood is exhausted under "
                        "this vocabulary"
                    )
                    break
                continue

            edit, child = move
            try:
                scores = self._score(paid, child, anchor)
            except BudgetExhausted as exc:
                notes.append(f"stopped on the rollout cap: {exc}")
                break

            accepted, reason, deltas = self._accept(scores, incumbent)
            entry = archive.add(
                ArchiveEntry(
                    child,
                    scores=dict(scores.by_task),
                    cost=scores.cost.to_dict(),
                    accepted=accepted,
                    reason=reason,
                    generation=child.generation,
                )
            )
            by_seed[child.cid] = dict(scores.by_seed)
            edits_by_cid[child.cid] = edit
            self._log(log, child, incumbent, edit, deltas, accepted, reason, seen_hashes)
            trace.add(
                "evaluate",
                edit.describe(),
                candidate_id=child.cid,
                component=component,
                accepted=accepted,
                metrics={
                    "mean": scores.mean,
                    "mean_delta": scores.mean - incumbent.mean,
                    "prediction_hit_rate": log.records[-1].prediction_hit_rate or 0.0,
                },
                spent=budget.spent,
            )
            if accepted:
                incumbent = entry

        selected = archive.best()
        if self.consolidate:
            selected = self._consolidate(
                paid, archive, selected, log, edits_by_cid, anchor, trace, notes, budget
            )
        if self.exhaust and selected is not None:
            spent = exhaust_budget(
                paid, selected, anchor, self.seeds, by_seed=by_seed.get(selected.cid)
            )
            if spent:
                trace.add(
                    "residual",
                    f"{spent} leftover rollout(s) re-measuring the winner",
                    candidate_id=selected.cid,
                    spent=budget.spent,
                )

        trace.metadata.update(
            {
                "final_schedule": list(schedule),
                "cycles": cycles,
                "calibration": log.calibration(),
                "unearned_edits": len(log.unearned_edits()),
                "edit_types": log.edit_type_counts(),
            }
        )
        trace.selection_reason = (
            f"component-wise hill climb over {len(schedule)} component(s) in "
            f"{cycles} full cycle(s); best of {len(archive.accepted)} accepted "
            f"candidate(s) on the anchor slice"
        )
        return EvolverResult(self.name, selected, archive, budget, trace, notes)

    # -- moves ------------------------------------------------------------
    def _draw(
        self,
        incumbent: ArchiveEntry,
        component: str,
        rng: random.Random,
        tried: set[tuple[str, str, str, str]],
    ) -> tuple[Edit, Candidate] | None:
        """One applicable, unexplored edit on ``component``, with its prediction.

        The prediction names the incumbent's *weakest* anchor tasks. That is the
        only diagnosis available without a model in the loop, and it is a real
        one: the effect this whole system is about is concentrated in the tasks
        that are currently failing, so "this will help where we are worst" is
        the claim a bounded edit is implicitly making.
        """
        candidate = incumbent.candidate
        weakest = sorted(incumbent.scores, key=lambda t: incumbent.scores[t])[
            : self.n_beneficiaries
        ]
        for _ in range(self.max_free_retries):
            moves = [
                m
                for m in self.vocabulary.moves(candidate, component)
                if (m.component, str(m.op), m.text, m.anchor) not in tried
            ]
            if not moves:
                return None
            edit = rng.choice(moves)
            tried.add((edit.component, str(edit.op), edit.text, edit.anchor))
            outcome = apply_move(
                candidate,
                edit,
                prediction=declare(
                    edit,
                    beneficiaries=weakest,
                    delta=self.predicted_delta,
                    rationale=f"component-wise pass on {component}",
                ),
            )
            if outcome.ok:
                assert outcome.child is not None
                return edit, outcome.child
        return None

    def _exhausted_everywhere(
        self, candidate: Candidate, schedule: Sequence[str], tried: set
    ) -> bool:
        """Is there an untried move left on any scheduled component?

        Checked before breaking out, because one exhausted component says
        nothing about the others and stopping on the first of them would end the
        run with most of the schedule unvisited.
        """
        for component in schedule:
            for move in self.vocabulary.moves(candidate, component):
                if (move.component, str(move.op), move.text, move.anchor) not in tried:
                    return False
        return True

    # -- decisions --------------------------------------------------------
    def _score(
        self, runner: BudgetedRunner, candidate: Candidate, anchor: Sequence[TaskId]
    ) -> SliceScores:
        return evaluate_on(runner.for_phase("anchor"), candidate, anchor, self.seeds)

    def _accept(
        self, scores: SliceScores, incumbent: ArchiveEntry
    ) -> tuple[bool, str, dict[str, float]]:
        """Two clauses: no aggregate drop past tolerance, no new zero-score task."""
        deltas = {
            t: scores.by_task[t] - incumbent.scores.get(t, 0.0)
            for t in scores.by_task
            if t in incumbent.scores
        }
        mean_delta = scores.mean - incumbent.mean
        new_zeros = sorted(
            t
            for t, v in scores.by_task.items()
            if v <= EPSILON and incumbent.scores.get(t, 0.0) > EPSILON
        )
        if new_zeros:
            return False, f"introduces failures-as-zero on {', '.join(new_zeros)}", deltas
        if mean_delta < -self.accept_margin:
            return (
                False,
                f"aggregate regression {mean_delta:+.4f} (limit -{self.accept_margin:g})",
                deltas,
            )
        return True, f"accepted ({mean_delta:+.4f})", deltas

    def _log(
        self,
        log: DecisionLog,
        child: Candidate,
        parent: ArchiveEntry,
        edit: Edit,
        deltas: dict[str, float],
        accepted: bool,
        reason: str,
        seen_hashes: dict[str, set[str]],
    ) -> DecisionRecord:
        """Record the edit as a falsifiable contract, then verify it in place."""
        spec = child.manifest.components[edit.component]
        before = parent.candidate.files.get(spec.path or "", "")
        after = child.files.get(spec.path or "", "")
        seen = seen_hashes.setdefault(edit.component, set())
        edit_type = classify_edit(before, after, seen_hashes=seen)
        seen.add(content_hash(before))
        return log.append(
            DecisionRecord(
                candidate_id=child.cid,
                parent_id=parent.cid,
                component=edit.component,
                edit_type=edit_type,
                # The candidate carries the prediction in its own dataclass; the
                # log wants the decision module's. Same fields, converted rather
                # than aliased so neither module has to import the other's.
                prediction=(
                    Prediction.from_dict(child.predictions[0].to_dict())
                    if child.predictions
                    else None
                ),
                observed_deltas=dict(deltas),
                accepted=accepted,
                reasons=[reason],
            )
        )

    def _reorder(
        self,
        schedule: Sequence[str],
        log: DecisionLog,
        trace: EvolverTrace,
        budget: RolloutBudget,
    ) -> list[str]:
        """Re-sort the schedule by per-component prediction accuracy.

        A component nothing is known about yet is treated as maximally
        promising rather than as maximally bad. The opposite convention has a
        failure mode that eats the whole schedule: the first component visited
        would be the only one with a hit rate, a single wrong prediction would
        sort it behind every unvisited component or ahead of them forever, and
        which components ever got attention would be decided by the order of the
        first cycle rather than by anything measured.
        """
        rates: dict[str, list[float]] = {}
        for rec in log.records:
            hit = rec.prediction_hit_rate
            if hit is not None:
                rates.setdefault(rec.component, []).append(hit)
        if not rates:
            return list(schedule)
        prior = {c: i for i, c in enumerate(schedule)}

        def key(component: str) -> tuple[float, int]:
            seen = rates.get(component)
            score = sum(seen) / len(seen) if seen else UNMEASURED_PRIORITY
            return (-score, prior[component])

        reordered = sorted(schedule, key=key)
        if reordered != list(schedule):
            trace.add(
                "reorder",
                f"{' > '.join(reordered)} (by prediction accuracy)",
                spent=budget.spent,
            )
        return reordered

    # -- consolidation ----------------------------------------------------
    def _consolidate(
        self,
        runner: BudgetedRunner,
        archive: Archive,
        selected: ArchiveEntry | None,
        log: DecisionLog,
        edits_by_cid: dict[str, Edit],
        anchor: Sequence[TaskId],
        trace: EvolverTrace,
        notes: list[str],
        budget: RolloutBudget,
    ) -> ArchiveEntry | None:
        """Strip additions on the winner's lineage whose named beneficiaries never moved.

        An accepted edit that helped none of the tasks it named is not
        necessarily harmful — it may have helped something it did not predict —
        but it is the signature of over-specification, and content that entered
        an always-on artifact for a reason that turned out not to hold costs
        tokens on every rollout thereafter. So the removal is *measured*, not
        assumed: the shorter document is scored and kept only if it comes back
        no worse.

        Everything is stripped in one pass and measured once. Removing lines one
        at a time and keeping each removal on its own merit would be strictly
        better and costs one full anchor evaluation *per line*, which in a
        regime of ~17 tasks at ~25 minutes a rollout is a different project. The
        all-or-nothing version recovers the case where the additions were inert
        and declines in the case where at least one of them was load-bearing,
        which is most of the value at a twentieth of the price.
        """
        if selected is None:
            return selected
        lineage = self._lineage(archive, selected)
        component_text = self._component_lines(selected.candidate)
        unearned = [
            rec
            for rec in log.unearned_edits()
            if rec.candidate_id in lineage
            and (edit := edits_by_cid.get(rec.candidate_id)) is not None
            and edit.op is Op.ADD
            and edit.text.rstrip() in component_text.get(edit.component, ())
        ]
        if not unearned:
            trace.add(
                "consolidate",
                "no unearned addition survives on the winner's lineage",
                candidate_id=selected.cid,
                spent=budget.spent,
            )
            return selected

        candidate = selected.candidate
        stripped: list[str] = []
        for rec in unearned:
            edit = edits_by_cid[rec.candidate_id]
            outcome = apply_move(
                candidate, Edit(edit.component, Op.DELETE, anchor=edit.text.rstrip())
            )
            if outcome.ok and outcome.child is not None:
                candidate = outcome.child
                stripped.append(edit.text.strip()[:60])
        if not stripped or candidate.cid == selected.cid:
            trace.add(
                "consolidate", "no strippable addition survived", spent=budget.spent
            )
            return selected

        try:
            scores = self._score(runner, candidate, anchor)
        except BudgetExhausted as exc:
            notes.append(f"consolidation could not be measured: {exc}")
            trace.add("consolidate", "unmeasured; incumbent kept", spent=budget.spent)
            return selected

        keep = scores.mean >= selected.mean - self.accept_margin
        entry = archive.add(
            ArchiveEntry(
                candidate,
                scores=dict(scores.by_task),
                cost=scores.cost.to_dict(),
                accepted=keep,
                reason=f"consolidated: stripped {len(stripped)} unearned addition(s)",
                generation=candidate.generation,
            )
        )
        trace.add(
            "consolidate",
            f"stripped {len(stripped)} unearned addition(s): {'; '.join(stripped)}"
            + ("" if keep else " — measured worse, incumbent kept"),
            candidate_id=candidate.cid,
            accepted=keep,
            metrics={"mean": scores.mean, "mean_delta": scores.mean - selected.mean},
            spent=budget.spent,
        )
        return entry if keep else selected

    @staticmethod
    def _lineage(archive: Archive, entry: ArchiveEntry) -> set[str]:
        """Candidate ids on the path from ``entry`` back to the seed.

        Consolidation must only strip edits that are actually *in* the winner.
        A rejected branch's unearned addition is not in the winning document,
        and trying to delete it either fails or — worse, since anchors match
        fuzzily — removes a different line that happens to read like it.
        """
        ids: set[str] = set()
        current: Candidate | None = entry.candidate
        while current is not None and current.cid not in ids:
            ids.add(current.cid)
            parent = archive.get(current.parent_id) if current.parent_id else None
            current = parent.candidate if parent else None
        return ids

    @staticmethod
    def _component_lines(candidate: Candidate) -> dict[str, tuple[str, ...]]:
        """Each component's current lines, for exact membership tests."""
        out: dict[str, tuple[str, ...]] = {}
        for name, spec in candidate.manifest.components.items():
            if spec.path:
                out[name] = tuple(candidate.files.get(spec.path, "").splitlines())
        return out
