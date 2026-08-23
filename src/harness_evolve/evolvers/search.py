"""The existing search loop, exposed as one arm among several.

:class:`harness_evolve.core.search.Search` is Pareto parent selection over
per-task scores, gated screening before full evaluation, and a regression gate
that asks "did anything fall off a cliff" rather than "did the mean rise". Each
of those traces to a measured property of this task, and the loop carries 20+
tests and a seed-aware cumulative-drift clause that took a live run to discover.

So this is a *wrapper*, not a reimplementation. Nothing here changes how that
loop searches; it supplies the loop with a budgeted runner, catches the cap when
the loop walks into it, and re-expresses the decision log as a trace in the
shared shape so this arm can sit next to the others in one table.

The one behavioural decision made here is the default candidate budget: it is
set to the rollout cap, which is an upper bound no search can reach, so the
*rollout* budget is what stops the loop. A candidate-count limit that bites
first would make this arm quietly under-spend, and an under-spending arm in a
matched comparison is the failure this package exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from harness_evolve.core.acceptance import RegressionGate
from harness_evolve.core.candidate import Candidate
from harness_evolve.core.search import EvidenceBuilder, HygieneGate, Search, SearchConfig
from harness_evolve.evolvers.base import (
    BudgetExhausted,
    EvolverResult,
    EvolverTrace,
    RolloutBudget,
    TaskSlices,
    budgeted,
    exhaust_budget,
)
from harness_evolve.proposers.base import Demonstration, Proposer
from harness_evolve.runners.base import RolloutRunner


@dataclass
class SearchEvolver:
    """Pareto selection + gated screening + regression gate, as an arm.

    Parameters
    ----------
    proposer_factory:
        Called once per :meth:`evolve`. A factory rather than an instance
        because proposers carry state — a scripted one advances an index, an
        LLM one accumulates history — and an arm that inherits the previous
        arm's state is not the method it claims to be.
    config:
        Overrides the loop's knobs. When omitted, everything keeps its default
        except the candidate budget, which is raised until the rollout cap is
        what binds.
    """

    proposer_factory: Callable[[], Proposer]
    config: SearchConfig | None = None
    gate: RegressionGate | None = None
    hygiene: HygieneGate | None = None
    evidence_builder: EvidenceBuilder | None = None
    demonstrations: Sequence[Demonstration] = ()
    decision_log_path: Path | None = None
    name: str = "gated_search"
    #: Spend any remainder re-measuring the winner. See
    #: :func:`~harness_evolve.evolvers.base.exhaust_budget`.
    exhaust: bool = True

    def evolve(
        self,
        seed: Candidate,
        slices: TaskSlices,
        runner: RolloutRunner,
        budget: RolloutBudget,
    ) -> EvolverResult:
        """Run the gated search under ``budget`` and report it in the shared shape."""
        paid = budgeted(runner, budget)
        cfg = self.config or SearchConfig(budget_candidates=max(1, budget.cap))
        search = Search(
            paid.for_phase("search"),
            self.proposer_factory(),
            gate=self.gate,
            hygiene=self.hygiene,
            evidence_builder=self.evidence_builder,
            config=cfg,
            demonstrations=self.demonstrations,
            decision_log_path=self.decision_log_path,
        )
        trace = EvolverTrace(method=self.name)
        notes: list[str] = []

        try:
            result = search.run(seed, slices.anchor, slices.probe)
            notes.extend(result.notes)
            notes.append(
                f"proposed {result.n_proposed}, screened out {result.n_screened_out}, "
                f"hygiene-blocked {result.n_hygiene_blocked}, "
                f"proposer failures {result.n_proposer_failures}"
            )
            if result.stagnated:
                notes.append("search stagnated before exhausting its budget")
        except BudgetExhausted as exc:
            # Normal termination, not an error: the cap is the stopping rule.
            # The archive is an attribute of the loop, so everything evaluated
            # before the refused rollout is still here to be selected from.
            notes.append(f"stopped on the rollout cap: {exc}")

        self._transcribe(search, trace)
        selected = search.archive.best()
        if self.exhaust:
            spent = exhaust_budget(paid, selected, slices.anchor, cfg.seeds)
            if spent:
                trace.add(
                    "residual",
                    f"{spent} leftover rollout(s) re-measuring the winner",
                    candidate_id=selected.cid if selected else "",
                    spent=budget.spent,
                )

        accepted = len(search.archive.accepted)
        trace.selection_reason = (
            f"highest mean among {accepted} gate-accepted candidate(s) on the "
            f"anchor slice; {len(search.archive.entries) - accepted} were rejected"
        )
        trace.metadata.update(
            {
                "gate": type(search.gate).__name__,
                "screen_tasks": cfg.screen_tasks,
                "seeds": list(cfg.seeds),
                "calibration": search.log.calibration(),
                "edit_types": search.log.edit_type_counts(),
                "cycling_rate": search.log.cycling_rate(),
                "constraints": search.constraints.summary() if search.constraints else "",
            }
        )
        return EvolverResult(
            method=self.name,
            selected=selected,
            archive=search.archive,
            budget=budget,
            trace=trace,
            notes=notes,
        )

    @staticmethod
    def _transcribe(search: Search, trace: EvolverTrace) -> None:
        """Re-express the decision log as trace steps.

        The log already answers "why was this accepted"; restating it in the
        shared shape is what lets one renderer print four methods that agree on
        nothing else.
        """
        if search.archive.entries:
            root = search.archive.entries[0]
            trace.add(
                "seed",
                f"seed evaluated, mean={root.mean:.4f}",
                candidate_id=root.cid,
            )
        for rec in search.log.records:
            metrics: dict[str, float] = {}
            for key in ("worst_delta", "mean_delta"):
                value = rec.metrics.get(key)
                if isinstance(value, (int, float)):
                    metrics[key] = float(value)
            hit = rec.prediction_hit_rate
            if hit is not None:
                metrics["prediction_hit_rate"] = hit
            trace.add(
                "accept" if rec.accepted else "reject",
                "; ".join(rec.reasons) or str(rec.edit_type),
                candidate_id=rec.candidate_id,
                component=rec.component,
                accepted=rec.accepted,
                metrics=metrics,
            )
