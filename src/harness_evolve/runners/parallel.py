"""Run a candidate's rollouts concurrently, because wall-clock is the budget.

The base ``run_many`` is a serial comprehension. That was the right default when
the only real runner had never been run: a serial loop is the one that cannot
surprise you. Measured on 2026-08-26 it is also the thing that decides whether an
overnight campaign produces a result, because the numbers are lopsided:

* a GEOS rollout is **minutes** -- one container, one agent session, tens of
  sequential model calls;
* the free upstream pool serving ``stealth/ox-alpha`` sustains **8-16 concurrent
  requests** before goodput stops rising;
* one rollout uses roughly **one** of those slots at a time.

So a serial ``run_many`` leaves seven eighths of the free window unused, and the
free window is the entire reason for the schedule. Concurrency here is not an
optimisation, it is the difference between measuring something tonight and not.

Why a wrapper rather than a flag on ``SubprocessRunner``:

* it composes -- ``ParallelRunner(RecordingRunner(SubprocessRunner(...)))`` gives
  concurrency *and* durable resume, and the ordering is explicit rather than
  implied;
* it is testable against a fake runner with no container in sight;
* and the serial path stays exactly as it was, so anything that goes wrong under
  concurrency can be A/B'd against it by changing one number to 1.

Threads, not processes: every rollout spends its life inside ``subprocess.run``
waiting on a container, which releases the GIL.

**Ordering is preserved.** Results come back in ``(seed, task)`` order regardless
of completion order, because downstream code pairs rollouts with tasks
positionally in places, and a silent reordering would be a very quiet bug.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Sequence

from harness_evolve.runners.base import RolloutRunner, RunnerCapabilities
from harness_evolve.types import Rollout, TaskId

if TYPE_CHECKING:  # pragma: no cover
    from harness_evolve.core.candidate import Candidate


@dataclass
class ParallelRunner(RolloutRunner):
    """Fan ``run_many`` out over a thread pool; delegate everything else."""

    inner: RolloutRunner
    #: Concurrent rollouts. Default 6, below the measured 8-16 pool ceiling:
    #: each rollout is an agent *session* that can have more than one request in
    #: flight, and overshooting converts directly into 429s rather than goodput.
    max_parallel: int = 6
    #: Called with each completed rollout as it lands, for progress reporting.
    #: Invoked from worker threads, so it must be cheap and thread-safe.
    on_result: object = field(default=None, repr=False)

    @property
    def capabilities(self) -> RunnerCapabilities:
        return self.inner.capabilities

    def preflight(self) -> list[str]:
        return self.inner.preflight()

    def run(self, candidate: "Candidate", task: TaskId, seed: int = 1) -> Rollout:
        return self.inner.run(candidate, task, seed)

    def run_many(
        self,
        candidate: "Candidate",
        tasks: Sequence[TaskId],
        seeds: Sequence[int] = (1,),
    ) -> list[Rollout]:
        jobs = [(t, s) for s in seeds for t in tasks]
        if self.max_parallel <= 1 or len(jobs) <= 1:
            return [self.inner.run(candidate, t, s) for t, s in jobs]

        def one(job: tuple[TaskId, int]) -> Rollout:
            task, seed = job
            rollout = self.inner.run(candidate, task, seed)
            if callable(self.on_result):
                try:
                    self.on_result(rollout)
                except Exception:  # noqa: BLE001 - reporting must not kill a run
                    pass
            return rollout

        with ThreadPoolExecutor(max_workers=min(self.max_parallel, len(jobs))) as pool:
            # map preserves input order; completion order is not input order and
            # downstream code pairs positionally in places.
            return list(pool.map(one, jobs))
