"""The layered evidence corpus: what the proposer is actually allowed to see.

v1 handed its proposer a 2500-character list of tool names with truncated
arguments. No observations, no errors, no validator output, no failure
classification, no per-section scores -- and, through a separate bug, no reward
either. It then asked that proposer to explain why the run had regressed. The
replacement is the "experience observability" structure of arXiv:2604.25850:
millions of raw trajectory tokens reorganised into a layered drill-down corpus
an evolving agent can consume top-down.

Four levels, each answering one question:

* **L0 aggregate** -- is this candidate better than its parent, and how
  reliably? Headline quantity is the **zero-rate**, not sigma: the whole
  reliability story here is about preventing failure-as-zero terminations, and
  sigma is a downstream consequence of that rate rather than the thing itself.
* **L1 per task** -- which tasks moved, in which direction.
* **L2 failure** -- for the tasks that are losing score, *what* is wrong:
  weakest sections, worst subtrees by impact, missing/extra element types,
  failure category.
* **L3 drill-down** -- for **one named task, fetched on demand**: tail
  trajectory excerpt, mined trajectory features, EFC breakdown, and the
  validator's output **verbatim**.

L3 being on-demand is the design point. v1 capped the whole context at 2500
characters because everything was dumped at once, and the cap is what destroyed
the signal. Fetching one task's detail only when the proposer asks for it means
that detail can be complete -- an unabridged GEOS unknown-attribute error
prints the entire table of valid attributes, and that table is the single
highest-quality feedback the harness produces.

The corpus is built from ``list[Rollout]`` plus optional ``Diagnosis`` objects,
so it is indifferent to which simulator scored the run and which runner
produced it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from statistics import fmean, pstdev
from typing import Any, Iterable, Mapping, Sequence

from harness_evolve.evidence.diagnostics import (
    MiningConfig,
    TrajectoryFeatures,
    mine_trajectory,
    render_excerpt,
    trajectory_excerpt,
)
from harness_evolve.evidence.efc import EFCConfig, EFCReport, efc_report
from harness_evolve.simulators.base import Diagnosis
from harness_evolve.types import CandidateId, Cost, Rollout, TaskId

__all__ = ["CorpusConfig", "RoundEvidence", "TaskEvidence", "build_evidence"]


@dataclass(frozen=True)
class CorpusConfig:
    """Rendering and mining knobs for one corpus.

    ``max_validator_chars = 0`` means *no cap*, which is deliberate: the global
    character cap is the thing this design exists to remove, and the on-demand
    L3 fetch is what makes removing it safe. The knob stays so a caller facing
    a pathological validator can bound it explicitly rather than discovering a
    silent truncation.
    """

    mining: MiningConfig = field(default_factory=MiningConfig)
    efc: EFCConfig = field(default_factory=EFCConfig)
    #: Written by the stop hook next to the agent workspace; resolved relative
    #: to ``Rollout.artifacts_dir`` when present.
    hook_events_filename: str = ".verify_hook_events.jsonl"
    tail_turns: int = 10
    #: A task is shown at L2 if it scores below this, has any zero, or regressed.
    l2_score_threshold: float = 0.8
    max_l2_tasks: int = 6
    max_subtrees: int = 5
    max_sections: int = 5
    max_elements: int = 8
    max_validator_chars: int = 0


def _fmt_delta(delta: float | None) -> str:
    return "  n/a" if delta is None else f"{delta:+.3f}"


@dataclass
class TaskEvidence:
    """Everything known about one task under one candidate, across seeds."""

    task: TaskId
    rollouts: list[Rollout] = field(default_factory=list)
    diagnosis: Diagnosis | None = None
    parent_mean: float | None = None
    #: seed -> EFC report, populated only by :meth:`RoundEvidence.compute_efc`.
    efc_reports: dict[int, EFCReport] = field(default_factory=dict)

    @property
    def n(self) -> int:
        return len(self.rollouts)

    @property
    def values(self) -> list[float]:
        return [r.score.value for r in self.rollouts]

    @property
    def mean(self) -> float:
        return fmean(self.values) if self.rollouts else 0.0

    @property
    def sigma(self) -> float:
        """Across-seed population sigma. Zero for a single seed, not undefined."""
        return pstdev(self.values) if len(self.rollouts) > 1 else 0.0

    @property
    def n_zero(self) -> int:
        return sum(1 for r in self.rollouts if r.score.is_zero)

    @property
    def zero_rate(self) -> float:
        return self.n_zero / self.n if self.n else 0.0

    @property
    def delta(self) -> float | None:
        """Mean score minus the parent's mean on this task, or None if new."""
        return None if self.parent_mean is None else self.mean - self.parent_mean

    @property
    def statuses(self) -> list[str]:
        return sorted({r.score.status for r in self.rollouts})

    @property
    def cost(self) -> Cost:
        total = Cost()
        for rollout in self.rollouts:
            total = total + rollout.cost
        return total

    @property
    def mean_efc(self) -> float | None:
        return fmean(r.efc for r in self.efc_reports.values()) if self.efc_reports else None

    def worst_rollout(self) -> Rollout | None:
        """The rollout worth drilling into: lowest score, earliest seed on a tie."""
        if not self.rollouts:
            return None
        return min(self.rollouts, key=lambda r: (r.score.value, r.seed))

    def rollout_for_seed(self, seed: int) -> Rollout | None:
        for rollout in self.rollouts:
            if rollout.seed == seed:
                return rollout
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "n": self.n,
            "mean": self.mean,
            "sigma": self.sigma,
            "zero_rate": self.zero_rate,
            "delta": self.delta,
            "statuses": self.statuses,
            "mean_efc": self.mean_efc,
            "category": self.diagnosis.category if self.diagnosis else None,
        }


@dataclass
class RoundEvidence:
    """The corpus for one candidate's round, rendered level by level.

    Constructed through :func:`build_evidence` or :meth:`from_rollouts`; the
    proposer receives one of these and nothing else.
    """

    candidate_id: CandidateId = ""
    parent_id: CandidateId | None = None
    tasks: dict[TaskId, TaskEvidence] = field(default_factory=dict)
    config: CorpusConfig = field(default_factory=CorpusConfig)
    notes: list[str] = field(default_factory=list)
    _features_cache: dict[tuple[TaskId, int], TrajectoryFeatures] = field(
        default_factory=dict, repr=False
    )

    # -- construction ----------------------------------------------------
    @classmethod
    def from_rollouts(
        cls,
        rollouts: Iterable[Rollout],
        *,
        candidate_id: CandidateId | None = None,
        parent: "RoundEvidence | None" = None,
        parent_scores: Mapping[TaskId, float] | None = None,
        diagnoses: Mapping[TaskId, Diagnosis] | None = None,
        config: CorpusConfig | None = None,
    ) -> "RoundEvidence":
        """Group rollouts by task and attach diagnoses and parent baselines.

        ``parent`` and ``parent_scores`` are alternatives: pass the parent's own
        corpus when you have it, or a bare task -> mean mapping when all you
        kept was the numbers. Passing both prefers ``parent_scores``, so a
        caller can override a stale corpus without rebuilding it.
        """
        rollouts = list(rollouts)
        evidence = cls(
            candidate_id=candidate_id or (rollouts[0].candidate_id if rollouts else ""),
            parent_id=parent.candidate_id if parent else None,
            config=config or CorpusConfig(),
        )
        baseline: dict[TaskId, float] = {}
        if parent is not None:
            baseline = {t: te.mean for t, te in parent.tasks.items()}
        if parent_scores is not None:
            baseline.update(parent_scores)

        for rollout in rollouts:
            task = evidence.tasks.setdefault(rollout.task, TaskEvidence(task=rollout.task))
            task.rollouts.append(rollout)
        for task_id, task in evidence.tasks.items():
            task.rollouts.sort(key=lambda r: r.seed)
            task.parent_mean = baseline.get(task_id)
            if diagnoses and task_id in diagnoses:
                task.diagnosis = diagnoses[task_id]

        if baseline:
            unseen = sorted(set(baseline) - set(evidence.tasks))
            if unseen:
                evidence.notes.append(
                    "parent scored tasks this candidate has no rollouts for: "
                    + ", ".join(unseen)
                )
        return evidence

    # -- aggregate statistics -------------------------------------------
    @property
    def rollouts(self) -> list[Rollout]:
        return [r for t in self.tasks.values() for r in t.rollouts]

    @property
    def n_rollouts(self) -> int:
        return sum(t.n for t in self.tasks.values())

    @property
    def mean(self) -> float:
        """Mean over *tasks*, not over rollouts.

        Task-weighted so an unevenly seeded slice does not silently reweight the
        objective toward whichever task happened to get more runs.
        """
        return fmean([t.mean for t in self.tasks.values()]) if self.tasks else 0.0

    @property
    def sigma(self) -> float:
        """Pooled population sigma over every rollout score."""
        values = [r.score.value for r in self.rollouts]
        return pstdev(values) if len(values) > 1 else 0.0

    @property
    def mean_task_sigma(self) -> float:
        """Mean across-seed sigma: the "across-run variability" the adapters cut."""
        per_task = [t.sigma for t in self.tasks.values() if t.n > 1]
        return fmean(per_task) if per_task else 0.0

    @property
    def n_zero(self) -> int:
        return sum(t.n_zero for t in self.tasks.values())

    @property
    def zero_rate(self) -> float:
        """Fraction of rollouts that scored zero. The headline reliability number."""
        return self.n_zero / self.n_rollouts if self.n_rollouts else 0.0

    @property
    def parent_mean(self) -> float | None:
        means = [t.parent_mean for t in self.tasks.values() if t.parent_mean is not None]
        return fmean(means) if means else None

    @property
    def total_cost(self) -> Cost:
        total = Cost()
        for rollout in self.rollouts:
            total = total + rollout.cost
        return total

    @property
    def mean_efc(self) -> float | None:
        per_task = [t.mean_efc for t in self.tasks.values() if t.mean_efc is not None]
        return fmean(per_task) if per_task else None

    def regressions(self, threshold: float = 0.0) -> list[TaskEvidence]:
        """Tasks whose mean fell below the parent's by more than ``threshold``."""
        return sorted(
            (t for t in self.tasks.values() if t.delta is not None and t.delta < -threshold),
            key=lambda t: t.delta or 0.0,
        )

    def worst_tasks(self, k: int = 5) -> list[TaskEvidence]:
        return sorted(self.tasks.values(), key=lambda t: (t.mean, t.task))[:k]

    def ordered_tasks(self) -> list[TaskEvidence]:
        """Tasks worst-first: attention belongs on the tail, which is the whole effect."""
        return sorted(self.tasks.values(), key=lambda t: (t.mean, t.task))

    # -- EFC -------------------------------------------------------------
    def compute_efc(self) -> dict[TaskId, float]:
        """Mine every rollout's trajectory and attach its EFC report.

        Separate from construction because it walks the filesystem: L0-L2 render
        from in-memory rollouts alone, and a caller that only wants the summary
        should not pay for trajectory IO. Returns task -> mean EFC.
        """
        out: dict[TaskId, float] = {}
        for task in self.tasks.values():
            for rollout in task.rollouts:
                features = self._features(task, rollout)
                task.efc_reports[rollout.seed] = efc_report(
                    features,
                    validator_events=rollout.validator_events,
                    cost=rollout.cost,
                    config=self.config.efc,
                )
            mean = task.mean_efc
            if mean is not None:
                out[task.task] = mean
        return out

    def _features(self, task: TaskEvidence, rollout: Rollout) -> TrajectoryFeatures:
        key = (task.task, rollout.seed)
        cached = self._features_cache.get(key)
        if cached is None:
            hook_path: str | None = None
            if rollout.artifacts_dir and self.config.hook_events_filename:
                hook_path = str(Path(rollout.artifacts_dir) / self.config.hook_events_filename)
            cached = mine_trajectory(
                rollout.events_path,
                hook_events_path=hook_path,
                config=self.config.mining,
            )
            self._features_cache[key] = cached
        return cached

    # -- rendering -------------------------------------------------------
    def render(self, level: int = 2, task: TaskId | None = None) -> str:
        """Proposer-facing text through ``level``, plus one task's L3 if named.

        Levels are cumulative: ``render(2)`` is L0 + L1 + L2. ``level >= 3``
        without a ``task`` renders the drill-down *menu* rather than every
        task's detail -- the menu is the affordance that makes the fetch
        on-demand instead of a dump.
        """
        parts = [self._render_header(), self._render_l0()]
        if level >= 1:
            parts.append(self._render_l1())
        if level >= 2:
            parts.append(self._render_l2())
        if level >= 3 and task is None:
            parts.append(self._render_l3_menu())
        if task is not None:
            parts.append(self.drill_down(task))
        return "\n\n".join(p for p in parts if p)

    def _render_header(self) -> str:
        parent = self.parent_id or "(none)"
        return (
            f"# evidence corpus — candidate {self.candidate_id or '(unnamed)'} "
            f"(parent {parent})"
        )

    def _render_l0(self) -> str:
        parent_mean = self.parent_mean
        delta = None if parent_mean is None else self.mean - parent_mean
        cost = self.total_cost
        lines = [
            "## L0 — aggregate",
            f"tasks {len(self.tasks)} × rollouts {self.n_rollouts}",
            f"mean score      {self.mean:.3f}"
            + (f"   (parent {parent_mean:.3f}, delta {_fmt_delta(delta)})" if parent_mean is not None else ""),
            f"zero-rate       {self.zero_rate:.3f}   ({self.n_zero}/{self.n_rollouts} rollouts "
            f"scored zero)   <-- headline reliability quantity",
            f"sigma (pooled)  {self.sigma:.3f}    across-seed sigma (mean over tasks) "
            f"{self.mean_task_sigma:.3f}",
            f"cost            tool_calls={cost.tool_calls:g} wall={cost.wall_seconds:g}s "
            f"in_tok={cost.input_tokens:g} out_tok={cost.output_tokens:g} usd={cost.usd:.2f}",
        ]
        mean_efc = self.mean_efc
        if mean_efc is not None:
            lines.append(f"EFC (mean/task) {mean_efc:.2f}")
        deltas = [t for t in self.ordered_tasks() if t.delta is not None]
        if deltas:
            lines.append(
                "per-task delta vs parent: "
                + "  ".join(f"{t.task}{_fmt_delta(t.delta)}" for t in deltas)
            )
        regressed = self.regressions()
        if regressed:
            lines.append(
                "REGRESSIONS: "
                + ", ".join(f"{t.task} {_fmt_delta(t.delta)}" for t in regressed)
            )
        lines.extend(f"note: {n}" for n in self.notes)
        return "\n".join(lines)

    def _render_l1(self) -> str:
        show_efc = self.mean_efc is not None
        header = f"{'task':<28} {'n':>2} {'mean':>6} {'sigma':>6} {'zero':>5} {'delta':>7}  status"
        if show_efc:
            header = (
                f"{'task':<28} {'n':>2} {'mean':>6} {'sigma':>6} {'zero':>5} "
                f"{'delta':>7} {'EFC':>6}  status"
            )
        lines = ["## L1 — per task (worst first)", header]
        for task in self.ordered_tasks():
            row = (
                f"{task.task:<28} {task.n:>2} {task.mean:>6.3f} {task.sigma:>6.3f} "
                f"{task.n_zero}/{task.n:<3} {_fmt_delta(task.delta):>7}"
            )
            if show_efc:
                mean_efc = task.mean_efc
                row += f" {mean_efc:>6.2f}" if mean_efc is not None else f" {'-':>6}"
            row += "  " + ",".join(task.statuses)
            lines.append(row)
        return "\n".join(lines)

    def _l2_tasks(self) -> list[TaskEvidence]:
        """Tasks worth explaining: anything failing, zeroed, or regressed."""
        selected = [
            t
            for t in self.ordered_tasks()
            if t.n_zero
            or t.mean < self.config.l2_score_threshold
            or (t.delta is not None and t.delta < 0)
            or (t.diagnosis is not None and t.diagnosis.category not in (None, "no_failure"))
        ]
        return selected[: self.config.max_l2_tasks]

    def _render_l2(self) -> str:
        selected = self._l2_tasks()
        if not selected:
            return "## L2 — failure detail\n(no task is failing, zeroed, or regressed)"
        lines = [f"## L2 — failure detail ({len(selected)} task(s))"]
        for task in selected:
            lines.append(self._render_l2_task(task))
        lines.append(
            'drill down with render(level=3, task="<task>") for the tail trajectory, '
            "mined features, EFC breakdown, and verbatim validator output"
        )
        return "\n".join(lines)

    def _render_l2_task(self, task: TaskEvidence) -> str:
        cfg = self.config
        diagnosis = task.diagnosis
        head = (
            f"### {task.task}  mean={task.mean:.3f} zeros={task.n_zero}/{task.n} "
            f"delta={_fmt_delta(task.delta)} "
            f"category={(diagnosis.category if diagnosis else None) or 'unclassified'}"
        )
        lines = [head]
        if diagnosis is None:
            lines.append("  (no diagnosis: the simulator returned none for this task)")
            failed = [r for r in task.rollouts if r.error]
            for rollout in failed[:2]:
                lines.append(f"  seed {rollout.seed} error: {rollout.error}")
            return "\n".join(lines)

        weakest = diagnosis.weakest_sections(cfg.max_sections)
        if weakest:
            lines.append(
                "  weakest sections: "
                + ", ".join(f"{name} {score:.2f}" for name, score in weakest)
            )
        for subtree in diagnosis.worst_subtrees[: cfg.max_subtrees]:
            lines.append("  worst subtree: " + _fmt_subtree(subtree))
        if diagnosis.missing_elements:
            lines.append(
                f"  missing element types ({len(diagnosis.missing_elements)}): "
                + ", ".join(diagnosis.missing_elements[: cfg.max_elements])
            )
        if diagnosis.extra_elements:
            lines.append(
                f"  extra element types ({len(diagnosis.extra_elements)}, "
                f"n_extra={diagnosis.n_extra}): "
                + ", ".join(diagnosis.extra_elements[: cfg.max_elements])
            )
        for note in diagnosis.notes:
            lines.append(f"  note: {note}")
        return "\n".join(lines)

    def _render_l3_menu(self) -> str:
        names = ", ".join(t.task for t in self._l2_tasks()) or ", ".join(self.tasks)
        return (
            "## L3 — drill-down (on demand)\n"
            "not rendered by default: one task's full detail is larger than every "
            "level above it combined.\n"
            f'request one with render(level=3, task="<task>"); suggested: {names}'
        )

    def drill_down(self, task: TaskId, seed: int | None = None) -> str:
        """Full detail for one task: the L3 layer, fetched only when asked for.

        Defaults to the task's worst-scoring rollout, since a candidate's tail
        is what selection is about and the best seed explains nothing. Validator
        output is reproduced verbatim.
        """
        evidence = self.tasks.get(task)
        if evidence is None:
            available = ", ".join(sorted(self.tasks)) or "(none)"
            return f"## L3 — {task}\nno rollouts for this task; available: {available}"
        rollout = evidence.rollout_for_seed(seed) if seed is not None else evidence.worst_rollout()
        if rollout is None:
            return f"## L3 — {task}\nno rollout for seed {seed}"

        features = self._features(evidence, rollout)
        lines = [
            f"## L3 — drill-down: {task} (seed {rollout.seed})",
            f"score {rollout.score.value:.3f}  status {rollout.score.status}  "
            f"delta vs parent {_fmt_delta(evidence.delta)}",
        ]
        if rollout.error:
            lines.append(f"rollout error: {rollout.error}")

        lines.append("")
        lines.append("### validator output (verbatim)")
        lines.append(self._validator_text(rollout))

        lines.append("")
        lines.append("### mined trajectory features")
        lines.append(features.render())

        report = evidence.efc_reports.get(rollout.seed)
        if report is None:
            report = efc_report(
                features,
                validator_events=rollout.validator_events,
                cost=rollout.cost,
                config=self.config.efc,
            )
            evidence.efc_reports[rollout.seed] = report
        lines.append("")
        lines.append("### effective feedback compute")
        lines.append(report.render())

        lines.append("")
        lines.append(f"### tail trajectory excerpt (last {self.config.tail_turns} turns)")
        lines.append(
            render_excerpt(trajectory_excerpt(rollout.events_path, self.config.tail_turns))
        )
        return "\n".join(lines)

    def _validator_text(self, rollout: Rollout) -> str:
        """Validator payloads rendered verbatim, uncapped by default.

        The v1 corpus truncated everything to fit one global budget, which is
        how the most actionable text the harness produces -- a validator error
        that prints the full table of legal attributes -- became a fragment of
        a sentence.
        """
        if not rollout.validator_events:
            return "(none recorded)"
        chunks: list[str] = []
        for i, event in enumerate(rollout.validator_events):
            if not isinstance(event, Mapping):
                chunks.append(str(event))
                continue
            label = str(event.get("source") or event.get("category") or f"event {i}")
            severity = str(event.get("severity") or "")
            location = str(event.get("location") or "")
            text = ""
            for key in ("message", "text", "output", "detail", "stderr", "reason", "error"):
                value = event.get(key)
                if isinstance(value, str) and value.strip():
                    text = value
                    break
            head = f"[{label}{'/' + severity if severity else ''}{' at ' + location if location else ''}]"
            chunks.append(f"{head}\n{text or '(no text)'}")
        blob = "\n\n".join(chunks)
        cap = self.config.max_validator_chars
        if cap and len(blob) > cap:
            return blob[:cap] + f"\n… truncated at the configured {cap}-character cap"
        return blob

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "parent_id": self.parent_id,
            "n_tasks": len(self.tasks),
            "n_rollouts": self.n_rollouts,
            "mean": self.mean,
            "sigma": self.sigma,
            "mean_task_sigma": self.mean_task_sigma,
            "zero_rate": self.zero_rate,
            "mean_efc": self.mean_efc,
            "total_cost": self.total_cost.to_dict(),
            "tasks": {t: e.to_dict() for t, e in self.tasks.items()},
            "notes": list(self.notes),
        }


def _fmt_subtree(subtree: Mapping[str, Any]) -> str:
    """One worst-subtree row. Tolerant of partially populated dicts."""
    path = subtree.get("path", "?")
    parts = [str(path)]
    if "score" in subtree:
        parts.append(f"score={float(subtree['score']):.2f}")
    if "impact" in subtree:
        parts.append(f"impact={float(subtree['impact']):.2f}")
    matched = subtree.get("n_matched")
    n_gt = subtree.get("n_gt_children")
    if matched is not None and n_gt is not None:
        parts.append(f"matched={matched}/{n_gt}")
    if subtree.get("n_extra"):
        parts.append(f"extra={subtree['n_extra']}")
    return "  ".join(parts)


def build_evidence(
    rollouts: Sequence[Rollout],
    *,
    candidate_id: CandidateId | None = None,
    parent: RoundEvidence | None = None,
    parent_scores: Mapping[TaskId, float] | None = None,
    diagnoses: Mapping[TaskId, Diagnosis] | None = None,
    config: CorpusConfig | None = None,
    with_efc: bool = False,
) -> RoundEvidence:
    """Build a corpus from a round's rollouts.

    ``with_efc=True`` mines every trajectory up front; leave it False when the
    caller only needs L0-L2, which never touches the filesystem.
    """
    evidence = RoundEvidence.from_rollouts(
        rollouts,
        candidate_id=candidate_id,
        parent=parent,
        parent_scores=parent_scores,
        diagnoses=diagnoses,
        config=config,
    )
    if with_efc:
        evidence.compute_efc()
    return evidence
