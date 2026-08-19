"""Replay completed rollouts from disk. The offline-protocol runner.

Everything the evaluation protocol needs -- compute-matched baselines, paired
statistics over the anchor slice, binding-constraint probes, re-analysis after
a scorer bug fix -- is a re-read of rollouts that were already paid for. At
~25 min and real money per task-run, doing that against a live runner is the
difference between a protocol that gets run and one that gets written down.

Two properties matter more than speed:

**It reports honestly.** ``capabilities.can_execute`` is ``False``. A caller
that hands this runner an unseen candidate is asking for something it cannot
do, and it must find that out from the capability flag before the search
starts, not from a wrong number afterwards.

**A miss raises.** Never a default, never a zero, never ``None``. A silent
default is precisely how v1's broken reward channel hid: the loop consumed
``treesim = None`` for every task for three rounds and reported a round mean of
0 without anybody noticing. A cache miss here is a loud, specific error naming
what *is* in the corpus for that candidate, because the usual cause is a seed
or task-name mismatch and that is fixable in seconds if the message says so.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Mapping, Sequence

from harness_evolve.runners.base import RolloutRunner, RunnerCapabilities
from harness_evolve.types import CandidateId, Cost, Rollout, Score, TaskId

if TYPE_CHECKING:  # pragma: no cover
    from harness_evolve.core.candidate import Candidate

#: Corpus key: content hash of the candidate, task id, seed.
CacheKey = tuple[CandidateId, TaskId, int]


class CacheMiss(KeyError):
    """Raised when the corpus holds no rollout for a requested key.

    A ``KeyError`` subclass so ``except KeyError`` around a lookup still works,
    but named so a caller can distinguish "not cached" from "bug".
    """

    def __init__(self, key: CacheKey, message: str) -> None:
        super().__init__(message)
        self.key = key
        self.message = message

    def __str__(self) -> str:  # KeyError repr-quotes its argument otherwise
        return self.message


class CorpusError(ValueError):
    """Raised when a corpus record cannot be read as a rollout."""


@dataclass
class RolloutRecord:
    """The on-disk form of a completed rollout.

    A record type of its own rather than ``Rollout.to_dict()`` because that
    view drops ``validator_events`` down to a count, and stop-hook decisions
    are the evidence half the whole stop-policy search rests on. Reading
    ``Rollout.to_dict()`` output is still supported -- it just replays with an
    empty validator-event list, which the loader says out loud.
    """

    task: TaskId
    candidate_id: CandidateId
    seed: int
    score: dict[str, Any]
    cost: dict[str, float] = field(default_factory=dict)
    artifacts_dir: str | None = None
    events_path: str | None = None
    validator_events: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    @classmethod
    def from_rollout(cls, rollout: Rollout) -> "RolloutRecord":
        return cls(
            task=rollout.task,
            candidate_id=rollout.candidate_id,
            seed=rollout.seed,
            score=rollout.score.to_dict(),
            cost=rollout.cost.to_dict(),
            artifacts_dir=rollout.artifacts_dir,
            events_path=rollout.events_path,
            validator_events=list(rollout.validator_events),
            error=rollout.error,
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, source: str = "") -> "RolloutRecord":
        where = f" in {source}" if source else ""
        for required in ("task", "candidate_id", "seed", "score"):
            if required not in data:
                raise CorpusError(f"record{where} is missing {required!r}: {dict(data)!r}")
        score = data["score"]
        if not isinstance(score, Mapping) or "value" not in score:
            raise CorpusError(
                f"record{where} for {data['task']!r} has no score value; a corpus "
                f"entry without a score is exactly the hole this runner exists "
                f"to make impossible"
            )
        return cls(
            task=str(data["task"]),
            candidate_id=str(data["candidate_id"]),
            seed=int(data["seed"]),
            score=dict(score),
            cost=dict(data.get("cost") or {}),
            artifacts_dir=data.get("artifacts_dir"),
            events_path=data.get("events_path"),
            validator_events=list(data.get("validator_events") or []),
            error=data.get("error"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "candidate_id": self.candidate_id,
            "seed": self.seed,
            "score": dict(self.score),
            "cost": dict(self.cost),
            "artifacts_dir": self.artifacts_dir,
            "events_path": self.events_path,
            "validator_events": list(self.validator_events),
            "error": self.error,
        }

    @property
    def key(self) -> CacheKey:
        return (self.candidate_id, self.task, self.seed)

    def to_rollout(self) -> Rollout:
        raw = dict(self.score)
        return Rollout(
            task=self.task,
            candidate_id=self.candidate_id,
            seed=self.seed,
            score=Score(
                task=str(raw.get("task", self.task)),
                value=float(raw["value"]),
                status=str(raw.get("status", "success")),
                detail=dict(raw.get("detail") or {}),
            ),
            cost=Cost(**{k: float(v) for k, v in self.cost.items()}),
            artifacts_dir=self.artifacts_dir,
            events_path=self.events_path,
            validator_events=list(self.validator_events),
            error=self.error,
        )


class CachedRunner(RolloutRunner):
    """Replay a corpus of completed rollouts, keyed by (cid, task, seed)."""

    def __init__(
        self,
        corpus_dir: Path | None = None,
        *,
        records: Iterable[RolloutRecord] = (),
    ) -> None:
        """
        Args:
            corpus_dir: directory of ``.jsonl`` (one record per line) and/or
                ``.json`` (a record, or a list of records) files. Loaded eagerly
                so a malformed corpus fails at construction rather than in the
                middle of a search.
            records: in-memory records, merged over anything loaded from disk.
        """
        self.corpus_dir = Path(corpus_dir) if corpus_dir is not None else None
        self._records: dict[CacheKey, RolloutRecord] = {}
        if self.corpus_dir is not None and self.corpus_dir.is_dir():
            for rec in _load_corpus_dir(self.corpus_dir):
                self._records[rec.key] = rec
        for rec in records:
            self._records[rec.key] = rec

    # -- construction helpers --------------------------------------------
    @classmethod
    def from_rollouts(cls, rollouts: Iterable[Rollout]) -> "CachedRunner":
        """An in-memory corpus. The cheap way to replay a run already in hand."""
        return cls(records=[RolloutRecord.from_rollout(r) for r in rollouts])

    @staticmethod
    def write_corpus(path: Path, rollouts: Iterable[Rollout]) -> Path:
        """Append rollouts to a ``.jsonl`` corpus file, creating it if needed."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            for r in rollouts:
                fh.write(json.dumps(RolloutRecord.from_rollout(r).to_dict()) + "\n")
        return path

    # -- capabilities and readiness --------------------------------------
    @property
    def capabilities(self) -> RunnerCapabilities:
        """What this runner can do. ``can_execute`` is the load-bearing field."""
        return RunnerCapabilities(
            can_execute=False,
            produces_trajectories=any(r.events_path for r in self._records.values()),
            produces_validator_events=any(
                r.validator_events for r in self._records.values()
            ),
            deterministic=True,
            usd_per_task_run=0.0,
        )

    def preflight(self) -> list[str]:
        reasons: list[str] = []
        if self.corpus_dir is not None and not self.corpus_dir.is_dir():
            reasons.append(f"corpus directory does not exist: {self.corpus_dir}")
        if not self._records:
            reasons.append("corpus is empty: nothing to replay")
        return reasons

    # -- the runner contract ---------------------------------------------
    def run(self, candidate: "Candidate", task: TaskId, seed: int = 1) -> Rollout:
        """Replay the recorded rollout, or raise :class:`CacheMiss`."""
        key = (candidate.cid, task, int(seed))
        rec = self._records.get(key)
        if rec is None:
            raise CacheMiss(key, self._miss_message(key))
        return rec.to_rollout()

    # -- coverage, so callers can check before they commit ---------------
    def has(self, candidate_id: CandidateId, task: TaskId, seed: int) -> bool:
        return (candidate_id, task, int(seed)) in self._records

    def keys(self) -> list[CacheKey]:
        return sorted(self._records)

    def candidate_ids(self) -> list[CandidateId]:
        return sorted({cid for cid, _, _ in self._records})

    def missing(
        self,
        candidate_id: CandidateId,
        tasks: Sequence[TaskId],
        seeds: Sequence[int] = (1,),
    ) -> list[CacheKey]:
        """Which (cid, task, seed) cells are absent.

        The point of exposing this is that an offline protocol should discover
        an incomplete corpus while it is planning, not one rollout into a
        paired comparison whose pairing is now broken.
        """
        return [
            (candidate_id, t, int(s))
            for s in seeds
            for t in tasks
            if not self.has(candidate_id, t, s)
        ]

    def __len__(self) -> int:
        return len(self._records)

    # -- diagnostics ------------------------------------------------------
    def _miss_message(self, key: CacheKey) -> str:
        """A miss message that names the likely mismatch.

        Almost every real miss is a task-name or seed mismatch, so the message
        enumerates what the corpus does hold for that candidate.
        """
        cid, task, seed = key
        for_cid = sorted(
            (t, s) for c, t, s in self._records if c == cid
        )
        if not for_cid:
            known = self.candidate_ids()
            return (
                f"cache miss: no rollouts at all for candidate {cid} "
                f"(task={task!r}, seed={seed}). The corpus holds {len(self)} "
                f"rollouts across {len(known)} candidates: {known[:8]}"
                f"{' ...' if len(known) > 8 else ''}. This runner cannot execute "
                f"new configurations (capabilities.can_execute is False); run the "
                f"candidate with an executing runner first, or select a candidate "
                f"the corpus covers."
            )
        seeds_for_task = sorted(s for t, s in for_cid if t == task)
        if seeds_for_task:
            return (
                f"cache miss: candidate {cid} has task {task!r} at seeds "
                f"{seeds_for_task}, but not seed {seed}."
            )
        return (
            f"cache miss: candidate {cid} has no rollout for task {task!r} at any "
            f"seed. Cached tasks for this candidate: "
            f"{sorted({t for t, _ in for_cid})}."
        )


def _load_corpus_dir(corpus_dir: Path) -> list[RolloutRecord]:
    """Read every ``.json``/``.jsonl`` file under ``corpus_dir``."""
    records: list[RolloutRecord] = []
    for path in sorted(corpus_dir.rglob("*")):
        if not path.is_file() or path.suffix not in (".json", ".jsonl"):
            continue
        rel = str(path.relative_to(corpus_dir))
        if path.suffix == ".jsonl":
            for lineno, line in enumerate(path.read_text().splitlines(), start=1):
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise CorpusError(f"{rel}:{lineno} is not valid JSON: {exc}") from exc
                records.append(RolloutRecord.from_dict(data, source=f"{rel}:{lineno}"))
            continue
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise CorpusError(f"{rel} is not valid JSON: {exc}") from exc
        for item in data if isinstance(data, list) else [data]:
            records.append(RolloutRecord.from_dict(item, source=rel))
    return records
