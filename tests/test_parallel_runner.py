"""Concurrency is what converts the free window into results, so it is tested.

A serial `run_many` leaves seven eighths of the measured 8-16 upstream slots
idle. The risks concurrency introduces are all quiet ones -- reordered results,
an interleaved corpus write, a lost rollout -- so each has a test.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field

from harness_evolve.runners.base import RolloutRunner, RunnerCapabilities
from harness_evolve.runners.parallel import ParallelRunner
from harness_evolve.runners.recording import RecordingRunner
from harness_evolve.types import Rollout, Score


@dataclass
class SlowFake(RolloutRunner):
    """A runner that sleeps, so concurrency is observable in wall-clock."""

    delay: float = 0.05
    peak: int = 0
    in_flight: int = 0
    order: list = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def capabilities(self) -> RunnerCapabilities:
        return RunnerCapabilities(can_execute=True)

    def run(self, candidate, task, seed=1):
        with self._lock:
            self.in_flight += 1
            self.peak = max(self.peak, self.in_flight)
        time.sleep(self.delay)
        with self._lock:
            self.in_flight -= 1
            self.order.append((task, seed))
        return Rollout(task=task, candidate_id="c1", seed=seed,
                       score=Score(task=task, value=0.5, status="ok"))


class FakeCandidate:
    cid = "c1"


def test_rollouts_actually_run_concurrently():
    inner = SlowFake(delay=0.1)
    runner = ParallelRunner(inner, max_parallel=6)
    started = time.time()
    out = runner.run_many(FakeCandidate(), [f"t{i}" for i in range(6)], (1,))
    elapsed = time.time() - started
    assert len(out) == 6
    assert inner.peak > 1
    # Serial would be >= 0.6s; concurrent should be far under.
    assert elapsed < 0.4, elapsed


def test_results_keep_input_order_not_completion_order():
    """Downstream code pairs rollouts with tasks positionally in places."""
    inner = SlowFake(delay=0.0)
    runner = ParallelRunner(inner, max_parallel=8)
    tasks = [f"t{i}" for i in range(8)]
    out = runner.run_many(FakeCandidate(), tasks, (1, 2))
    assert [r.task for r in out] == tasks * 2
    assert [r.seed for r in out] == [1] * 8 + [2] * 8


def test_max_parallel_is_respected():
    inner = SlowFake(delay=0.05)
    ParallelRunner(inner, max_parallel=3).run_many(
        FakeCandidate(), [f"t{i}" for i in range(12)], (1,)
    )
    assert inner.peak <= 3


def test_one_job_or_max_parallel_one_takes_the_serial_path():
    inner = SlowFake(delay=0.0)
    ParallelRunner(inner, max_parallel=1).run_many(
        FakeCandidate(), ["a", "b", "c"], (1,)
    )
    assert inner.peak == 1


def test_the_corpus_survives_concurrent_writes(tmp_path):
    """An interleaved append produces a line that is not JSON, and the corpus is
    exactly what a resumed run depends on."""
    corpus = tmp_path / "rollouts.jsonl"
    recording = RecordingRunner(SlowFake(delay=0.0), corpus)
    runner = ParallelRunner(recording, max_parallel=8)
    tasks = [f"task_{i}" for i in range(40)]
    runner.run_many(FakeCandidate(), tasks, (1,))

    lines = [l for l in corpus.read_text().splitlines() if l.strip()]
    assert len(lines) == 40
    for line in lines:
        json.loads(line)          # every line must parse


def test_a_resumed_run_replays_instead_of_re_executing(tmp_path):
    corpus = tmp_path / "rollouts.jsonl"
    tasks = ["a", "b", "c", "d"]
    first = SlowFake(delay=0.0)
    ParallelRunner(RecordingRunner(first, corpus), max_parallel=4).run_many(
        FakeCandidate(), tasks, (1,)
    )
    assert len(first.order) == 4

    second = SlowFake(delay=0.0)
    out = ParallelRunner(RecordingRunner(second, corpus), max_parallel=4).run_many(
        FakeCandidate(), tasks, (1,)
    )
    assert second.order == []      # nothing re-executed
    assert [r.task for r in out] == tasks


def test_the_progress_callback_sees_every_rollout():
    seen: list = []
    lock = threading.Lock()

    def record(rollout):
        with lock:
            seen.append(rollout.task)

    ParallelRunner(SlowFake(delay=0.0), max_parallel=4,
                   on_result=record).run_many(
        FakeCandidate(), ["a", "b", "c"], (1,)
    )
    assert sorted(seen) == ["a", "b", "c"]


def test_a_failing_progress_callback_does_not_kill_the_run():
    def boom(rollout):
        raise RuntimeError("reporting is not the job")

    out = ParallelRunner(SlowFake(delay=0.0), max_parallel=4,
                         on_result=boom).run_many(
        FakeCandidate(), ["a", "b"], (1,)
    )
    assert len(out) == 2
