"""The selection operator: Self-Harness's regression gate, SIGA-shaped.

v1 had no selection operator. ``reflect.py`` wrote ``v{N+1}`` unconditionally;
the only rejection paths were malformed output, path traversal, and a path
allowlist. There was no accept-if-better gate, no regression check, and no
rollback -- and no reward signal to gate on even if there had been.

The gate here is deliberately *not* "did the mean go up". Three facts about
this task make mean-improvement the wrong criterion:

* **The gain is reliability, not quality.** Across-run sigma falls by roughly
  an order of magnitude under adapters (0.081 -> 0.002-0.005) by preventing
  zero-score terminations. The quantity being optimised is the tail.
* **The tail is two tasks.** The reported held-out lift is driven by two
  catastrophic-failure rescues out of ten tasks. A mean gate cannot tell
  "rescued the tail" from "got lucky on the tail" at n=3.
* **Efficiency is a hard constraint.** The paper's own framing is that the
  adapter must not impose runtime overhead beyond the bare harness -- a guard
  against the over-specification failure mode of LLM-reflection-driven harness
  optimization. v1 exhibited exactly that failure mode (primer 270B -> 3159B
  over three unmonitored rounds), so it becomes a hard search constraint here
  rather than a post-hoc observation.

So: **no per-task cliff, no aggregate regression, no efficiency regression.**

The class implements GEPA's ``AcceptanceCriterion`` protocol structurally
(``should_accept(proposal, state)``) so it can be handed to ``gepa.optimize``
directly, but it has no import dependency on GEPA and is usable standalone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

DEFAULT_MAX_TASK_REGRESSION = 0.05
DEFAULT_MAX_MEAN_REGRESSION = 0.005
DEFAULT_MAX_EFFICIENCY_RATIO = 1.15


@dataclass
class GateResult:
    """Outcome of one accept/reject decision, with the reason recorded."""

    accepted: bool
    reasons: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.accepted

    @property
    def reason(self) -> str:
        return "; ".join(self.reasons) if self.reasons else "accepted"

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "reasons": list(self.reasons),
            "metrics": dict(self.metrics),
        }


@dataclass
class RegressionGate:
    """Self-Harness proposal validation, adapted to a tail-driven objective.

    Parameters
    ----------
    max_task_regression:
        Largest per-task drop tolerated on any anchor task. This is *the*
        clause: it makes "did anything fall off a cliff" the question, which is
        the operationalisation of "the gain is reliability, not quality".
    max_mean_regression:
        Small tolerance on the aggregate, so lateral moves that trade a little
        mean for tail safety can still be explored.
    max_efficiency_ratio:
        Hard ceiling on tool calls and wall-clock relative to the parent.
    require_zero_rate_non_increasing:
        Reject any candidate that introduces a new failures-as-zero
        termination, regardless of what it does to the mean. Under
        failures-as-zero a single such run is worth ~0.08 of cell sigma.
    """

    max_task_regression: float = DEFAULT_MAX_TASK_REGRESSION
    max_mean_regression: float = DEFAULT_MAX_MEAN_REGRESSION
    max_efficiency_ratio: float = DEFAULT_MAX_EFFICIENCY_RATIO
    require_zero_rate_non_increasing: bool = True

    # -- the gate ---------------------------------------------------------
    def evaluate(
        self,
        child_scores: Mapping[str, float],
        parent_scores: Mapping[str, float],
        *,
        child_cost: Mapping[str, float] | None = None,
        parent_cost: Mapping[str, float] | None = None,
        hygiene_ok: bool = True,
        checks_ok: bool = True,
    ) -> GateResult:
        reasons: list[str] = []
        metrics: dict[str, Any] = {}

        # (1)/(2) free gates -- these cost no rollouts and should kill most
        # bad proposals before any API spend.
        if not hygiene_ok:
            reasons.append("hygiene gate failed")
        if not checks_ok:
            reasons.append("check plugin failed its own test")

        common = sorted(set(child_scores) & set(parent_scores))
        metrics["n_common_tasks"] = len(common)
        if not common:
            reasons.append("no common tasks with parent (cannot compare)")
            return GateResult(False, reasons, metrics)

        deltas = {t: child_scores[t] - parent_scores[t] for t in common}
        worst_task = min(deltas, key=lambda t: deltas[t])
        worst = deltas[worst_task]
        mean_delta = sum(deltas.values()) / len(deltas)
        metrics.update(
            {
                "worst_task": worst_task,
                "worst_delta": worst,
                "mean_delta": mean_delta,
                "per_task_deltas": deltas,
            }
        )

        # (3) no per-task cliff
        if worst < -self.max_task_regression:
            reasons.append(
                f"per-task regression on {worst_task}: {worst:+.3f} "
                f"(limit -{self.max_task_regression:.3f})"
            )

        # (4) no aggregate regression
        if mean_delta < -self.max_mean_regression:
            reasons.append(
                f"aggregate regression: {mean_delta:+.4f} "
                f"(limit -{self.max_mean_regression:.4f})"
            )

        # (4b) no new zero-score terminations
        if self.require_zero_rate_non_increasing:
            child_zeros = {t for t in common if child_scores[t] <= 1e-9}
            parent_zeros = {t for t in common if parent_scores[t] <= 1e-9}
            new_zeros = sorted(child_zeros - parent_zeros)
            metrics["new_zero_tasks"] = new_zeros
            if new_zeros:
                reasons.append(
                    f"introduces failures-as-zero on {', '.join(new_zeros)}"
                )

        # (5) no efficiency regression
        if child_cost and parent_cost:
            for key in ("tool_calls", "wall_seconds", "output_tokens"):
                c, p = child_cost.get(key), parent_cost.get(key)
                if c is None or not p:
                    continue
                ratio = c / p
                metrics[f"{key}_ratio"] = ratio
                if ratio > self.max_efficiency_ratio:
                    reasons.append(
                        f"efficiency regression on {key}: {ratio:.2f}x "
                        f"(limit {self.max_efficiency_ratio:.2f}x)"
                    )

        return GateResult(not reasons, reasons, metrics)

    # -- GEPA AcceptanceCriterion protocol --------------------------------
    def should_accept(self, proposal: Any, state: Any) -> bool:
        before = list(getattr(proposal, "subsample_scores_before", None) or [])
        after = list(getattr(proposal, "subsample_scores_after", None) or [])
        if not before or len(before) != len(after):
            # Fall back to GEPA's default semantics when we cannot pair scores.
            return sum(after) > sum(before)
        ids = self._instance_ids(proposal, len(before))
        return bool(
            self.evaluate(
                dict(zip(ids, after)),
                dict(zip(ids, before)),
            )
        )

    def reject_reason(self, proposal: Any, state: Any) -> str:
        before = list(getattr(proposal, "subsample_scores_before", None) or [])
        after = list(getattr(proposal, "subsample_scores_after", None) or [])
        if not before or len(before) != len(after):
            return "unpaired subsample scores"
        ids = self._instance_ids(proposal, len(before))
        return self.evaluate(dict(zip(ids, after)), dict(zip(ids, before))).reason

    @staticmethod
    def _instance_ids(proposal: Any, n: int) -> Sequence[str]:
        ev = getattr(proposal, "eval_before", None)
        ids = getattr(ev, "instance_ids", None) if ev is not None else None
        if ids and len(ids) == n:
            return [str(i) for i in ids]
        return [f"i{k}" for k in range(n)]


@dataclass
class DecisionRecord:
    """One row of ``.evolve/decision_log.jsonl`` (AHE decision observability).

    Pairs the prediction a proposal made *before* evaluation with what actually
    happened, so the log doubles as a calibration record for the proposer model
    and as an over-specification detector: an accepted edit whose predicted
    beneficiaries did not move is over-specification wearing a disguise.
    """

    candidate_id: str
    parent_id: str | None
    component: str
    predicted_beneficiaries: list[str]
    predicted_delta: float
    observed_deltas: dict[str, float]
    gate: GateResult

    @property
    def prediction_hit_rate(self) -> float | None:
        if not self.predicted_beneficiaries:
            return None
        hits = sum(
            1
            for t in self.predicted_beneficiaries
            if self.observed_deltas.get(t, 0.0) > 0.01
        )
        return hits / len(self.predicted_beneficiaries)

    @property
    def is_unearned(self) -> bool:
        """Accepted, but none of its predicted beneficiaries actually moved."""
        hr = self.prediction_hit_rate
        return bool(self.gate.accepted and hr is not None and hr == 0.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "parent_id": self.parent_id,
            "component": self.component,
            "predicted_beneficiaries": self.predicted_beneficiaries,
            "predicted_delta": self.predicted_delta,
            "observed_deltas": self.observed_deltas,
            "prediction_hit_rate": self.prediction_hit_rate,
            "unearned": self.is_unearned,
            **self.gate.to_dict(),
        }
