"""How a child candidate is produced from a parent plus evidence."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Sequence

if TYPE_CHECKING:  # pragma: no cover
    from harness_evolve.core.candidate import Candidate
    from harness_evolve.evidence.corpus import RoundEvidence


@dataclass(frozen=True)
class Demonstration:
    """One expert reference trajectory for a task.

    Deliberately not a full trajectory dump. What a proposer can act on is the
    *strategy* an expert used and the artifact they produced -- which files they
    consulted, in what order, what they reported finding hard. A raw event
    stream buries that.
    """

    task: str
    summary: str
    artifact_excerpt: str = ""
    sources_consulted: tuple[str, ...] = ()
    notes: str = ""
    provenance: str = ""

    def render(self, max_chars: int = 1200) -> str:
        parts = [f"### expert demonstration -- {self.task}", self.summary]
        if self.sources_consulted:
            parts.append("consulted: " + ", ".join(self.sources_consulted[:8]))
        if self.notes:
            parts.append(f"expert notes: {self.notes}")
        return "\n".join(parts)[:max_chars]


class ProposerError(RuntimeError):
    """A proposal could not be produced or was structurally invalid.

    Raised, not swallowed. v1 fell back to inheriting the parent whenever the
    proposer's output failed to parse, which silently consumed a call and made
    "the model said nothing useful" indistinguishable from "the model proposed
    nothing".
    """


class Proposer(ABC):
    """Produce one child candidate."""

    @abstractmethod
    def propose(
        self,
        parent: "Candidate",
        evidence: "RoundEvidence",
        history: Sequence[dict[str, Any]] = (),
        demonstrations: Sequence["Demonstration"] = (),
    ) -> "Candidate":
        """Return a child of ``parent``.

        Implementations must honour three invariants, all re-checked by the
        caller so a misbehaving proposer cannot corrupt the search:

        1. **exactly one component edited** -- minimality, so an edit's effect
           is attributable at all;
        2. **a prediction attached** -- which tasks it expects to help and by
           how much, verified next round;
        3. **budgets respected** -- a proposer that can only add is how an
           always-on artifact grows 12x in three rounds.

        ``demonstrations`` is optional expert reference experience. It exists
        because self-rollout harness evolution is reported to break down under
        sparse, high-variance reward where failures are hard to attribute
        (arXiv:2605.24539) -- which describes this task more accurately than it
        describes the benchmarks that literature usually runs on. Expert
        trajectories give the proposer something to diagnose against when the
        reward signal alone is too noisy to localize a failure.
        """
