"""Value types shared across the package.

Deliberately dependency-free and immutable where practical: these cross every
module boundary, so anything mutable here becomes an aliasing bug later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

TaskId = str
CandidateId = str

#: Which evaluation slice a task belongs to. Carried on every rollout because
#: the distinction is a correctness property, not bookkeeping: probe rollouts
#: exist to give a proposer fresh failure modes to look at, and must never
#: contribute to a selection decision, or the search is scoring itself on the
#: same data it just read. Held-out is stricter still -- touched once, at the
#: end, by the single selected candidate.
Slice = Literal["anchor", "probe", "held_out"]

Severity = Literal["error", "warn", "info"]

#: Failure taxonomy, carried over from the bottleneck classifier so that
#: evidence, proposals, and reports all speak the same language. `no_failure`
#: is included so "nothing was wrong" is representable rather than missing.
FailureCategory = Literal[
    "missing_block",
    "extra_block",
    "hallucinated_extras",
    "structural_mismatch",
    "bad_attribute_value",
    "partial_implementation",
    "wrong_constitutive",
    "no_failure",
]

FAILURE_CATEGORIES: tuple[str, ...] = (
    "missing_block", "extra_block", "hallucinated_extras", "structural_mismatch",
    "bad_attribute_value", "partial_implementation", "wrong_constitutive", "no_failure",
)


@dataclass(frozen=True)
class Finding:
    """One problem with an artifact, reported by a check or a hygiene rule.

    ``severity="error"`` is the only level that blocks: blocking on something
    the agent cannot act on is worse than not checking at all.
    """

    source: str
    severity: Severity
    message: str
    location: str = ""

    def render(self) -> str:
        where = f" at {self.location}" if self.location else ""
        return f"[{self.severity}] {self.source}{where}: {self.message}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "severity": self.severity,
            "message": self.message,
            "location": self.location,
        }


@dataclass(frozen=True)
class Score:
    """One task's outcome under one candidate at one seed.

    ``value`` follows the failures-as-zero convention: a parse error, timeout,
    empty workspace, or missing output is 0.0, not absent. Systems are not
    rewarded for producing unscorable files, and the *rate* of these is the
    quantity the whole reliability story is about -- so it must be
    representable, not silently dropped.
    """

    task: TaskId
    value: float
    status: str = "success"
    detail: Mapping[str, Any] = field(default_factory=dict)

    @property
    def is_zero(self) -> bool:
        return self.value <= 1e-9

    @property
    def is_failure(self) -> bool:
        return self.status not in ("success", "ok")

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "value": self.value,
            "status": self.status,
            "detail": dict(self.detail),
        }


@dataclass(frozen=True)
class Cost:
    """Resource use for a rollout or a set of rollouts.

    Tracked as a first-class quantity because the efficiency constraint is a
    hard gate on acceptance, not a post-hoc observation: a candidate that wins
    on quality while inflating tool calls is the over-specification failure
    mode, and the v1 lineage exhibited it (primer 270 B -> 3159 B).
    """

    tool_calls: float = 0.0
    wall_seconds: float = 0.0
    input_tokens: float = 0.0
    output_tokens: float = 0.0
    usd: float = 0.0

    def __add__(self, other: "Cost") -> "Cost":
        return Cost(
            tool_calls=self.tool_calls + other.tool_calls,
            wall_seconds=self.wall_seconds + other.wall_seconds,
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            usd=self.usd + other.usd,
        )

    def ratio_to(self, other: "Cost") -> dict[str, float]:
        """Per-field ratio against ``other``; fields where ``other`` is 0 are omitted."""
        out = {}
        for f in ("tool_calls", "wall_seconds", "input_tokens", "output_tokens", "usd"):
            denom = getattr(other, f)
            if denom:
                out[f] = getattr(self, f) / denom
        return out

    def to_dict(self) -> dict[str, float]:
        return {
            "tool_calls": self.tool_calls,
            "wall_seconds": self.wall_seconds,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "usd": self.usd,
        }


@dataclass
class Rollout:
    """One execution of one candidate on one task.

    ``artifacts_dir`` is where the agent's workspace landed and ``events_path``
    is its raw event stream; the evidence layer reads both. Keeping the paths
    rather than the contents means a rollout stays cheap to pass around and the
    expensive drill-down is done on demand.

    ``slice`` travels with the rollout rather than being tracked by the caller.
    A rollout that has been separated from its slice cannot be safely
    aggregated, and the cost of that mistake is a search that selects on data it
    also used as evidence -- which looks like progress and is not.
    """

    @property
    def selectable(self) -> bool:
        """May this rollout influence a selection decision?"""
        return self.slice == "anchor"

    task: TaskId
    candidate_id: CandidateId
    seed: int
    score: Score
    slice: Slice = "anchor"
    cost: Cost = field(default_factory=Cost)
    artifacts_dir: str | None = None
    events_path: str | None = None
    validator_events: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "candidate_id": self.candidate_id,
            "seed": self.seed,
            "slice": self.slice,
            "score": self.score.to_dict(),
            "cost": self.cost.to_dict(),
            "artifacts_dir": self.artifacts_dir,
            "events_path": self.events_path,
            "n_validator_events": len(self.validator_events),
            "error": self.error,
        }
