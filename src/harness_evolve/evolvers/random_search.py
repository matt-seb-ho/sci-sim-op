"""Random search over bounded edits: the control, built to be able to win.

Every claim this repository could make is a claim that some structure —
Pareto selection, a regression gate, a held-out accept rule, a component
schedule — buys something over sampling. arXiv:2607.12227's finding is that
automatic harness evolution often does not beat trivial baselines, and that this
goes unnoticed because the baseline is built to lose: given fewer rollouts, a
narrower edit vocabulary, or a worse final selection rule than the method it is
supposed to test.

So the three things that would make this a straw man are removed by
construction:

* **Same budget.** It receives the identical :class:`RolloutBudget`, and it
  spends it — the loop runs until it cannot afford another full evaluation, and
  any remainder goes to re-measuring its own selection.
* **Same edit vocabulary.** The very same :class:`EditVocabulary` instance the
  sophisticated arms draw from. Every candidate they can reach, it can reach.
* **Same final selection rule.** ``archive.best()``: highest mean on the anchor
  slice. Nothing is discarded before that, because *no gating* is the whole
  definition of this arm.

What it does not have is a gate, an accept rule, a screen, or a memory of what
it already tried beyond avoiding exact duplicates. Candidates are drawn afresh
from the seed each time rather than from the incumbent: a random walk that keeps
its last accepted step is hill climbing without a gate, which is a different
method and a much weaker control. Drawing from the seed with a random edit depth
samples the neighbourhood the other arms are climbing through, which is what
makes "the structure bought nothing" a reachable conclusion rather than an
excluded one.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from harness_evolve.core.archive import Archive, ArchiveEntry
from harness_evolve.core.candidate import Candidate
from harness_evolve.evolvers.base import (
    BudgetExhausted,
    EditVocabulary,
    EvolverResult,
    EvolverTrace,
    RolloutBudget,
    TaskSlices,
    apply_move,
    budgeted,
    declare,
    evaluate_on,
    exhaust_budget,
)
from harness_evolve.runners.base import RolloutRunner


@dataclass
class RandomSearchEvolver:
    """Sample bounded edits at random, keep the best on the anchor slice.

    Parameters
    ----------
    max_edits:
        Largest number of edits applied to one sample. Depth is drawn uniformly
        in ``[1, max_edits]`` so single-edit neighbours and the deeper
        candidates a multi-round hill climb would reach are both in range —
        a depth-1-only control could not express the outcome of any of the
        other arms and so could not test them.
    """

    vocabulary: EditVocabulary
    seeds: tuple[int, ...] = (1, 2)
    max_edits: int = 3
    #: Free rejections tolerated per sample. A move that will not apply costs
    #: nothing, but an exhausted neighbourhood must not spin.
    max_free_retries: int = 12
    rng_seed: int = 0
    name: str = "random_search"
    exhaust: bool = True

    def evolve(
        self,
        seed: Candidate,
        slices: TaskSlices,
        runner: RolloutRunner,
        budget: RolloutBudget,
    ) -> EvolverResult:
        """Draw candidates until the budget is gone, then return the best one."""
        paid = budgeted(runner, budget)
        rng = random.Random(self.rng_seed)
        trace = EvolverTrace(method=self.name)
        notes: list[str] = []
        archive = Archive(rng=random.Random(self.rng_seed))
        anchor = list(slices.anchor)
        per_candidate = len(anchor) * len(self.seeds)

        seed.validate()
        try:
            scores = evaluate_on(
                paid.for_phase("sample"), seed, anchor, self.seeds
            )
        except BudgetExhausted as exc:
            notes.append(f"budget could not fund the seed evaluation: {exc}")
            return EvolverResult(self.name, None, archive, budget, trace, notes)

        archive.add(
            ArchiveEntry(
                seed, scores=dict(scores.by_task), cost=scores.cost.to_dict(), reason="seed"
            )
        )
        by_seed = {seed.cid: dict(scores.by_seed)}
        trace.add(
            "seed",
            f"anchor mean {scores.mean:.4f}",
            candidate_id=seed.cid,
            metrics={"mean": scores.mean},
            spent=budget.spent,
        )

        n_drawn = 0
        n_duplicate = 0
        while budget.remaining >= per_candidate:
            child = self._sample(seed, rng)
            if child is None:
                notes.append(
                    "no applicable edit could be drawn; the vocabulary offers "
                    "nothing this document has not already absorbed"
                )
                break
            if archive.get(child.cid) is not None:
                # A free skip: re-evaluating an identical candidate would spend
                # rollouts to reproduce a number already in the archive.
                n_duplicate += 1
                continue
            n_drawn += 1
            try:
                scores = evaluate_on(
                    paid.for_phase("sample"), child, anchor, self.seeds
                )
            except BudgetExhausted as exc:
                notes.append(f"stopped on the rollout cap: {exc}")
                break
            # No gate. Every sample enters the archive as an eligible selection,
            # which is what "keep the best, no gating" means and what makes this
            # arm able to pick up a candidate the gated arms would have refused.
            archive.add(
                ArchiveEntry(
                    child,
                    scores=dict(scores.by_task),
                    cost=scores.cost.to_dict(),
                    accepted=True,
                    reason=f"sampled (mean {scores.mean:.4f}); no gate applied",
                    generation=child.generation,
                )
            )
            by_seed[child.cid] = dict(scores.by_seed)
            trace.add(
                "sample",
                f"{child.generation} edit(s) from the seed",
                candidate_id=child.cid,
                metrics={"mean": scores.mean},
                spent=budget.spent,
            )

        selected = archive.best()
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
            {"n_sampled": n_drawn, "n_duplicate_skipped": n_duplicate, "gate": None}
        )
        trace.selection_reason = (
            f"highest anchor mean over {n_drawn} candidate(s) sampled uniformly "
            "from the seed's edit neighbourhood; nothing was gated out"
        )
        return EvolverResult(self.name, selected, archive, budget, trace, notes)

    def _sample(self, seed: Candidate, rng: random.Random) -> Candidate | None:
        """One candidate: between 1 and ``max_edits`` random moves from the seed."""
        components = self.vocabulary.editable_components(seed)
        if not components:
            return None
        depth = rng.randint(1, max(1, self.max_edits))
        candidate = seed
        applied = 0
        failures = 0
        while applied < depth and failures < self.max_free_retries:
            component = rng.choice(components)
            moves = self.vocabulary.moves(candidate, component)
            if not moves:
                failures += 1
                continue
            edit = rng.choice(moves)
            outcome = apply_move(candidate, edit, prediction=declare(edit))
            if not outcome.ok:
                failures += 1
                continue
            assert outcome.child is not None
            candidate = outcome.child
            applied += 1
        return candidate if applied else None
