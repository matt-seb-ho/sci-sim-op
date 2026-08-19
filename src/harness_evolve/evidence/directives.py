"""Mining *repair directives* out of validator output.

Every verifier-grounded evolution method surveyed consumes a **pass/fail**
signal: the trial either verified or it did not, and the loop learns only from
the fact of failure. That is all most verifiers offer.

A scientific simulator offers considerably more. When GEOS rejects a deck it
does not say "invalid" -- it names the offending token *and enumerates the legal
alternatives inline*:

    Error: XML Node Solvers/SinglePhaseFVM contains unused attribute
    'totallyBogusAttribute'. Valid attributes are:
      cflFactor, discretization, initialDt, logLevel, name, targetRegions, ...

    Error: The tag 'ImmiscibleMultiphaseFlowBogus' is invalid within Solvers.
    All available tags are: {AcousticFirstOrderSEM, AcousticSEM, ... }

    Error: No child named 'region' found. The children of elementRegionsGroup
    are: { region_renamed }

That output does not merely report a failure. **It names the correct action
space at the point of failure**, which is strictly more information than a
verdict, and it is exactly what a proposer needs in order to write a constraint
that is *true* rather than plausible.

So the contribution here is a direction of information flow the surveyed methods
do not have. Instead of the proposer *guessing* a negative constraint from
score deltas and the loop testing it at the cost of a full evaluation round, the
constraint is **derived** from what the simulator already said, at no rollout
cost, and is correct by construction because the simulator enumerated it.

Two consequences worth being explicit about:

* A derived constraint needs no search budget to discover, only to confirm. In a
  regime where a rollout costs ~25 minutes, that is the difference between an
  affordable mechanism and an unaffordable one.
* A derived constraint carries no contamination risk of the usual kind. It comes
  from the simulator's own schema, not from a ground-truth deck -- the agent
  could have obtained it by asking the validator. Constraints mined from
  *ground truth* would be leakage; constraints mined from the *checker* are the
  interface contract, which is what an adapter is supposed to supply.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

#: Directive kinds, ordered by how directly they constrain the action space.
KIND_UNKNOWN_ATTRIBUTE = "unknown_attribute"
KIND_UNKNOWN_ELEMENT = "unknown_element"
KIND_DANGLING_REFERENCE = "dangling_reference"
KIND_MISSING_REQUIRED = "missing_required"


@dataclass(frozen=True)
class RepairDirective:
    """One validator complaint, parsed into the action space it names.

    ``offender`` is what the agent wrote; ``alternatives`` is what the simulator
    said was legal there. The pair is the whole point: a verdict tells you the
    deck is wrong, this tells you what right would have looked like.
    """

    kind: str
    offender: str
    alternatives: tuple[str, ...] = ()
    context: str = ""
    raw: str = ""

    @property
    def is_actionable(self) -> bool:
        """Did the simulator enumerate the legal alternatives?

        A directive without alternatives is only a verdict with extra words, and
        should not be treated as though it constrains anything.
        """
        return bool(self.alternatives)

    @property
    def nearest(self) -> str | None:
        """The legal alternative closest to what the agent wrote.

        A near-miss is a typo and a distant miss is a misconception, and the two
        call for different constraints: "you meant X" versus "this whole family
        of names does not exist here".
        """
        if not self.alternatives:
            return None
        return min(self.alternatives, key=lambda a: _edit_distance(self.offender, a))

    @property
    def is_near_miss(self) -> bool:
        n = self.nearest
        if n is None:
            return False
        return _edit_distance(self.offender, n) <= max(2, len(n) // 4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "offender": self.offender,
            "context": self.context,
            "n_alternatives": len(self.alternatives),
            "nearest": self.nearest,
            "is_near_miss": self.is_near_miss,
        }


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------

_LIST_SPLIT = re.compile(r"[,\s]+")


def _tokens(blob: str) -> tuple[str, ...]:
    """Split an enumerated alternatives list, tolerating its several shapes.

    GEOS variously wraps these in ``{...}``, in ``[...]``, or in nothing at all,
    and sometimes wraps across lines mid-list. Parsing leniently is right here:
    a missed alternative silently weakens a constraint, and there is no reason
    to be strict about punctuation the simulator did not promise to keep stable.
    """
    blob = blob.strip().strip("{}[]()")
    out = []
    for tok in _LIST_SPLIT.split(blob):
        tok = tok.strip().strip(",{}[]()'\"")
        # Trailing prose after the list ("... and 3 others") is not a name.
        if tok and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_:.\-]*", tok):
            out.append(tok)
    return tuple(dict.fromkeys(out))


_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        KIND_UNKNOWN_ATTRIBUTE,
        re.compile(
            r"(?:XML Node\s+(?P<context>\S+)\s+)?contains unused attribute\s+"
            r"['\"](?P<offender>[^'\"]+)['\"]\.?\s*"
            r"Valid attributes are:?\s*(?P<alts>.+?)(?=\n\s*\n|\n\s*(?:Error|Warning|Fatal)\b|\Z)",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        KIND_UNKNOWN_ELEMENT,
        re.compile(
            r"The tag\s+['\"]?(?P<offender>[A-Za-z0-9_:.\-]+)['\"]?\s+is invalid"
            r"(?:\s+within\s+(?P<context>[A-Za-z0-9_:.\-]+))?\.?\s*"
            r"All available tags are:?\s*(?P<alts>.+?)(?=\n\s*\n|\n\s*(?:Error|Warning|Fatal)\b|\Z)",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        KIND_DANGLING_REFERENCE,
        re.compile(
            r"No child named\s+['\"](?P<offender>[^'\"]+)['\"]\s+found\.?\s*"
            r"The children of\s+(?P<context>\S+?)\s+are:?\s*"
            r"(?P<alts>.+?)(?=\n\s*\n|\n\s*(?:Error|Warning|Fatal)\b|\Z)",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
)


def parse_validator_output(text: str) -> list[RepairDirective]:
    """Extract every repair directive from one validator run's output."""
    if not text:
        return []
    found: list[RepairDirective] = []
    for kind, pattern in _PATTERNS:
        for m in pattern.finditer(text):
            groups = m.groupdict()
            found.append(
                RepairDirective(
                    kind=kind,
                    offender=(groups.get("offender") or "").strip(),
                    alternatives=_tokens(groups.get("alts") or ""),
                    # Trailing sentence punctuation is not part of a tag name;
                    # leaving it in produces constraints that read as typos.
                    context=(groups.get("context") or "").strip().rstrip(".,;:"),
                    raw=m.group(0)[:400],
                )
            )
    return found


def directives_from_events(events: Iterable[Mapping[str, Any]]) -> list[RepairDirective]:
    """Mine directives from stop-hook / validator event records.

    Reads several plausible field names because the event schema is not fixed
    across runners; a directive missed for want of a key name is a silently
    weaker constraint set, which is the failure mode this module exists to avoid.
    """
    out: list[RepairDirective] = []
    for ev in events:
        for key in ("validator_output", "stdout", "stderr", "message", "feedback", "detail"):
            blob = ev.get(key)
            if isinstance(blob, str) and blob:
                out.extend(parse_validator_output(blob))
    return out


# ---------------------------------------------------------------------------
# deriving constraints
# ---------------------------------------------------------------------------


@dataclass
class DerivedConstraint:
    """A negative constraint the simulator's own output entails.

    Carries its provenance because that is what distinguishes it from a proposed
    constraint: this one is not a hypothesis to be tested, it is a restatement
    of something the checker already asserted.
    """

    kind: str
    entry: dict[str, Any]
    prose: str
    support: int = 1
    provenance: str = "derived from validator output"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "entry": self.entry,
            "prose": self.prose,
            "support": self.support,
            "provenance": self.provenance,
        }


def derive_constraints(
    directives: Sequence[RepairDirective],
    *,
    min_support: int = 2,
    max_alternatives_in_prose: int = 12,
) -> list[DerivedConstraint]:
    """Turn repeated repair directives into constraints.

    ``min_support`` defaults to 2 deliberately. A single unknown-attribute error
    is one agent's slip; the same slip twice is a property of how this model
    reads this interface, which is what an adapter should carry. Encoding
    one-offs would reproduce the over-specification failure that put an
    always-on artifact on a 12x growth curve with nothing to show for it.

    Near-misses and distant misses produce different constraints on purpose: a
    typo wants a correction, a misconception wants the legal set named.
    """
    counts: Counter[tuple[str, str, str]] = Counter()
    exemplar: dict[tuple[str, str, str], RepairDirective] = {}
    for d in directives:
        if not d.is_actionable:
            continue
        key = (d.kind, d.context, d.offender)
        counts[key] += 1
        exemplar.setdefault(key, d)

    out: list[DerivedConstraint] = []
    for key, support in counts.most_common():
        if support < min_support:
            continue
        d = exemplar[key]
        out.append(_constraint_for(d, support, max_alternatives_in_prose))
    return out


def _constraint_for(
    d: RepairDirective, support: int, max_alts: int
) -> DerivedConstraint:
    where = f"<{d.context}>" if d.context else "this element"
    if d.kind == KIND_UNKNOWN_ATTRIBUTE:
        if d.is_near_miss:
            prose = (
                f"- On {where}, the attribute `{d.offender}` does not exist; "
                f"the real name is `{d.nearest}`."
            )
        else:
            shown = ", ".join(f"`{a}`" for a in d.alternatives[:max_alts])
            more = "" if len(d.alternatives) <= max_alts else ", ..."
            prose = (
                f"- Do NOT set `{d.offender}` on {where}. Its only valid "
                f"attributes are: {shown}{more}."
            )
        return DerivedConstraint(
            kind="forbid_attr",
            entry={"kind": "forbid_attr", "tag": d.context, "attr": d.offender,
                   "valid": list(d.alternatives)},
            prose=prose, support=support,
        )

    if d.kind == KIND_UNKNOWN_ELEMENT:
        if d.is_near_miss:
            prose = (
                f"- `<{d.offender}>` is not a real tag inside {where}; "
                f"you mean `<{d.nearest}>`."
            )
        else:
            shown = ", ".join(f"`{a}`" for a in d.alternatives[:max_alts])
            more = "" if len(d.alternatives) <= max_alts else ", ..."
            prose = (
                f"- `<{d.offender}>` does not exist inside {where}. "
                f"Valid children include: {shown}{more}."
            )
        return DerivedConstraint(
            kind="forbid_element",
            entry={"kind": "forbid_element", "parent": d.context,
                   "tag": d.offender, "valid": list(d.alternatives)},
            prose=prose, support=support,
        )

    # Dangling reference: the constraint is consistency, not vocabulary.
    prose = (
        f"- Every name referenced in {where} must match a defined block. "
        f"`{d.offender}` matched nothing"
        + (f" (defined: {', '.join(f'`{a}`' for a in d.alternatives[:max_alts])})" if d.alternatives else "")
        + "."
    )
    return DerivedConstraint(
        kind="require_reference",
        entry={"kind": "require_reference", "container": d.context,
               "referenced": d.offender, "defined": list(d.alternatives)},
        prose=prose, support=support,
    )


def render_constraints(constraints: Sequence[DerivedConstraint]) -> str:
    """Prose block for the memory component, highest-support first."""
    if not constraints:
        return ""
    ordered = sorted(constraints, key=lambda c: -c.support)
    lines = ["## Constraints the validator has already told us", ""]
    lines += [c.prose for c in ordered]
    return "\n".join(lines)


def summarize(directives: Sequence[RepairDirective]) -> str:
    """One-paragraph account of what the validator has been saying."""
    if not directives:
        return "no repair directives observed"
    actionable = [d for d in directives if d.is_actionable]
    by_kind = Counter(d.kind for d in directives)
    near = sum(1 for d in actionable if d.is_near_miss)
    parts = [
        f"{len(directives)} validator directive(s), {len(actionable)} naming a "
        f"legal alternative set",
        "; ".join(f"{k}={v}" for k, v in sorted(by_kind.items())),
    ]
    if actionable:
        parts.append(
            f"{near}/{len(actionable)} are near-misses (typos) rather than "
            "misconceptions"
        )
    return " | ".join(parts)


def _edit_distance(a: str, b: str) -> int:
    """Case-insensitive Levenshtein. Small strings; the simple version is fine."""
    a, b = a.lower(), b.lower()
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


@dataclass
class ConstraintLedger:
    """Accumulates repair directives across rounds and derives constraints.

    Support has to accumulate *across* rounds, not within one. A validator
    complaint seen once in a round is one agent's slip; the same complaint in
    three different rounds, on different candidates, is a property of how this
    model reads this interface -- which is exactly the thing an always-on
    adapter should carry and the thing a per-round view cannot see.

    The ledger is also the cheapest artifact in the system. Directives arrive as
    a by-product of rollouts already paid for, so the marginal cost of a
    constraint discovered this way is zero. That matters when the alternative is
    a proposer guessing a bound and a full evaluation round finding out whether
    it holds.
    """

    directives: list[RepairDirective] = field(default_factory=list)
    rounds_observed: int = 0
    #: Support required before a directive becomes a constraint. Counted over
    #: distinct observations, so a single agent repeating itself within one
    #: round does not by itself promote a one-off into a rule.
    min_support: int = 2

    def observe(self, events: Iterable[Mapping[str, Any]]) -> int:
        """Mine one round's validator events. Returns how many were new."""
        found = directives_from_events(events)
        self.directives.extend(found)
        self.rounds_observed += 1
        return len(found)

    def observe_text(self, text: str) -> int:
        found = parse_validator_output(text)
        self.directives.extend(found)
        return len(found)

    def constraints(self) -> list[DerivedConstraint]:
        return derive_constraints(self.directives, min_support=self.min_support)

    @property
    def actionable_fraction(self) -> float:
        """How much of what the validator said actually named an action space.

        Worth watching rather than assuming: it is the number that says whether
        this mechanism is doing anything on a given simulator. A verifier that
        only ever emits verdicts would sit near zero here, and the honest
        response to that is to stop claiming the mechanism applies to it.
        """
        if not self.directives:
            return 0.0
        return sum(1 for d in self.directives if d.is_actionable) / len(self.directives)

    def summary(self) -> str:
        cs = self.constraints()
        return (
            f"{len(self.directives)} directive(s) over {self.rounds_observed} round(s), "
            f"{self.actionable_fraction:.0%} naming an action space, "
            f"{len(cs)} constraint(s) at support >= {self.min_support}"
        )
