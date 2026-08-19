"""The decision log: every edit as a falsifiable contract, and what became of it.

Two ideas are combined here.

**Decision observability** (arXiv:2604.25850): pair every edit with a
self-declared prediction, verified against the next round's outcomes, so
evolution proceeds by falsifiable claims rather than trial and error. The
predecessor system had no record of what any edit was *for*, so after three
rounds nobody could say which change did what -- and it turned out none of them
had done anything.

**Edit-type accounting** (arXiv:2605.20086): that paper replays evolutionary
coding traces and finds most score gains come from a small subset of edit types,
and -- the striking bit -- that around 30% of lines added during search are
byte-identical re-introductions of previously deleted lines. Evolutionary search
cycles. Detecting that costs nothing if the log stores content hashes, so it is
stored.

The log is therefore not bookkeeping. It answers three questions a search run
must be able to answer about itself: is the proposer's judgement calibrated, are
accepted edits earning their acceptance, and is the search actually exploring or
just oscillating.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


class EditType(StrEnum):
    """Coarse taxonomy of what an edit did to a component.

    Coarser than arXiv:2605.20086's nine categories because our components are
    prose and config rather than programs, and a taxonomy finer than the signal
    is noise with extra steps.
    """

    ADD = "add"
    DELETE = "delete"
    REWRITE = "rewrite"
    TIGHTEN = "tighten"          # same content, fewer tokens
    ADD_CONSTRAINT = "add_constraint"
    POLICY = "policy"            # stop-policy / config change, no prose touched
    REVERT = "revert"            # restores content this lineage previously held
    NOOP = "noop"


@dataclass(frozen=True)
class Prediction:
    """What a proposal claims it will do, stated before it is evaluated."""

    component: str
    targets_category: str
    predicted_beneficiaries: tuple[str, ...] = ()
    predicted_delta: float = 0.0
    rationale: str = ""
    evidence_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "targets_category": self.targets_category,
            "predicted_beneficiaries": list(self.predicted_beneficiaries),
            "predicted_delta": self.predicted_delta,
            "rationale": self.rationale,
            "evidence_refs": list(self.evidence_refs),
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Prediction":
        return cls(
            component=str(d.get("component", "")),
            targets_category=str(d.get("targets_category", "")),
            predicted_beneficiaries=tuple(d.get("predicted_beneficiaries") or ()),
            predicted_delta=float(d.get("predicted_delta") or 0.0),
            rationale=str(d.get("rationale", "")),
            evidence_refs=tuple(d.get("evidence_refs") or ()),
        )


def classify_edit(
    before: str,
    after: str,
    *,
    seen_hashes: Iterable[str] = (),
    constraint_markers: Sequence[str] = ("no more", "at most", "exactly", "must not"),
) -> EditType:
    """Label an edit by comparing the component's text before and after.

    ``seen_hashes`` are content hashes this lineage has held previously; a match
    means the search has cycled back to something it already discarded, which is
    the pathology arXiv:2605.20086 quantifies.
    """
    if before == after:
        return EditType.NOOP
    if content_hash(after) in set(seen_hashes):
        return EditType.REVERT
    if not after.strip():
        return EditType.DELETE
    if not before.strip():
        return EditType.ADD

    grew = len(after) > len(before)
    added_lines = set(after.splitlines()) - set(before.splitlines())
    kept = len(set(before.splitlines()) & set(after.splitlines()))
    overlap = kept / max(len(set(before.splitlines())), 1)

    if grew and any(
        m in line.lower() for line in added_lines for m in constraint_markers
    ):
        return EditType.ADD_CONSTRAINT
    if not grew and overlap > 0.6:
        return EditType.TIGHTEN
    if overlap < 0.4:
        return EditType.REWRITE
    return EditType.ADD if grew else EditType.DELETE


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


@dataclass
class DecisionRecord:
    """One accept/reject decision with everything needed to audit it later."""

    candidate_id: str
    parent_id: str | None
    component: str
    edit_type: EditType
    prediction: Prediction | None
    observed_deltas: dict[str, float] = field(default_factory=dict)
    accepted: bool = False
    reasons: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def prediction_hit_rate(self) -> float | None:
        """Fraction of predicted beneficiaries that actually improved.

        ``None`` when the proposal named none -- absent is not zero, and
        collapsing the two would corrupt the calibration curve.
        """
        if not self.prediction or not self.prediction.predicted_beneficiaries:
            return None
        named = self.prediction.predicted_beneficiaries
        hits = sum(1 for t in named if self.observed_deltas.get(t, 0.0) > 0.01)
        return hits / len(named)

    @property
    def is_unearned(self) -> bool:
        """Accepted, but nothing it predicted would improve did improve.

        Not a bug -- an accepted edit can help by luck or by helping tasks it did
        not name. But it is the signature of over-specification: content added
        for a reason that turned out not to hold, which then stays in an
        always-on artifact forever, costing tokens on every future rollout.
        """
        hr = self.prediction_hit_rate
        return bool(self.accepted and hr is not None and hr == 0.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "parent_id": self.parent_id,
            "component": self.component,
            "edit_type": str(self.edit_type),
            "prediction": self.prediction.to_dict() if self.prediction else None,
            "observed_deltas": self.observed_deltas,
            "accepted": self.accepted,
            "reasons": self.reasons,
            "metrics": self.metrics,
            "prediction_hit_rate": self.prediction_hit_rate,
            "unearned": self.is_unearned,
            "timestamp": self.timestamp,
        }


@dataclass
class DecisionLog:
    """Append-only log plus the diagnostics that make it worth keeping."""

    records: list[DecisionRecord] = field(default_factory=list)
    path: Path | None = None

    def append(self, record: DecisionRecord) -> DecisionRecord:
        self.records.append(record)
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a") as f:
                f.write(json.dumps(record.to_dict()) + "\n")
        return record

    # -- diagnostics ------------------------------------------------------
    def calibration(self) -> dict[str, Any]:
        """Is the proposer's judgement worth anything?

        A directly useful number in its own right: arXiv:2605.30621 reports that
        the capability to *produce* useful harness updates is roughly flat
        across model tiers, which was measured on general benchmarks. Whether it
        is also flat on a domain-knowledge-bound task is open, and this is the
        measurement that would answer it.
        """
        rates = [
            r.prediction_hit_rate
            for r in self.records
            if r.prediction_hit_rate is not None
        ]
        if not rates:
            return {"n": 0, "mean_hit_rate": None}
        return {
            "n": len(rates),
            "mean_hit_rate": sum(rates) / len(rates),
            "n_perfect": sum(1 for r in rates if r == 1.0),
            "n_zero": sum(1 for r in rates if r == 0.0),
        }

    def unearned_edits(self) -> list[DecisionRecord]:
        return [r for r in self.records if r.is_unearned]

    def edit_type_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for r in self.records:
            counts[str(r.edit_type)] = counts.get(str(r.edit_type), 0) + 1
        return dict(sorted(counts.items()))

    def cycling_rate(self) -> float:
        """Fraction of edits that restored previously-discarded content.

        High values mean the search is oscillating rather than exploring. Worth
        surfacing loudly: it is invisible in a score curve, which will happily
        show a plateau while the same two edits undo each other.
        """
        if not self.records:
            return 0.0
        return sum(1 for r in self.records if r.edit_type is EditType.REVERT) / len(
            self.records
        )

    def acceptance_rate(self) -> float:
        if not self.records:
            return 0.0
        return sum(1 for r in self.records if r.accepted) / len(self.records)

    def rejection_reasons(self) -> dict[str, int]:
        """Why proposals are dying, so a systematically-failing gate is visible.

        If most rejections are on the efficiency clause, the proposer is
        inflating and the memory-update mechanism needs tightening rather than
        the gate needing loosening.
        """
        counts: dict[str, int] = {}
        for r in self.records:
            for reason in r.reasons:
                key = reason.split(":")[0].strip()
                counts[key] = counts.get(key, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))

    def summary(self) -> str:
        cal = self.calibration()
        hr = cal["mean_hit_rate"]
        lines = [
            f"decisions: {len(self.records)}, "
            f"accepted {self.acceptance_rate():.0%}, "
            f"cycling {self.cycling_rate():.0%}",
            f"proposer calibration: mean hit rate "
            f"{f'{hr:.2f}' if hr is not None else 'n/a'} over {cal['n']} predictions",
        ]
        if self.edit_type_counts():
            lines.append("edit types: " + ", ".join(
                f"{k}={v}" for k, v in self.edit_type_counts().items()
            ))
        if self.rejection_reasons():
            lines.append("rejections: " + ", ".join(
                f"{k}={v}" for k, v in list(self.rejection_reasons().items())[:5]
            ))
        unearned = self.unearned_edits()
        if unearned:
            lines.append(
                f"WARNING: {len(unearned)} accepted edit(s) helped none of the "
                "tasks they named (over-specification signal)"
            )
        return "\n".join(lines)
