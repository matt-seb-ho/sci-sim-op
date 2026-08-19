"""Markdown rendering of a compute-matched comparison, verdict first.

Two conventions this module refuses to break.

**Results are reported per model x harness configuration** (arXiv:2605.27922).
"System X scores Y" is not a reportable fact about this project: the same
adapter under a different stop policy, retry budget, or base model is a
different measurement, and the configuration header exists so a reader can tell
which one produced the table below it.

**The acceptance criterion is printed before the numbers.** Stating the rule
after seeing the data is how "+0.069 from self-evolution" became a headline
without a single compute-matched comparison behind it. :class:`VerdictCriterion`
renders above :class:`Verdict`, and the verdict is computed from the criterion
rather than written by hand.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping, Sequence

from harness_evolve.core.candidate import Candidate
from harness_evolve.evaluation.baselines import BudgetLedger, BudgetPlan
from harness_evolve.evaluation.protocol import EvaluationProtocol
from harness_evolve.evaluation.stats import Comparison

__all__ = [
    "ArmConfig",
    "EvaluationReport",
    "Verdict",
    "VerdictCriterion",
    "VerdictOutcome",
    "decide",
]

#: Verdict outcomes. ``mechanism_only`` and ``indeterminate`` exist because at
#: n=10 with two movers they are the *likely* honest answers, and collapsing
#: them into "survives"/"fails" would force a binary the data cannot support.
VerdictOutcome = Literal["survives", "mechanism_only", "indeterminate", "fails"]

OUTCOME_BLURB: Mapping[str, str] = {
    "survives": "Beats the control and every compute-matched task-level baseline, with paired statistical support.",
    "mechanism_only": "Beats the control and the baselines on the tail mechanism (rescues, zero rate), but the paired tests are too underpowered to confirm it. Report as a mechanism observation, not as a measured gain.",
    "indeterminate": "The comparison cannot distinguish the arms. This is a statement about the design's power, not evidence of no effect.",
    "fails": "A compute-matched baseline matched or beat the evolved candidate, or the control was not beaten.",
}


@dataclass(frozen=True)
class ArmConfig:
    """The full model x harness configuration behind one column of numbers."""

    key: str
    label: str
    model: str
    harness: str
    adapter_cid: str = ""
    generation: int = 0
    stop_policy: str = ""
    simulator: str = ""
    seeds: tuple[int, ...] = ()
    scaling: str = "none"
    notes: str = ""

    @classmethod
    def from_candidate(
        cls,
        key: str,
        candidate: Candidate,
        *,
        label: str,
        model: str,
        harness: str,
        simulator: str = "",
        seeds: Sequence[int] = (),
        scaling: str = "none",
        notes: str = "",
    ) -> "ArmConfig":
        """Read the harness half of the configuration off the candidate itself.

        Derived rather than passed in, so a report cannot describe a stop policy
        the run did not use.
        """
        sp = candidate.manifest.stop_policy
        return cls(
            key=key,
            label=label,
            model=model,
            harness=harness,
            adapter_cid=candidate.cid,
            generation=candidate.generation,
            stop_policy=(
                f"retries={sp.retries}, feedback={sp.feedback_shape}, "
                f"checks={'+'.join(sp.checks)}"
            ),
            simulator=simulator,
            seeds=tuple(seeds),
            scaling=scaling,
            notes=notes,
        )

    def row(self) -> str:
        return (
            f"| {self.label} | {self.model} | {self.harness} | {self.adapter_cid} | "
            f"g{self.generation} | {self.stop_policy} | {self.simulator} | "
            f"{list(self.seeds)} | {self.scaling} | {self.notes} |"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "label": self.label,
            "model": self.model,
            "harness": self.harness,
            "adapter_cid": self.adapter_cid,
            "generation": self.generation,
            "stop_policy": self.stop_policy,
            "simulator": self.simulator,
            "seeds": list(self.seeds),
            "scaling": self.scaling,
            "notes": self.notes,
        }


CONFIG_HEADER = (
    "| arm | model | harness | adapter | gen | stop policy | simulator | seeds | test-time scaling | notes |\n"
    "|---|---|---|---|---|---|---|---|---|---|"
)


@dataclass(frozen=True)
class VerdictCriterion:
    """The acceptance rule, fixed before the numbers are read.

    Four conditions, in the order they are checked:

    1. **Control.** The evolved candidate must beat the seed adapter at equal
       seeds on paired per-task deltas: more wins than losses at the noise band
       and no task pushed below the catastrophic threshold.
    2. **Compute match.** Every baseline it is compared against must be matched
       to the search's spend in ``budget_unit`` within ``tolerance``, per the
       ledger. An unmatched baseline cannot support or refute anything.
    3. **Baselines.** No compute-matched task-level baseline may match or beat
       it. This is the condition the predecessor system never tested and the one
       the critique says usually fails.
    4. **Support.** Either a bootstrap CI excluding zero or a powered
       permutation rejection. Where the guard rails refuse -- which is expected
       at n=10 with two movers -- the best available outcome is
       ``mechanism_only``, never ``survives``.
    """

    alpha: float = 0.05
    confidence: float = 0.95
    budget_unit: str = "rollouts"
    tolerance: float = 0.10
    require_no_new_catastrophes: bool = True

    def render(self) -> str:
        return "\n".join(
            [
                "### Criterion (fixed before the numbers below)",
                "",
                "1. **Beats the honest control.** Paired per-task comparison against the "
                "seed adapter at the same seed count: wins > losses at the derived noise "
                "band"
                + (", and no task newly pushed below the catastrophic threshold."
                   if self.require_no_new_catastrophes else "."),
                f"2. **Budget is matched and audited.** Every baseline within "
                f"{self.tolerance:.0%} of the search's spend in `{self.budget_unit}`, "
                "per the ledger below.",
                "3. **Beats every compute-matched task-level baseline.** Best-of-k "
                "(oracle *and* realizable selector) and sequential refinement. A tie "
                "counts as a failure: equal score at equal compute is not better design.",
                f"4. **Paired statistical support.** A {self.confidence:.0%} bootstrap CI "
                f"on the per-task deltas excluding zero, or a permutation test rejecting "
                f"at alpha={self.alpha:.2f} while powered enough to do so.",
                "",
                "If 1-3 hold but 4 does not, the outcome is `mechanism_only`: the tail "
                "mechanism is visible but the design cannot measure it. If 1 or 3 fails, "
                "the outcome is `fails`.",
            ]
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "alpha": self.alpha,
            "confidence": self.confidence,
            "budget_unit": self.budget_unit,
            "tolerance": self.tolerance,
            "require_no_new_catastrophes": self.require_no_new_catastrophes,
        }


@dataclass(frozen=True)
class Verdict:
    """The outcome of applying a :class:`VerdictCriterion`, with its reasons."""

    outcome: VerdictOutcome
    criterion: VerdictCriterion
    reasons: tuple[str, ...]
    unmatched_arms: tuple[str, ...] = ()

    def render(self) -> str:
        lines = [
            "### Does this survive a compute-matched comparison?",
            "",
            f"**Verdict: `{self.outcome}`.** {OUTCOME_BLURB[self.outcome]}",
            "",
        ]
        lines += [f"- {r}" for r in self.reasons]
        if self.unmatched_arms:
            lines += [
                "",
                f"Arms whose budget was not matched in `{self.criterion.budget_unit}`: "
                f"{list(self.unmatched_arms)}. Their comparisons are reported but "
                "carry no weight in this verdict.",
            ]
        return "\n".join(lines)

    def to_dict(self) -> dict[str, object]:
        return {
            "outcome": self.outcome,
            "criterion": self.criterion.to_dict(),
            "reasons": list(self.reasons),
            "unmatched_arms": list(self.unmatched_arms),
        }


def decide(
    criterion: VerdictCriterion,
    *,
    vs_control: Comparison,
    vs_baselines: Mapping[str, Comparison],
    ledger: BudgetLedger | None = None,
    search_arm: str = "search",
) -> Verdict:
    """Apply the criterion. ``Comparison`` treatment is always the evolved candidate.

    Budget matching is read from the ledger rather than trusted: an arm the
    ledger cannot vouch for is dropped from the decision and named in the
    verdict, because a baseline that quietly spent half the compute would
    otherwise manufacture exactly the result being tested for.
    """
    reasons: list[str] = []

    # 1. control
    wlt = vs_control.wlt
    control_beaten = len(wlt.wins) > len(wlt.losses) and vs_control.mean_delta > 0
    reasons.append(
        f"(1) control: {wlt.render()}, mean delta {vs_control.mean_delta:+.4f} -> "
        + ("passes" if control_beaten else "**fails**")
    )
    new_catastrophes = tuple(
        t
        for t in vs_control.tail_treatment.tasks_with_any_catastrophe
        if t not in vs_control.tail_baseline.tasks_with_any_catastrophe
    )
    if criterion.require_no_new_catastrophes and new_catastrophes:
        control_beaten = False
        reasons.append(
            f"(1) control: tasks newly below the catastrophic threshold: "
            f"{list(new_catastrophes)} -> **fails**"
        )

    # 2. budget match
    unmatched: list[str] = []
    if ledger is not None and vs_baselines:
        try:
            matches = {m.arm: m for m in ledger.match(search_arm, tolerance=criterion.tolerance)}
        except KeyError:
            matches = {}
            reasons.append(
                f"(2) budget: no spend recorded for the search arm {search_arm!r}; "
                "no baseline can be certified as matched"
            )
            unmatched = list(vs_baselines)
        for key in vs_baselines:
            m = matches.get(key)
            if m is None:
                if key not in unmatched:
                    unmatched.append(key)
                continue
            if criterion.budget_unit in m.matched_units:
                reasons.append(
                    f"(2) budget: `{key}` matched in {criterion.budget_unit} "
                    f"({m.ratios[criterion.budget_unit]:.2f}x)"
                )
            else:
                unmatched.append(key)
                ratio = m.ratios.get(criterion.budget_unit)
                reasons.append(
                    f"(2) budget: `{key}` **not matched** in {criterion.budget_unit}"
                    + (f" ({ratio:.2f}x)" if ratio is not None else " (unmeasured)")
                )
    elif vs_baselines:
        unmatched = list(vs_baselines)
        reasons.append("(2) budget: no ledger supplied, so no match can be audited")

    # 3. baselines
    counted = {k: c for k, c in vs_baselines.items() if k not in unmatched}
    baselines_beaten = True
    if not counted:
        baselines_beaten = False
        reasons.append(
            "(3) baselines: no budget-matched task-level baseline was available -- "
            "the central question is untested"
        )
    for key, comp in counted.items():
        beat = comp.mean_delta > 0 and len(comp.wlt.wins) > len(comp.wlt.losses)
        baselines_beaten = baselines_beaten and beat
        reasons.append(
            f"(3) vs `{key}`: mean delta {comp.mean_delta:+.4f}, {comp.wlt.render()} -> "
            + ("passes" if beat else "**fails**")
        )

    # 4. support
    supported = vs_control.conclusive and all(c.conclusive for c in counted.values())
    reasons.append(
        "(4) support: control "
        + vs_control.bootstrap.render()
        + "; "
        + vs_control.permutation.render()
        + " -> "
        + ("passes" if supported else "**not established**")
    )

    mechanism = (
        vs_control.rescues.net_rescues > 0
        and not vs_control.rescues.lost
        and vs_control.zero_rate_delta <= 0
        and all(c.rescues.net_rescues >= 0 for c in counted.values())
    )
    reasons.append(
        "(4b) mechanism: " + vs_control.rescues.render() + "; zero-rate change "
        f"{vs_control.zero_rate_delta:+.3f} -> "
        + ("visible" if mechanism else "not visible")
    )

    if not control_beaten or not baselines_beaten:
        outcome: VerdictOutcome = "fails"
    elif supported:
        outcome = "survives"
    elif mechanism:
        outcome = "mechanism_only"
    else:
        outcome = "indeterminate"
    return Verdict(
        outcome=outcome,
        criterion=criterion,
        reasons=tuple(reasons),
        unmatched_arms=tuple(dict.fromkeys(unmatched)),
    )


@dataclass
class EvaluationReport:
    """A full comparison rendered as one markdown document.

    Holds only values already computed elsewhere: no statistic is calculated
    during rendering, so the numbers in the document are exactly the numbers the
    protocol produced.
    """

    title: str
    treatment_key: str
    configs: Mapping[str, ArmConfig]
    comparisons: Mapping[str, Comparison]
    control_key: str = "seed_control"
    ledger: BudgetLedger | None = None
    search_arm: str = "search"
    plan: BudgetPlan | None = None
    criterion: VerdictCriterion = field(default_factory=VerdictCriterion)
    protocol: EvaluationProtocol | None = None
    slice_name: str = "held_out"
    selector_gaps: Mapping[str, float] = field(default_factory=dict)
    caveats: tuple[str, ...] = ()

    # -- pieces ----------------------------------------------------------
    def verdict(self) -> Verdict:
        if self.control_key not in self.comparisons:
            raise KeyError(
                f"no comparison against the control arm {self.control_key!r}; the "
                "control is the one arm the report cannot be written without"
            )
        return decide(
            self.criterion,
            vs_control=self.comparisons[self.control_key],
            vs_baselines={
                k: c for k, c in self.comparisons.items() if k != self.control_key
            },
            ledger=self.ledger,
            search_arm=self.search_arm,
        )

    def _config_section(self) -> str:
        lines = [
            "## Configurations compared",
            "",
            "Every row is one model x harness configuration. Numbers below belong to "
            "a row, never to a system name.",
            "",
            CONFIG_HEADER,
        ]
        for key in [self.treatment_key] + [
            k for k in self.configs if k != self.treatment_key
        ]:
            cfg = self.configs.get(key)
            if cfg is not None:
                lines.append(cfg.row())
        return "\n".join(lines)

    def _per_task_section(self) -> str:
        control = self.comparisons[self.control_key]
        band = control.wlt.noise_band
        lines = [
            "## Per-task paired results",
            "",
            f"Slice: `{self.slice_name}`; per-task summary across seeds: "
            f"`{control.aggregator}` (worst seed in parentheses). "
            f"Noise band +-{band:.4f} ({control.wlt.band_source}).",
            "",
        ]
        arm_keys = [self.control_key] + [
            k for k in self.comparisons if k != self.control_key
        ]
        header = ["task", f"{control.treatment.label} (min)"]
        for k in arm_keys:
            header.append(f"{self.comparisons[k].baseline.label} (min)")
        for k in arm_keys:
            header.append(f"delta vs {k}")
        header.append("vs control")
        lines.append("| " + " | ".join(header) + " |")
        lines.append("|" + "---|" * len(header))

        treat = control.treatment
        for task in treat.tasks:
            row = [
                task,
                f"{treat.aggregate(task):.3f} ({min(treat.values(task)):.3f})",
            ]
            for k in arm_keys:
                arm = self.comparisons[k].baseline
                row.append(
                    f"{arm.aggregate(task):.3f} ({min(arm.values(task)):.3f})"
                )
            for k in arm_keys:
                pair = next(p for p in self.comparisons[k].pairs if p.task == task)
                row.append(f"{pair.delta:+.3f}")
            d = next(p for p in control.pairs if p.task == task).delta
            row.append("W" if d > band else ("L" if d < -band else "T"))
            lines.append("| " + " | ".join(row) + " |")
        lines += [
            "",
            f"Win/loss/tie vs control: **{control.wlt.render()}**. "
            "The tie count is a headline number: a mean delta built from a couple of "
            "tasks is a different claim from a broad improvement.",
        ]
        return "\n".join(lines)

    def _stats_section(self) -> str:
        lines = ["## Paired statistics", ""]
        for key, comp in self.comparisons.items():
            lines += [
                f"### {comp.treatment.label} vs {comp.baseline.label} (`{key}`)",
                "",
                f"- mean paired delta: **{comp.mean_delta:+.4f}**",
                f"- bootstrap: {comp.bootstrap.render()}",
                f"- permutation: {comp.permutation.render()}",
                f"- effect size: {comp.effects.render()}",
                f"- win/loss/tie: {comp.wlt.render()}",
                f"- rescues: {comp.rescues.render()}",
                "",
            ]
        return "\n".join(lines).rstrip()

    def _tail_section(self) -> str:
        control = self.comparisons[self.control_key]
        arms = [("treatment", control.treatment, control.tail_treatment)]
        for key, comp in self.comparisons.items():
            arms.append((key, comp.baseline, comp.tail_baseline))
        lines = [
            "## Tail statistics",
            "",
            "The claimed effect is a variance collapse driven by zero-score runs, so "
            "these are primary results. A mean is a lossy projection of them.",
            "",
            "| arm | runs | zero rate | zero-rate 95% CI (task-clustered) | naive Wilson CI | "
            f"runs < {control.tail_treatment.catastrophic_threshold:.2f} | tasks with any catastrophe | "
            "mean per-task min | pooled across-seed SD |",
            "|---|---:|---:|---|---|---:|---|---:|---:|",
        ]
        for key, arm, tail in arms:
            ci = (
                tail.zero_rate_ci.interval.render()
                if tail.zero_rate_ci.reportable
                else f"refused ({tail.zero_rate_ci.refusal})"
            )
            lines.append(
                f"| {arm.label} | {tail.n_runs} | {tail.zero_rate:.3f} | {ci} | "
                f"{tail.zero_rate_ci_naive.render()} | {tail.catastrophic_runs} | "
                f"{list(tail.tasks_with_any_catastrophe)} | {tail.mean_per_task_min:.3f} | "
                f"{tail.pooled_seed_sd:.4f} |"
            )
        return "\n".join(lines)

    def _budget_section(self) -> str:
        lines = ["## Budget ledger", ""]
        if self.plan is not None:
            lines += [f"Plan: {self.plan.note}.", ""]
        if self.ledger is None:
            lines += [
                "**No ledger supplied.** Without one, no claim in this report is "
                "compute-matched; the comparison is descriptive only.",
            ]
            return "\n".join(lines)
        lines.append(self.ledger.render_markdown(reference=self.search_arm))
        lines += [
            "",
            "`attempts` counts agent attempts inside rollouts (initial try plus stop-hook "
            "retries). Parallel and sequential scaling are not matchable in the same "
            "unit, so both are reported and the verdict names the unit it uses.",
        ]
        if self.selector_gaps:
            lines += [
                "",
                "Selector gap (oracle minus realizable, mean over cells): "
                + ", ".join(f"`{k}` {v:+.3f}" for k, v in sorted(self.selector_gaps.items()))
                + ". A large gap means the parallel-sampling number is an upper bound "
                "no deployment could realize.",
            ]
        return "\n".join(lines)

    # -- assembly --------------------------------------------------------
    def render(self) -> str:
        """Render the whole report. Verdict criterion precedes every number."""
        verdict = self.verdict()
        parts = [
            f"# {self.title}",
            "",
            self._config_section(),
            "",
            self.criterion.render(),
            "",
            self._budget_section(),
            "",
            self._per_task_section(),
            "",
            self._stats_section(),
            "",
            self._tail_section(),
            "",
            verdict.render(),
        ]
        if self.caveats:
            parts += ["", "## Caveats", ""] + [f"- {c}" for c in self.caveats]
        if self.protocol is not None:
            parts += ["", "## Slice audit trail", "", self.protocol.render_audit()]
        return "\n".join(parts) + "\n"

    def to_dict(self) -> dict[str, object]:
        return {
            "title": self.title,
            "treatment": self.treatment_key,
            "configs": {k: c.to_dict() for k, c in self.configs.items()},
            "comparisons": {k: c.to_dict() for k, c in self.comparisons.items()},
            "ledger": self.ledger.to_dict() if self.ledger else None,
            "plan": self.plan.to_dict() if self.plan else None,
            "verdict": self.verdict().to_dict(),
            "protocol": self.protocol.to_dict() if self.protocol else None,
            "selector_gaps": dict(self.selector_gaps),
            "caveats": list(self.caveats),
        }
