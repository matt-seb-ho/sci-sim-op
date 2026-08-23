"""Improvements that cost no rollouts, and how much of the gain they carry.

arXiv:2607.12227's argument is a budget argument: harness evolution is itself a
search that spends inference compute, so at a matched budget it must beat what
the same compute buys as test-time scaling, and usually it does not.

The argument has a hole, and it is a structural one rather than a rhetorical
one. It assumes every harness improvement is *bought* with rollouts. Some are
not. Our derived-constraint mechanism (`evidence/directives.py`) reads validator
output that arrives as a by-product of rollouts spent for some other reason:
when GEOS rejects a deck it prints the full table of valid attributes, the ~50
legal solver types, or the set of names actually defined -- it names the legal
action space at the point of failure. A constraint derived from that text is
correct by construction and cost nothing to discover.

Which means: **a mechanism with zero marginal search cost cannot lose a
compute-matched comparison.** At a matched budget B the scaling baseline spends
B rollouts drawing samples; those very rollouts emit the validator output the
mechanism reads. It is strictly additive to whatever the baseline did with its
budget, so there is no budget at which the baseline outspends it. That is not a
loophole in the critique, it is the boundary of what the critique covers.

This module exists to keep that claim honest, because it is exactly the kind of
claim that decays into special pleading if it is asserted rather than measured.
So :class:`ZeroMarginalLedger`:

* takes the actual rollouts of a **donor** arm -- ideally the baseline itself,
  which is the strongest form of the claim -- and runs each mechanism over them;
* counts an improvement as zero-marginal only when a mechanism *derived its key*
  from those rollouts, never because someone labelled it so;
* splits the measured gain into the part carried by zero-marginal mechanisms and
  the part the search paid rollouts for;
* separates discovery from **confirmation**, because only discovery is free: a
  derived constraint still has to survive a regression gate, and pretending
  otherwise would be the special pleading this module is here to prevent;
* reports **zero** when nothing was derivable, which on a simulator whose
  validator only emits verdicts is the correct and expected answer.

The mechanism itself runs as `scripts/derive_constraints.py`, which turns a
corpus of already-spent rollouts into an improved adapter without executing
anything; this module is the accounting that says how much of the reported gain
that pass is responsible for. `docs/NOTES_2607.12227.md` §B states the argument
and its limits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Protocol, Sequence

from harness_evolve.evidence.directives import ConstraintLedger, DerivedConstraint
from harness_evolve.types import Rollout

__all__ = [
    "DerivableItem",
    "DerivedConstraints",
    "Improvement",
    "ZeroMarginalLedger",
    "ZeroMarginalMechanism",
    "ZeroMarginalReport",
    "constraint_key",
]


@dataclass(frozen=True)
class DerivableItem:
    """One harness improvement a mechanism could obtain from rollouts already spent.

    ``key`` is what makes the accounting checkable: it is minted by the
    mechanism from the mined evidence, and an :class:`Improvement` is only
    credited as zero-marginal if its own key appears here. Nothing can be
    declared free.
    """

    key: str
    mechanism: str
    support: int = 1
    evidence: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "mechanism": self.mechanism,
            "support": self.support,
            "evidence": self.evidence,
        }


class ZeroMarginalMechanism(Protocol):
    """Anything that turns rollouts spent for another purpose into improvements.

    The contract is deliberately narrow -- rollouts in, keyed items out -- so
    that a mechanism cannot smuggle in a rollout of its own. Anything needing to
    *run* something is search-funded by definition and does not belong here.
    """

    name: str

    def derive(self, rollouts: Sequence[Rollout]) -> tuple[DerivableItem, ...]:
        """Improvements obtainable from ``rollouts`` at no additional rollout cost."""
        ...


def constraint_key(constraint: DerivedConstraint) -> str:
    """Stable identity for a derived constraint: kind, scope, and the thing forbidden.

    Keyed off the structured ``entry`` rather than the prose, because the prose
    is rendered for a model to read and its wording is allowed to change without
    the constraint being a different constraint.
    """
    entry = constraint.entry
    kind = str(entry.get("kind", constraint.kind))
    if kind == "forbid_attr":
        scope, target = entry.get("tag", ""), entry.get("attr", "")
    elif kind == "forbid_element":
        scope, target = entry.get("parent", ""), entry.get("tag", "")
    elif kind == "require_reference":
        scope, target = entry.get("container", ""), entry.get("referenced", "")
    else:  # an unrecognised kind still deserves a stable, non-colliding key
        scope, target = "", str(sorted(entry.items()))
    return f"{kind}:{scope}:{target}"


@dataclass
class DerivedConstraints:
    """The validator-directive mechanism, as a zero-marginal accounting source.

    Wraps :class:`~harness_evolve.evidence.directives.ConstraintLedger` without
    changing it: support accumulates across the donor rollouts exactly as it
    does across search rounds, so a complaint seen once in the donor set is one
    agent's slip and does not become a rule.
    """

    name: str = "derived_constraints"
    min_support: int = 2

    def derive(self, rollouts: Sequence[Rollout]) -> tuple[DerivableItem, ...]:
        ledger = ConstraintLedger(min_support=self.min_support)
        for rollout in rollouts:
            ledger.observe(rollout.validator_events)
        return tuple(
            DerivableItem(
                key=constraint_key(c),
                mechanism=self.name,
                support=c.support,
                evidence=c.prose[:160],
            )
            for c in ledger.constraints()
        )


@dataclass(frozen=True)
class Improvement:
    """One accepted change to the adapter, with the gain measured for it.

    ``delta`` is supplied rather than computed: attributing a score movement to
    a particular edit is the decision log's job, and recomputing it here would
    produce a second number that could disagree with the one in the report.

    ``search_rollouts`` is what the search actually spent on this edit --
    proposal, evaluation, and regression gate. It stays attached even for
    zero-marginal improvements, because derivation being free does not make
    confirmation free, and the report prints the difference.
    """

    key: str
    component: str
    delta: float
    search_rollouts: int = 0
    description: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "component": self.component,
            "delta": self.delta,
            "search_rollouts": self.search_rollouts,
            "description": self.description,
        }


@dataclass(frozen=True)
class ZeroMarginalReport:
    """The split of a measured gain into free and search-funded parts."""

    donor_arm: str
    donor_is_baseline: bool
    donor_rollouts: int
    derivable: tuple[DerivableItem, ...]
    zero_marginal: tuple[Improvement, ...]
    search_funded: tuple[Improvement, ...]

    @property
    def total_delta(self) -> float:
        return sum(i.delta for i in self.zero_marginal) + sum(
            i.delta for i in self.search_funded
        )

    @property
    def zero_marginal_delta(self) -> float:
        return sum(i.delta for i in self.zero_marginal)

    @property
    def search_funded_delta(self) -> float:
        return sum(i.delta for i in self.search_funded)

    @property
    def fraction_reportable(self) -> bool:
        """Is there a positive total gain to take a fraction of?

        A fraction of a zero or negative total is not a small number, it is a
        meaningless one -- and it would be a large flattering number whenever the
        search-funded edits happened to cancel out.
        """
        return self.total_delta > 1e-12

    @property
    def zero_marginal_fraction(self) -> float:
        """Share of the measured gain carried by mechanisms that cost no rollouts.

        Not clamped to [0, 1]. A value above 1 is a real and reportable finding:
        the free mechanisms carried more than the whole gain because the
        search-funded edits gave some of it back.
        """
        if not self.fraction_reportable:
            return 0.0
        return self.zero_marginal_delta / self.total_delta

    @property
    def confirmation_rollouts(self) -> int:
        """Rollouts the search still spent confirming the free improvements.

        Zero marginal cost is a claim about *discovery*. These improvements were
        derived from the donor's output at no cost, then put through the same
        regression gate as everything else, and that gate costs rollouts. Naming
        the number is what separates this from special pleading.
        """
        return sum(i.search_rollouts for i in self.zero_marginal)

    @property
    def strictly_additive(self) -> bool:
        """Can this survive any compute-matched comparison by construction?

        Only when the donor rollouts are the baseline's own. Improvements mined
        from rollouts the *search* spent are cheap, not free: at a matched budget
        those rollouts came out of the same envelope the baseline is spending,
        so the comparison is a real contest and this argument does not apply.
        """
        return self.donor_is_baseline and bool(self.zero_marginal)

    def render(self) -> str:
        """Markdown block. Leads with the answer, including when it is zero."""
        donor = (
            f"the `{self.donor_arm}` baseline's own {self.donor_rollouts} rollout(s)"
            if self.donor_is_baseline
            else f"{self.donor_rollouts} rollout(s) spent by `{self.donor_arm}`"
        )
        lines = [
            f"Donor rollouts: {donor} -- spent for another purpose, mined here at "
            "no additional cost.",
            "",
        ]
        if not self.derivable:
            lines += [
                "**Nothing was derivable from them: zero improvements, zero share "
                "of the gain.** On a simulator whose validator emits verdicts "
                "rather than legal action spaces, this is the expected answer, and "
                "the zero-marginal argument does not apply to that simulator.",
            ]
            return "\n".join(lines)

        lines += [
            f"{len(self.derivable)} improvement(s) derivable at zero marginal cost, "
            f"of which {len(self.zero_marginal)} are among the accepted edits.",
            "",
            "| improvement | component | delta | funding | search rollouts |",
            "|---|---|---:|---|---:|",
        ]
        for imp in self.zero_marginal:
            lines.append(
                f"| {imp.key} | {imp.component} | {imp.delta:+.4f} | "
                f"zero-marginal | {imp.search_rollouts} |"
            )
        for imp in self.search_funded:
            lines.append(
                f"| {imp.key} | {imp.component} | {imp.delta:+.4f} | "
                f"search-funded | {imp.search_rollouts} |"
            )
        lines.append("")
        if self.fraction_reportable:
            lines.append(
                f"Zero-marginal share of the measured gain: "
                f"**{self.zero_marginal_fraction:.0%}** "
                f"({self.zero_marginal_delta:+.4f} of {self.total_delta:+.4f}); "
                f"search-funded remainder {self.search_funded_delta:+.4f}."
            )
        else:
            lines.append(
                f"Total measured gain is {self.total_delta:+.4f}, so no share can "
                "be reported: a fraction of a non-positive total would be a large "
                "flattering number rather than a small honest one."
            )
        lines += [
            "",
            f"Discovery was free; confirmation was not. The search still spent "
            f"{self.confirmation_rollouts} rollout(s) putting these through the "
            "regression gate.",
        ]
        if self.strictly_additive:
            lines += [
                "",
                "Because the donor rollouts are the baseline's own, this part of "
                "the gain is **strictly additive** to whatever the baseline spent "
                "its budget on: there is no matched budget at which the baseline "
                "outspends a mechanism that costs it nothing. It is the part of "
                "our result that a compute-matched critique cannot reach.",
            ]
        else:
            lines += [
                "",
                "The donor rollouts are not a baseline's, so these improvements are "
                "cheap rather than free in a matched comparison: the rollouts they "
                "were mined from came out of the same budget the baseline is being "
                "given.",
            ]
        return "\n".join(lines)

    def to_dict(self) -> dict[str, object]:
        return {
            "donor_arm": self.donor_arm,
            "donor_is_baseline": self.donor_is_baseline,
            "donor_rollouts": self.donor_rollouts,
            "derivable": [d.to_dict() for d in self.derivable],
            "zero_marginal": [i.to_dict() for i in self.zero_marginal],
            "search_funded": [i.to_dict() for i in self.search_funded],
            "total_delta": self.total_delta,
            "zero_marginal_delta": self.zero_marginal_delta,
            "search_funded_delta": self.search_funded_delta,
            "fraction_reportable": self.fraction_reportable,
            "zero_marginal_fraction": self.zero_marginal_fraction,
            "confirmation_rollouts": self.confirmation_rollouts,
            "strictly_additive": self.strictly_additive,
        }


@dataclass
class ZeroMarginalLedger:
    """Accounts which harness improvements were free, against rollouts already spent.

    The donor defaults to a baseline arm because that is the version of the
    claim worth making: constraints mined from the compute-matched baseline's
    own rollouts are additive to the baseline rather than in competition with
    it. Pointing the donor at the search's rollouts instead is allowed and
    honest, and :attr:`ZeroMarginalReport.strictly_additive` then reports False.
    """

    donor_arm: str = "best_of_k"
    donor_is_baseline: bool = True
    mechanisms: list[ZeroMarginalMechanism] = field(
        default_factory=lambda: [DerivedConstraints()]
    )
    donor_rollouts: list[Rollout] = field(default_factory=list)
    improvements: list[Improvement] = field(default_factory=list)

    def add_donor_rollouts(self, rollouts: Iterable[Rollout]) -> int:
        """Register rollouts spent for another purpose. Returns the running total."""
        self.donor_rollouts.extend(rollouts)
        return len(self.donor_rollouts)

    def add_improvement(self, improvement: Improvement) -> None:
        """Register one accepted edit and the gain attributed to it."""
        self.improvements.append(improvement)

    def derivable(self) -> tuple[DerivableItem, ...]:
        """Everything every mechanism can obtain from the donor rollouts.

        De-duplicated on key, keeping the highest support: two mechanisms
        deriving the same constraint is one improvement, not two, and counting
        it twice would inflate the free share for free.
        """
        best: dict[str, DerivableItem] = {}
        for mechanism in self.mechanisms:
            for item in mechanism.derive(self.donor_rollouts):
                prior = best.get(item.key)
                if prior is None or item.support > prior.support:
                    best[item.key] = item
        return tuple(best.values())

    def account(self) -> ZeroMarginalReport:
        """Split the registered improvements by whether the donor already paid for them."""
        derivable = self.derivable()
        free_keys = {d.key for d in derivable}
        zero_marginal = tuple(i for i in self.improvements if i.key in free_keys)
        search_funded = tuple(i for i in self.improvements if i.key not in free_keys)
        return ZeroMarginalReport(
            donor_arm=self.donor_arm,
            donor_is_baseline=self.donor_is_baseline,
            donor_rollouts=len(self.donor_rollouts),
            derivable=derivable,
            zero_marginal=zero_marginal,
            search_funded=search_funded,
        )
