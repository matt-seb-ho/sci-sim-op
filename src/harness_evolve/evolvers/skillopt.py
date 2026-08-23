"""SkillOpt (arXiv:2605.23904) as an arm: bounded edits, strict held-out accept.

SkillOpt optimises a *single* skill document as the external state of a frozen
agent, through bounded add/delete/replace edits, accepting an edit only when it
strictly improves a held-out validation score, and adding zero inference-time
model calls at deployment. The literature sweep in ``docs/LITERATURE_2026-08.md``
puts it as the de facto reference method for our artifact class, and it is one
of very few evaluated inside a real coding harness.

Two differences from the gated search this repository already had, and both are
the point of running it as a separate arm rather than folding it in:

* **The accept decision is made on data that did not produce the edit.** The
  gated search screens and gates on the same anchor slice it draws its evidence
  from. Here the anchor is split: one part chooses which candidate edit is worth
  evaluating, a disjoint part decides whether it is kept. What that buys is
  protection against selecting on the noise in a small slice; what it costs is
  that both halves are smaller, which at ~17 tasks is not a small cost.

* **Strict improvement, not no-regression.** The gate this repo built asks "did
  anything fall off a cliff" and lets lateral moves through, because the effect
  under study is a tail rescue that a mean cannot see. SkillOpt asks "is this
  measurably better" and returns the incumbent otherwise. On a near-ceiling
  objective that is a much harder bar to clear, and the honest prediction is
  that this arm frequently returns its seed — which is a result, not a bug, and
  :attr:`EvolverResult.returned_the_seed` reports it as one.

A rejected-edit buffer is kept, as in the paper: an edit already refused is not
re-drawn, so the budget goes to unexplored moves rather than to re-confirming a
refusal. It is free to maintain and it is the difference between exploring a
neighbourhood and oscillating inside it (arXiv:2605.20086 finds ~30% of edits in
evolutionary search are byte-identical re-introductions of deleted content).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Sequence

from harness_evolve.core.archive import Archive, ArchiveEntry
from harness_evolve.core.candidate import Candidate
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
from harness_evolve.proposers.edits import Edit
from harness_evolve.runners.base import RolloutRunner
from harness_evolve.types import TaskId


def _edit_key(edit: Edit) -> tuple[str, str, str, str]:
    """Identity of a move, for the rejected-edit buffer."""
    return (edit.component, str(edit.op), edit.text, edit.anchor)


@dataclass
class SkillOptEvolver:
    """Optimise one skill document, accepting only on strict validation gain.

    Parameters
    ----------
    vocabulary:
        The shared bounded move set. Identical to the one the control gets —
        that identity is what makes a loss to the control meaningful.
    skill_component:
        Which component is *the* skill document. SkillOpt trains one artifact,
        not a family of them; defaulting to the first editable component keeps
        that literal rather than quietly optimising everything.
    validation_hold_out:
        Anchor tasks moved to validation when the caller supplies no validation
        slice. The split is recorded in the trace, because "held out from what"
        is the only thing that makes a strict-improvement claim mean anything.
    propose_k:
        Candidate edits sampled per round and ranked on the propose slice; the
        best one goes to validation. Small on purpose: each one costs rollouts,
        and the ranking pass is the cheaper half of a round only while it stays
        small.
    min_improvement:
        How much better than the incumbent a candidate must validate to be
        accepted. Zero means strictly greater, which is the paper's rule.
    """

    vocabulary: EditVocabulary
    skill_component: str | None = None
    seeds: tuple[int, ...] = (1, 2)
    validation_hold_out: int = 2
    propose_k: int = 2
    propose_tasks: int = 2
    propose_seeds: tuple[int, ...] = (1,)
    min_improvement: float = 0.0
    #: Free rejections tolerated before a round is abandoned. A move that cannot
    #: be applied costs nothing, but an exhausted neighbourhood would otherwise
    #: spin forever.
    max_free_retries: int = 12
    rng_seed: int = 0
    name: str = "skillopt"
    exhaust: bool = True

    def evolve(
        self,
        seed: Candidate,
        slices: TaskSlices,
        runner: RolloutRunner,
        budget: RolloutBudget,
    ) -> EvolverResult:
        """Hill-climb the skill document under a strict held-out accept rule."""
        paid = budgeted(runner, budget)
        rng = random.Random(self.rng_seed)
        trace = EvolverTrace(method=self.name)
        notes: list[str] = []
        archive = Archive(rng=random.Random(self.rng_seed))

        split = slices if slices.validation else slices.split_anchor(
            hold_out=self.validation_hold_out
        )
        component = self.skill_component or next(
            iter(self.vocabulary.editable_components(seed)), ""
        )
        if not component:
            raise ValueError("no editable text component to treat as the skill document")
        trace.metadata.update(
            {
                "skill_component": component,
                "propose_tasks": list(split.anchor),
                "validation_tasks": list(split.validation),
                "validation_source": "caller" if slices.validation else "split_from_anchor",
                "accept_rule": f"strict improvement > +{self.min_improvement:g} on validation",
            }
        )

        seed.validate()
        try:
            incumbent_scores = self._validate(paid, seed, split.validation)
        except BudgetExhausted as exc:
            notes.append(f"budget could not fund the seed's validation pass: {exc}")
            return EvolverResult(self.name, None, archive, budget, trace, notes)

        incumbent = archive.add(
            ArchiveEntry(
                seed,
                scores=dict(incumbent_scores.by_task),
                cost=incumbent_scores.cost.to_dict(),
                reason="seed",
            )
        )
        by_seed: dict[str, dict[TaskId, tuple[float, ...]]] = {
            seed.cid: dict(incumbent_scores.by_seed)
        }
        trace.add(
            "seed",
            f"validation mean {incumbent_scores.mean:.4f} on {len(split.validation)} task(s)",
            candidate_id=seed.cid,
            component=component,
            metrics={"validation_mean": incumbent_scores.mean},
            spent=budget.spent,
        )

        rejected: set[tuple[str, str, str, str]] = set()
        round_cost = self._round_cost(split)
        n_rounds = 0

        while budget.remaining >= round_cost:
            n_rounds += 1
            try:
                chosen = self._rank_on_propose_slice(
                    paid, incumbent, split, rng, rejected, trace, budget
                )
            except BudgetExhausted as exc:
                notes.append(f"stopped on the rollout cap: {exc}")
                break
            if chosen is None:
                notes.append(
                    "no applicable unexplored edit remained; the neighbourhood of "
                    "this document under this vocabulary is exhausted"
                )
                break

            edit, child = chosen
            try:
                scores = self._validate(paid, child, split.validation)
            except BudgetExhausted as exc:
                notes.append(f"stopped on the rollout cap: {exc}")
                break

            gain = scores.mean - incumbent.mean
            accepted = gain > self.min_improvement + EPSILON
            entry = archive.add(
                ArchiveEntry(
                    child,
                    scores=dict(scores.by_task),
                    cost=scores.cost.to_dict(),
                    accepted=accepted,
                    reason=(
                        f"validation {scores.mean:+.4f} vs incumbent "
                        f"{incumbent.mean:.4f} ({gain:+.4f})"
                    ),
                    generation=child.generation,
                )
            )
            by_seed[child.cid] = dict(scores.by_seed)
            trace.add(
                "validate",
                edit.describe(),
                candidate_id=child.cid,
                component=component,
                accepted=accepted,
                metrics={"validation_mean": scores.mean, "gain": gain},
                spent=budget.spent,
            )
            if accepted:
                incumbent = entry
            else:
                # Refused once is refused: re-drawing it would buy a second copy
                # of the same measurement at full price.
                rejected.add(_edit_key(edit))

        selected = archive.best()
        if self.exhaust and selected is not None:
            spent = exhaust_budget(
                paid,
                selected,
                split.validation,
                self.seeds,
                by_seed=by_seed.get(selected.cid),
            )
            if spent:
                trace.add(
                    "residual",
                    f"{spent} leftover rollout(s) re-measuring the winner on validation",
                    candidate_id=selected.cid,
                    spent=budget.spent,
                )

        trace.selection_reason = (
            f"best validation mean over {len(archive.accepted)} accepted of "
            f"{len(archive.entries)} evaluated candidate(s), after {n_rounds} round(s); "
            f"acceptance required a strict gain on {len(split.validation)} task(s) "
            "that took no part in choosing the edit"
        )
        trace.metadata["rejected_edits"] = len(rejected)
        return EvolverResult(self.name, selected, archive, budget, trace, notes)

    # -- rounds -----------------------------------------------------------
    def _round_cost(self, split: TaskSlices) -> int:
        """Rollouts one full round costs, so the loop stops before a partial one.

        A round abandoned half-way has spent real rollouts on a decision it
        never made, which is the least useful way to end a budget.
        """
        propose = self.propose_k * min(self.propose_tasks, len(split.anchor)) * len(
            self.propose_seeds
        )
        return propose + len(split.validation) * len(self.seeds)

    def _rank_on_propose_slice(
        self,
        runner: BudgetedRunner,
        incumbent: ArchiveEntry,
        split: TaskSlices,
        rng: random.Random,
        rejected: set[tuple[str, str, str, str]],
        trace: EvolverTrace,
        budget: RolloutBudget,
    ) -> tuple[Edit, Candidate] | None:
        """Draw ``propose_k`` moves, score them on the propose slice, return the best.

        This is the half of the round that *proposes*. It deliberately never
        decides acceptance: its scores come from tasks the validation pass will
        not look at, so a move that wins here on noise still has to survive a
        measurement it cannot have overfitted.
        """
        component = trace.metadata["skill_component"]
        tasks = list(split.anchor)[: max(1, self.propose_tasks)]
        best: tuple[float, Edit, Candidate] | None = None
        drawn = 0
        free_failures = 0

        while drawn < self.propose_k and free_failures < self.max_free_retries:
            moves = [
                m
                for m in self.vocabulary.moves(incumbent.candidate, component)
                if _edit_key(m) not in rejected
            ]
            if not moves:
                break
            edit = rng.choice(moves)
            outcome = apply_move(
                incumbent.candidate,
                edit,
                prediction=declare(edit, beneficiaries=tasks),
            )
            if not outcome.ok:
                free_failures += 1
                rejected.add(_edit_key(edit))  # unapplicable now, unapplicable later
                continue
            drawn += 1
            child = outcome.child
            assert child is not None
            scores = evaluate_on(
                runner.for_phase("propose"), child, tasks, self.propose_seeds
            )
            trace.add(
                "propose",
                edit.describe(),
                candidate_id=child.cid,
                component=component,
                metrics={"propose_mean": scores.mean},
                spent=budget.spent,
            )
            if best is None or scores.mean > best[0]:
                best = (scores.mean, edit, child)

        if best is None:
            return None
        return best[1], best[2]

    def _validate(
        self, runner: BudgetedRunner, candidate: Candidate, tasks: Sequence[TaskId]
    ) -> SliceScores:
        """The accept decision's measurement, on the held-out validation slice."""
        return evaluate_on(runner.for_phase("validate"), candidate, tasks, self.seeds)
