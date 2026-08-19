"""Constructing the anchor, probe, and held-out slices.

The predecessor ran each round on a different third of its task pool, so
round-over-round score changes conflated adapter quality with task difficulty
and no two rounds were comparable. Fixing that means one *fixed* anchor slice --
but which tasks belong in it is a real question, and the obvious answer is wrong
here.

The obvious answer is coverage: spread the anchor across physics families so a
candidate cannot win by overfitting one. That is necessary and insufficient. The
measured effect in this setting is concentrated in a small number of
catastrophic-failure rescues; on the tasks where the bare harness already has a
usable template, adapters operate inside run-to-run noise. An anchor chosen for
coverage alone is mostly tasks where nothing can happen, and a search scored on
it is reading noise for most of its budget.

So the construction follows Janus (arXiv:2606.31121), which evaluates a
candidate memory update against a compact hybrid set rather than replaying
history, and mixes three roles:

* **coverage** -- representative of the distribution, so a candidate cannot win
  narrowly;
* **boundary** -- tasks where the outcome is actually in play: high across-seed
  variance, an intermittent zero rate, or a mid-range score. This is where the
  effect lives, and an anchor without it is blind to the mechanism;
* **fresh** -- tasks not yet used for selection, which bound how far the anchor
  can be overfitted.

With no baseline statistics the boundary role cannot be identified, and the
construction says so rather than guessing. A cold-start anchor is coverage-only
and is labelled as such.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping, Sequence

from harness_evolve.types import TaskId

Role = str
COVERAGE: Role = "coverage"
BOUNDARY: Role = "boundary"
FRESH: Role = "fresh"


@dataclass(frozen=True)
class TaskStat:
    """Baseline behaviour of one task, from a prior run of any configuration."""

    task: TaskId
    scores: tuple[float, ...] = ()
    group: str = ""

    @property
    def mean(self) -> float:
        return statistics.mean(self.scores) if self.scores else 0.0

    @property
    def spread(self) -> float:
        return statistics.pstdev(self.scores) if len(self.scores) > 1 else 0.0

    @property
    def zero_rate(self) -> float:
        if not self.scores:
            return 0.0
        return sum(1 for s in self.scores if s <= 1e-9) / len(self.scores)

    @property
    def in_play(self) -> float:
        """How much is actually at stake on this task.

        Three additive sources, in descending order of what they are worth:

        * an *intermittent* zero rate -- the task sometimes catastrophically
          fails and sometimes does not, which is precisely the behaviour
          adapters are known to fix, and the single most informative signal
          available;
        * across-seed spread -- the outcome is not determined;
        * a mid-range mean -- neither saturated nor hopeless.

        A task that always scores near 1.0 and a task that always scores 0.0
        both sit near zero here, for the same reason: nothing a candidate does
        will move them, so scoring on them spends budget to learn nothing.
        """
        z = self.zero_rate
        intermittent = 2.0 * z * (1.0 - z)          # peaks at z = 0.5, zero at either end
        headroom = 1.0 - abs(self.mean - 0.5) * 2.0  # peaks at mean = 0.5
        return intermittent + self.spread + 0.5 * max(headroom, 0.0)


@dataclass
class SlicePlan:
    """The chosen slices, with a defensible reason for every task in the anchor."""

    anchor: tuple[TaskId, ...] = ()
    probe: tuple[TaskId, ...] = ()
    held_out: tuple[TaskId, ...] = ()
    roles: dict[TaskId, Role] = field(default_factory=dict)
    rationale: dict[TaskId, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def cold_start(self) -> bool:
        return any("no baseline statistics" in w for w in self.warnings)

    def validate(self) -> None:
        """Slices must be disjoint. Overlap silently corrupts every comparison."""
        a, p, h = set(self.anchor), set(self.probe), set(self.held_out)
        for left, right, ln, rn in (
            (a, p, "anchor", "probe"),
            (a, h, "anchor", "held-out"),
            (p, h, "probe", "held-out"),
        ):
            shared = left & right
            if shared:
                raise ValueError(
                    f"{ln} and {rn} slices overlap on {sorted(shared)}"
                )

    def render(self) -> str:
        lines = [
            f"anchor ({len(self.anchor)}), probe ({len(self.probe)}), "
            f"held-out ({len(self.held_out)})",
            "",
            "anchor:",
        ]
        for t in self.anchor:
            lines.append(f"  {t} [{self.roles.get(t, '?')}] — {self.rationale.get(t, '')}")
        if self.probe:
            lines.append("")
            lines.append(f"probe (evidence only, never scored): {', '.join(self.probe)}")
        if self.held_out:
            lines.append(f"held-out (touched once, at the end): {', '.join(self.held_out)}")
        for w in self.warnings:
            lines.append(f"WARNING: {w}")
        return "\n".join(lines)


def build_slices(
    pool: Sequence[TaskId],
    *,
    stats: Mapping[TaskId, TaskStat] | None = None,
    anchor_size: int = 8,
    probe_size: int = 4,
    held_out: Sequence[TaskId] = (),
    group_of: Callable[[TaskId], str] | None = None,
    boundary_fraction: float = 0.5,
    fresh_fraction: float = 0.125,
) -> SlicePlan:
    """Choose anchor / probe / held-out slices from a task pool.

    ``boundary_fraction`` defaults to half the anchor. That is a deliberate bet:
    a slice weighted toward tasks where nothing is in play measures noise for
    most of its budget, and with a budget this small that is most of the run. It
    is also the parameter most worth revisiting once real baseline statistics
    exist -- it is currently reasoning, not evidence.
    """
    plan = SlicePlan(held_out=tuple(held_out))
    available = [t for t in pool if t not in set(held_out)]
    if not available:
        plan.warnings.append("no tasks left after removing the held-out slice")
        return plan

    anchor_size = min(anchor_size, len(available))
    group_of = group_of or (lambda t: (stats or {}).get(t, TaskStat(t)).group or "")

    chosen: list[TaskId] = []

    # -- boundary ---------------------------------------------------------
    if stats:
        n_boundary = int(anchor_size * boundary_fraction)
        ranked = sorted(
            (t for t in available if t in stats),
            key=lambda t: -stats[t].in_play,
        )
        for t in ranked[:n_boundary]:
            s = stats[t]
            chosen.append(t)
            plan.roles[t] = BOUNDARY
            plan.rationale[t] = (
                f"in play: mean {s.mean:.2f}, spread {s.spread:.2f}, "
                f"zero rate {s.zero_rate:.0%}"
            )
    else:
        plan.warnings.append(
            "no baseline statistics: the boundary role could not be identified, "
            "so this anchor is coverage-only and is weighted toward tasks where "
            "nothing may be in play. Rebuild it after the first baseline run."
        )

    # -- coverage ---------------------------------------------------------
    by_group: dict[str, list[TaskId]] = defaultdict(list)
    for t in available:
        if t not in chosen:
            by_group[group_of(t)].append(t)

    # Round-robin across groups so no family dominates by having more tasks.
    n_fresh = max(1, int(anchor_size * fresh_fraction)) if len(available) > anchor_size else 0
    target = anchor_size - n_fresh
    groups = sorted(by_group)
    i = 0
    while len(chosen) < target and any(by_group[g] for g in groups):
        g = groups[i % len(groups)]
        i += 1
        if not by_group[g]:
            continue
        t = by_group[g].pop(0)
        chosen.append(t)
        plan.roles[t] = COVERAGE
        plan.rationale[t] = f"coverage of group {g!r}" if g else "coverage"

    # -- fresh ------------------------------------------------------------
    remaining = [t for t in available if t not in chosen]
    for t in remaining[:n_fresh]:
        chosen.append(t)
        plan.roles[t] = FRESH
        plan.rationale[t] = "held back from selection so far; bounds anchor overfitting"

    plan.anchor = tuple(chosen)
    leftover = [t for t in available if t not in set(chosen)]
    plan.probe = tuple(leftover[:probe_size])

    if stats and len(plan.anchor) < anchor_size:
        plan.warnings.append(
            f"anchor is {len(plan.anchor)} tasks, short of the requested "
            f"{anchor_size}: the pool does not contain enough distinct tasks"
        )
    if not plan.probe:
        plan.warnings.append(
            "no probe slice: the proposer will only ever see failure modes the "
            "anchor has already been optimised against"
        )

    # Weighting the anchor toward tasks that are in play necessarily costs
    # coverage. Which groups it cost is a decision the reader should see, not
    # one buried in a ranking.
    all_groups = {group_of(t) for t in available if group_of(t)}
    covered = {group_of(t) for t in plan.anchor if group_of(t)}
    missing = sorted(all_groups - covered)
    if missing:
        plan.warnings.append(
            f"anchor does not cover group(s) {missing}: a candidate could "
            "improve the anchor while regressing there. Widen the anchor or "
            "lower boundary_fraction if that matters."
        )
    plan.validate()
    return plan


def stats_from_rollouts(
    rollouts: Iterable, *, group_of: Callable[[TaskId], str] | None = None
) -> dict[TaskId, TaskStat]:
    """Baseline statistics from any prior run's rollouts."""
    by_task: dict[TaskId, list[float]] = defaultdict(list)
    for r in rollouts:
        by_task[r.task].append(r.score.value)
    return {
        t: TaskStat(task=t, scores=tuple(v), group=(group_of(t) if group_of else ""))
        for t, v in by_task.items()
    }
