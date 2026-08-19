"""How a candidate adapter actually gets executed on a task.

Three implementations matter, and the search loop must not be able to tell them
apart:

* a **real** runner that materializes the adapter and launches the containerized
  coding harness (expensive: ~25 min/task-run);
* a **cached** runner that replays a corpus of completed rollouts, which is what
  makes offline protocol work -- compute-matched baselines, paired statistics,
  binding-constraint probes -- possible without spending anything;
* a **mock** runner that is deterministic, so the search loop itself can be
  tested end-to-end. v1 was never tested end-to-end, which is a large part of
  why nobody noticed it was running with no reward signal.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Sequence

from harness_evolve.types import Rollout, TaskId

if TYPE_CHECKING:  # pragma: no cover
    from harness_evolve.core.candidate import Candidate


@dataclass
class RunnerCapabilities:
    """What a runner can actually do, so callers can degrade deliberately."""

    can_execute: bool = True
    produces_trajectories: bool = True
    produces_validator_events: bool = True
    deterministic: bool = False
    usd_per_task_run: float = 0.0


class RolloutRunner(ABC):
    """Execute one candidate on one task."""

    @property
    def capabilities(self) -> RunnerCapabilities:
        return RunnerCapabilities()

    @abstractmethod
    def run(self, candidate: "Candidate", task: TaskId, seed: int = 1) -> Rollout:
        """Run and score, as a single operation.

        Deliberately *not* split into run-then-score. In v1 those were separate
        steps in a shell script and the scoring step was simply never invoked,
        so the reflection loop consumed `treesim = None` for every task and
        reported a round mean of 0. Making it one call means it cannot be
        half-performed.
        """

    def run_many(
        self, candidate: "Candidate", tasks: Sequence[TaskId], seeds: Sequence[int] = (1,)
    ) -> list[Rollout]:
        return [self.run(candidate, t, s) for s in seeds for t in tasks]

    def preflight(self) -> list[str]:
        """Reasons this runner cannot run here. Empty means ready."""
        return []
