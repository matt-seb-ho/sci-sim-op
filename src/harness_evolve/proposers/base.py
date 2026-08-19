"""How a child candidate is produced from a parent plus evidence."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Sequence

if TYPE_CHECKING:  # pragma: no cover
    from harness_evolve.core.candidate import Candidate
    from harness_evolve.evidence.corpus import RoundEvidence


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
        """
