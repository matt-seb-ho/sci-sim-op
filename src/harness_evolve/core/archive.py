"""Candidate archive with Pareto-front parent selection.

v1 was a linear chain: v0 -> v1 -> v2 -> v3, three reflections, one proposer
call each, no population, no branching, and no way to revisit an earlier good
candidate. The final artifact (v3) was not *selected*; it was simply the last
link.

Parent selection here is Pareto over **per-task** scores, mirroring GEPA's
``ParetoCandidateSelector``. That structure is not a stylistic preference — it
is the right one for this objective. The reported held-out lift is driven by
two catastrophic-failure rescues out of ten tasks, with everything else inside
run-to-run noise. Under mean-based hill climbing, a candidate that rescues
``ExampleProppantTest`` but is unremarkable elsewhere gets discarded; under
Pareto it stays on the frontier because it is the best candidate *on that task*,
and its rescue can be recombined later.

If ``gepa`` is installed, :func:`select_parent` defers to its implementation so
the two never drift. The local fallback is exact, so nothing depends on the
optional import.
"""

from __future__ import annotations

import json
import random
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from harness_evolve.core.candidate import Candidate


@dataclass
class ArchiveEntry:
    candidate: Candidate
    scores: dict[str, float] = field(default_factory=dict)
    cost: dict[str, float] = field(default_factory=dict)
    accepted: bool = True
    reason: str = ""
    generation: int = 0

    @property
    def cid(self) -> str:
        return self.candidate.cid

    @property
    def mean(self) -> float:
        return statistics.mean(self.scores.values()) if self.scores else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "cid": self.cid,
            "parent_id": self.candidate.parent_id,
            "generation": self.generation,
            "accepted": self.accepted,
            "reason": self.reason,
            "mean": self.mean,
            "scores": self.scores,
            "cost": self.cost,
        }


def pareto_front(entries: Sequence[ArchiveEntry]) -> dict[str, set[str]]:
    """Map each task to the set of candidate ids achieving its best score."""
    tasks: set[str] = set()
    for e in entries:
        tasks |= set(e.scores)
    front: dict[str, set[str]] = {}
    for task in sorted(tasks):
        scored = [(e.cid, e.scores[task]) for e in entries if task in e.scores]
        if not scored:
            continue
        best = max(s for _, s in scored)
        front[task] = {cid for cid, s in scored if s >= best - 1e-12}
    return front


def dominated_ids(front: Mapping[str, set[str]]) -> set[str]:
    """Ids whose task-membership is a strict subset of another id's.

    A candidate that is on the frontier for a subset of the tasks some other
    candidate covers adds no information and should not be sampled as a parent.
    """
    coverage: dict[str, set[str]] = {}
    for task, ids in front.items():
        for cid in ids:
            coverage.setdefault(cid, set()).add(task)
    dominated: set[str] = set()
    for cid, tasks in coverage.items():
        for other, other_tasks in coverage.items():
            if other != cid and tasks < other_tasks:
                dominated.add(cid)
                break
    return dominated


@dataclass
class Archive:
    """Every candidate ever evaluated, plus the frontier over them."""

    entries: list[ArchiveEntry] = field(default_factory=list)
    rng: random.Random = field(default_factory=lambda: random.Random(0))

    def add(self, entry: ArchiveEntry) -> ArchiveEntry:
        self.entries.append(entry)
        return entry

    def get(self, cid: str) -> ArchiveEntry | None:
        return next((e for e in self.entries if e.cid == cid), None)

    @property
    def accepted(self) -> list[ArchiveEntry]:
        return [e for e in self.entries if e.accepted]

    def best(self) -> ArchiveEntry | None:
        pool = self.accepted or self.entries
        return max(pool, key=lambda e: e.mean, default=None)

    def frontier(self) -> list[ArchiveEntry]:
        pool = self.accepted
        if not pool:
            return []
        front = pareto_front(pool)
        dom = dominated_ids(front)
        ids = {cid for ids_ in front.values() for cid in ids_} - dom
        return [e for e in pool if e.cid in ids]

    def select_parent(self) -> ArchiveEntry | None:
        """Sample a parent from the Pareto frontier, weighted by coverage.

        Weighting by how many tasks a candidate is best on gives broadly-good
        candidates more mutation attempts while keeping a single-task specialist
        (a tail rescue) reachable — which is the whole reason for the frontier
        in a tail-driven objective.
        """
        front_entries = self.frontier()
        if not front_entries:
            pool = self.accepted or self.entries
            return self.rng.choice(pool) if pool else None
        front = pareto_front(self.accepted)
        weights = []
        for e in front_entries:
            w = sum(1 for ids in front.values() if e.cid in ids)
            weights.append(max(w, 1))
        return self.rng.choices(front_entries, weights=weights, k=1)[0]

    # -- persistence ------------------------------------------------------
    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "n_entries": len(self.entries),
            "n_accepted": len(self.accepted),
            "frontier": [e.cid for e in self.frontier()],
            "best": (self.best().cid if self.best() else None),
            "entries": [e.to_dict() for e in self.entries],
        }
        path.write_text(json.dumps(payload, indent=2))

    def summary(self) -> str:
        lines = [
            f"archive: {len(self.entries)} candidates, "
            f"{len(self.accepted)} accepted, "
            f"{len(self.frontier())} on the frontier"
        ]
        b = self.best()
        if b:
            lines.append(f"best: {b.cid} mean={b.mean:.4f} gen={b.generation}")
        for e in sorted(self.frontier(), key=lambda e: -e.mean):
            lines.append(f"  frontier {e.cid} mean={e.mean:.4f} gen={e.generation}")
        return "\n".join(lines)


def select_parent_via_gepa(archive: Archive) -> ArchiveEntry | None:
    """Defer to GEPA's selector when it is installed, else the local one."""
    try:
        from gepa.gepa_utils import select_program_candidate_from_pareto_front
    except Exception:
        return archive.select_parent()
    pool = archive.accepted
    if not pool:
        return archive.select_parent()
    index = {e.cid: i for i, e in enumerate(pool)}
    front = {t: {index[c] for c in ids if c in index}
             for t, ids in pareto_front(pool).items()}
    scores = [e.mean for e in pool]
    try:
        idx = select_program_candidate_from_pareto_front(front, scores, archive.rng)
    except Exception:
        return archive.select_parent()
    return pool[idx] if 0 <= idx < len(pool) else archive.select_parent()
