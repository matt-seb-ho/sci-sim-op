"""Anchor / probe / held-out slice discipline, enforced rather than agreed.

Three slices, three different jobs:

* **anchor** -- the fixed slice every candidate is scored on. Fixed, so
  round-over-round numbers are comparable by construction and a "win" cannot be
  produced by drifting the evaluation set under the candidate.
* **probe** -- supplies fresh failure modes to the proposer and is *never*
  scored for selection. Its whole value is that it stays uncontaminated by the
  selection pressure; the moment a probe score picks a winner, it is an anchor
  with extra steps.
* **held-out** -- touched exactly once, at the end, by the single selected
  candidate alongside the compute-matched baselines.

None of that is new advice; the reason it lives in an object that *raises* is
that it is exactly the kind of rule which survives in a README and dies in a
launcher script under deadline. Off-benchmark generalization is the specific
thing the harness-evolution critique found lacking, so a held-out number that
has been peeked at is not a weak result -- it is not a result. Every access is
recorded, so the audit trail is a data structure rather than a promise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Literal, Mapping, Sequence

from harness_evolve.types import CandidateId, Rollout, TaskId

__all__ = [
    "AccessRecord",
    "EvaluationProtocol",
    "HeldOutRelease",
    "Purpose",
    "SliceName",
    "SliceViolation",
]

SliceName = Literal["anchor", "probe", "held_out"]

#: What a caller intends to do with the tasks it is asking for. This is the
#: field the enforcement turns on, so it is required at every call site --
#: naming the purpose is what makes an illegal access detectable at all.
Purpose = Literal["selection", "evidence", "final_report"]

#: Which slice each purpose may read. Encoded as data so the rule can be
#: printed in the report next to the numbers it constrains.
ALLOWED: Mapping[Purpose, tuple[SliceName, ...]] = {
    "selection": ("anchor",),
    "evidence": ("anchor", "probe"),
    "final_report": ("held_out",),
}


class SliceViolation(RuntimeError):
    """An access that would invalidate a downstream claim.

    Raised, never warned. A warning in a long-running search is a log line
    nobody reads, and by the time the report is written the contamination is
    indistinguishable from a result.
    """


@dataclass(frozen=True)
class AccessRecord:
    """One access to one slice: who, why, and when."""

    slice_name: SliceName
    purpose: Purpose
    requester: str
    n_tasks: int
    candidate_id: CandidateId | None = None
    at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    note: str = ""

    def render(self) -> str:
        who = f"{self.requester}"
        if self.candidate_id:
            who += f" ({self.candidate_id})"
        extra = f" -- {self.note}" if self.note else ""
        return (
            f"{self.at} | {self.slice_name} | {self.purpose} | {who} | "
            f"{self.n_tasks} tasks{extra}"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "slice": self.slice_name,
            "purpose": self.purpose,
            "requester": self.requester,
            "n_tasks": self.n_tasks,
            "candidate_id": self.candidate_id,
            "at": self.at,
            "note": self.note,
        }


@dataclass(frozen=True)
class HeldOutRelease:
    """The one-time release of the held-out slice.

    Returned once and only once. Holding it as a value means the final report
    can be assembled from a single access instead of asking again, which is why
    the second request can be an unconditional error.
    """

    tasks: tuple[TaskId, ...]
    candidate_id: CandidateId
    record: AccessRecord


@dataclass
class EvaluationProtocol:
    """The slice assignment, plus the rules about who may read what.

    Constructed once per experiment and passed everywhere tasks are requested.
    Callers never index the raw lists; they call :meth:`request` (or one of the
    three named wrappers) and state a purpose.
    """

    anchor: tuple[TaskId, ...]
    probe: tuple[TaskId, ...] = ()
    held_out: tuple[TaskId, ...] = ()
    name: str = "default"
    _log: list[AccessRecord] = field(default_factory=list, repr=False)
    _held_out_release: HeldOutRelease | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self.anchor = tuple(self.anchor)
        self.probe = tuple(self.probe)
        self.held_out = tuple(self.held_out)
        if not self.anchor:
            raise SliceViolation("anchor slice must be non-empty: it is what scores candidates")
        overlaps = [
            (a, b, sorted(set(x) & set(y)))
            for (a, x), (b, y) in (
                (("anchor", self.anchor), ("probe", self.probe)),
                (("anchor", self.anchor), ("held_out", self.held_out)),
                (("probe", self.probe), ("held_out", self.held_out)),
            )
        ]
        for a, b, shared in overlaps:
            if shared:
                # A task in two slices is contamination with a clean audit log,
                # which is the worst of both worlds.
                raise SliceViolation(
                    f"slices {a} and {b} share tasks {shared}; slices must be disjoint"
                )

    # -- introspection ---------------------------------------------------
    @property
    def slices(self) -> Mapping[SliceName, tuple[TaskId, ...]]:
        return {"anchor": self.anchor, "probe": self.probe, "held_out": self.held_out}

    @property
    def access_log(self) -> tuple[AccessRecord, ...]:
        return tuple(self._log)

    @property
    def held_out_released(self) -> bool:
        return self._held_out_release is not None

    def slice_of(self, task: TaskId) -> SliceName | None:
        """Which slice ``task`` belongs to, if any."""
        for name, tasks in self.slices.items():
            if task in tasks:
                return name  # type: ignore[return-value]
        return None

    # -- the gate --------------------------------------------------------
    def request(
        self,
        slice_name: SliceName,
        purpose: Purpose,
        *,
        requester: str,
        candidate_id: CandidateId | None = None,
        note: str = "",
    ) -> tuple[TaskId, ...]:
        """Return the tasks of ``slice_name``, or refuse and say why.

        Refusals, in order of how badly they would corrupt a claim: held-out for
        anything but the final report; held-out twice; probe for selection.
        """
        if slice_name not in self.slices:
            raise SliceViolation(f"unknown slice {slice_name!r}")
        if purpose not in ALLOWED:
            raise SliceViolation(f"unknown purpose {purpose!r}")
        allowed = ALLOWED[purpose]
        if slice_name not in allowed:
            raise SliceViolation(
                f"{requester!r} requested the {slice_name!r} slice for purpose "
                f"{purpose!r}; that purpose may only read {list(allowed)}. "
                + (
                    "Held-out tasks may never inform selection -- a selected "
                    "candidate scored on data it was selected with has no "
                    "held-out result at all."
                    if slice_name == "held_out"
                    else "Probe tasks supply evidence only; scoring them for "
                    "selection turns them into a second anchor and forfeits the "
                    "fresh-failure-mode signal they exist for."
                )
            )
        if slice_name == "held_out":
            raise SliceViolation(
                "use release_held_out(); the held-out slice is served exactly once"
            )
        record = AccessRecord(
            slice_name=slice_name,
            purpose=purpose,
            requester=requester,
            n_tasks=len(self.slices[slice_name]),
            candidate_id=candidate_id,
            note=note,
        )
        self._log.append(record)
        return self.slices[slice_name]

    # -- named wrappers, so call sites read as intentions -----------------
    def tasks_for_selection(
        self, *, requester: str, candidate_id: CandidateId | None = None
    ) -> tuple[TaskId, ...]:
        """The anchor slice: the only tasks a candidate may be selected on."""
        return self.request(
            "anchor", "selection", requester=requester, candidate_id=candidate_id
        )

    def tasks_for_evidence(
        self,
        *,
        requester: str,
        slice_name: SliceName = "probe",
        candidate_id: CandidateId | None = None,
    ) -> tuple[TaskId, ...]:
        """Tasks whose rollouts feed the evidence corpus but never the selector."""
        return self.request(
            slice_name, "evidence", requester=requester, candidate_id=candidate_id
        )

    def release_held_out(
        self, *, requester: str, candidate_id: CandidateId, note: str = ""
    ) -> HeldOutRelease:
        """Serve the held-out slice, once, to one named candidate.

        A second call raises even for the same candidate: "we only looked twice"
        is how a held-out set becomes a validation set, and the object cannot
        tell an innocent re-read from a second selection round.
        """
        if not self.held_out:
            raise SliceViolation("no held-out slice was configured")
        if self._held_out_release is not None:
            prior = self._held_out_release
            raise SliceViolation(
                f"held-out slice was already released to {prior.candidate_id!r} at "
                f"{prior.record.at} (requester {prior.record.requester!r}); it is "
                "served exactly once. Re-running it produces a number that is "
                "selected-on-held-out, not held out."
            )
        record = AccessRecord(
            slice_name="held_out",
            purpose="final_report",
            requester=requester,
            n_tasks=len(self.held_out),
            candidate_id=candidate_id,
            note=note or "single final evaluation",
        )
        self._log.append(record)
        release = HeldOutRelease(
            tasks=self.held_out, candidate_id=candidate_id, record=record
        )
        self._held_out_release = release
        return release

    # -- after-the-fact guards -------------------------------------------
    def assert_selection_safe(
        self, rollouts: Iterable[Rollout], *, requester: str = "unknown"
    ) -> None:
        """Refuse rollouts that reached a selection call from the wrong slice.

        The gate above only covers tasks obtained *through* the protocol. This
        catches the other route -- a cached corpus, a hardcoded task list, a
        resumed run -- at the point where the contaminated score would be used.
        """
        offenders = sorted(
            {
                r.task
                for r in rollouts
                if self.slice_of(r.task) in ("held_out", "probe")
            }
        )
        if offenders:
            raise SliceViolation(
                f"{requester!r} passed rollouts from non-anchor tasks into a "
                f"selection decision: {offenders}. These scores cannot inform "
                "which candidate wins."
            )

    def assert_final_arm(
        self, rollouts: Iterable[Rollout], *, requester: str = "unknown"
    ) -> None:
        """Check that a final-report arm was actually run on the held-out slice."""
        if self._held_out_release is None:
            raise SliceViolation(
                "final report assembled before release_held_out(); there is no "
                "audited access to point at"
            )
        tasks = {r.task for r in rollouts}
        stray = sorted(t for t in tasks if t not in set(self.held_out))
        if stray:
            raise SliceViolation(
                f"{requester!r} mixed non-held-out tasks {stray} into the final "
                "held-out arm"
            )

    # -- serialization ---------------------------------------------------
    def render_audit(self) -> str:
        """Markdown audit trail: every access, in order, with the rule that allowed it."""
        lines = [
            f"Slices (`{self.name}`): anchor {len(self.anchor)}, probe "
            f"{len(self.probe)}, held-out {len(self.held_out)}; "
            f"held-out released: {'yes' if self.held_out_released else 'no'}",
            "",
            "| when | slice | purpose | requester | tasks | note |",
            "|---|---|---|---|---:|---|",
        ]
        for r in self._log:
            who = r.requester + (f" ({r.candidate_id})" if r.candidate_id else "")
            lines.append(
                f"| {r.at} | {r.slice_name} | {r.purpose} | {who} | {r.n_tasks} | {r.note} |"
            )
        if not self._log:
            lines.append("| _(no accesses recorded)_ | | | | | |")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "anchor": list(self.anchor),
            "probe": list(self.probe),
            "held_out": list(self.held_out),
            "held_out_released": self.held_out_released,
            "access_log": [r.to_dict() for r in self._log],
        }

    # -- construction helpers --------------------------------------------
    @classmethod
    def from_split(
        cls,
        tasks: Sequence[TaskId],
        *,
        n_probe: int = 0,
        n_held_out: int = 0,
        name: str = "default",
    ) -> "EvaluationProtocol":
        """Deterministic split by sorted task id: probe first, then held-out, rest anchor.

        Deterministic rather than randomized so the split is reproducible from
        the task list alone and cannot be re-drawn after seeing results -- with
        10 held-out tasks, re-drawing a split is worth several points of
        headline.
        """
        ordered = sorted(tasks)
        if n_probe + n_held_out >= len(ordered):
            raise SliceViolation(
                f"split leaves no anchor tasks: {len(ordered)} tasks, "
                f"{n_probe} probe + {n_held_out} held out"
            )
        probe = tuple(ordered[:n_probe])
        held = tuple(ordered[n_probe : n_probe + n_held_out])
        anchor = tuple(ordered[n_probe + n_held_out :])
        return cls(anchor=anchor, probe=probe, held_out=held, name=name)
