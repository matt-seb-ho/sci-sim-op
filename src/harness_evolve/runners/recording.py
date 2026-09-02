"""Write-through recording: make a long search resumable and re-analysable.

Two problems, one mechanism.

**Resume.** A search at a credible budget is 16 to 37 hours of wall-clock, run
against a container, an external API, and a machine that may reboot. A crash at
hour twelve that forces a restart from zero does not just cost the twelve hours
-- it makes the experiment something nobody wants to attempt twice, which is how
protocols get quietly relaxed. Every rollout is therefore appended to a corpus
the moment it completes, and a restarted search replays what it already has.

**Re-analysis.** The statistics, the baselines, the verdict criterion, and the
tail measures are all cheap; the *rollouts* are the expensive part. Once a run's
rollouts are on disk, the entire evaluation can be re-run for nothing -- against a
different noise band, a different threshold, an added baseline, a corrected bug.
Without that, every question asked after the run costs another run, and the
answer is usually "we will not re-run it", which is the same thing as not asking.

The durability discipline matters more than it looks: append, flush, and fsync
per rollout. Buffering would lose exactly the work that a crash makes expensive,
and the cost -- a few milliseconds against a rollout measured in minutes -- is
not worth reasoning about.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Sequence

from harness_evolve.runners.base import RolloutRunner, RunnerCapabilities
from harness_evolve.runners.cached import CachedRunner, RolloutRecord
from harness_evolve.types import CandidateId, Rollout, TaskId

if TYPE_CHECKING:  # pragma: no cover
    from harness_evolve.core.candidate import Candidate

DEFAULT_CORPUS_NAME = "rollouts.jsonl"


@dataclass
class RecordingStats:
    """What a recording session did, so a resume can be reported rather than assumed."""

    executed: int = 0
    replayed: int = 0
    write_failures: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.executed + self.replayed

    def summary(self) -> str:
        parts = [f"{self.total} rollout(s): {self.executed} executed"]
        if self.replayed:
            parts.append(f"{self.replayed} replayed from the corpus")
        if self.write_failures:
            parts.append(
                f"{self.write_failures} FAILED TO PERSIST -- those rollouts are "
                "not resumable"
            )
        return ", ".join(parts)


class RecordingRunner(RolloutRunner):
    """Wrap a runner so every rollout is persisted, and re-used on a rerun.

    Parameters
    ----------
    inner:
        The runner that does the real work.
    corpus_path:
        Where rollouts are appended, as JSON lines.
    replay:
        Serve a recorded rollout instead of executing. This is what makes a
        restart a resume. Turn it off to force fresh execution while still
        recording -- for a deliberate re-measurement, say.
    strict_writes:
        Raise if a rollout cannot be persisted. Off by default: losing the
        *record* of a completed rollout is bad, but throwing away the rollout
        itself is worse, so the default keeps the result and counts the failure
        loudly. Turn it on when resumability matters more than the current run.
    """

    def __init__(
        self,
        inner: RolloutRunner,
        corpus_path: Path | str,
        *,
        replay: bool = True,
        strict_writes: bool = False,
    ) -> None:
        self.inner = inner
        self.corpus_path = Path(corpus_path)
        self.replay = replay
        self.strict_writes = strict_writes
        self.stats = RecordingStats()
        # ParallelRunner drives this from a thread pool; the corpus is what a
        # resumed run depends on, so its writes are serialised.
        self._write_lock = threading.Lock()
        self.corpus_path.parent.mkdir(parents=True, exist_ok=True)
        self._recorded: dict[tuple[CandidateId, TaskId, int], RolloutRecord] = {}
        self._load_existing()

    # -- corpus ------------------------------------------------------------
    def _load_existing(self) -> None:
        """Read whatever a previous run left behind.

        A truncated final line is expected rather than exceptional: it is what a
        crash mid-write looks like, and it is precisely the situation this class
        exists for. It is skipped and counted, never fatal.
        """
        if not self.corpus_path.exists():
            return
        bad = 0
        for line in self.corpus_path.read_text(errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = RolloutRecord.from_dict(
                    json.loads(line), source=str(self.corpus_path)
                )
            except Exception:
                bad += 1
                continue
            self._recorded[rec.key] = rec
        if self._recorded:
            self.stats.notes.append(
                f"resuming from {len(self._recorded)} recorded rollout(s) in "
                f"{self.corpus_path}"
            )
        if bad:
            self.stats.notes.append(
                f"{bad} unreadable line(s) skipped -- a truncated last line is "
                "what an interrupted write looks like"
            )

    def _append(self, rollout: Rollout) -> bool:
        """Append one rollout durably. Returns whether it is now on disk.

        Locked because ``ParallelRunner`` calls this from several threads at
        once: two interleaved appends produce a line that is not JSON, and the
        corpus is the artifact a resumed run depends on.
        """
        with self._write_lock:
            return self._append_locked(rollout)

    def _append_locked(self, rollout: Rollout) -> bool:
        try:
            payload = json.dumps(RolloutRecord.from_rollout(rollout).to_dict())
            with self.corpus_path.open("a", encoding="utf-8") as fh:
                fh.write(payload + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            return True
        except Exception as exc:
            self.stats.write_failures += 1
            self.stats.notes.append(
                f"could not persist {rollout.candidate_id}/{rollout.task}/"
                f"{rollout.seed}: {type(exc).__name__}: {exc}"
            )
            if self.strict_writes:
                raise
            return False

    # -- the runner contract ------------------------------------------------
    @property
    def capabilities(self) -> RunnerCapabilities:
        return self.inner.capabilities

    def preflight(self) -> list[str]:
        reasons = list(self.inner.preflight())
        parent = self.corpus_path.parent
        if not os.access(parent, os.W_OK):
            reasons.append(
                f"corpus directory is not writable ({parent}); the run would not "
                "be resumable"
            )
        return reasons

    def run(self, candidate: "Candidate", task: TaskId, seed: int = 1) -> Rollout:
        key = (candidate.cid, task, int(seed))
        if self.replay and key in self._recorded:
            self.stats.replayed += 1
            return self._recorded[key].to_rollout()

        rollout = self.inner.run(candidate, task, seed)
        self.stats.executed += 1
        if self._append(rollout):
            self._recorded[key] = RolloutRecord.from_rollout(rollout)
        return rollout

    # -- inspection ---------------------------------------------------------
    def as_cached(self) -> CachedRunner:
        """A replay-only view of everything recorded so far.

        The handoff to offline analysis: hand this to the protocol and re-run
        every statistic for free.
        """
        return CachedRunner(records=list(self._recorded.values()))

    def coverage(
        self, candidate_id: CandidateId, tasks: Sequence[TaskId], seeds: Sequence[int]
    ) -> tuple[int, int]:
        """``(recorded, requested)`` for one candidate over a task x seed grid."""
        want = [(candidate_id, t, int(s)) for t in tasks for s in seeds]
        return sum(1 for k in want if k in self._recorded), len(want)

    def __len__(self) -> int:
        return len(self._recorded)

    def summary(self) -> str:
        lines = [self.stats.summary(), f"corpus: {self.corpus_path} ({len(self)} rows)"]
        lines += self.stats.notes
        return "\n".join(lines)
