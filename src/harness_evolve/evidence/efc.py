"""Effective Feedback Compute (EFC) as a per-trajectory optimization target.

Background
----------
arXiv:2605.29682 ("Scaling Laws for Agent Harnesses via Effective Feedback
Compute") argues that the scaling coordinate for a harness is not raw compute
but the subset of feedback the agent receives that is **informative, valid,
non-redundant, and retained**, reporting R^2 = 0.99 / 0.93 for EFC against
near-zero fits for tokens, tool calls, and wall time.

Why we compute it here
----------------------
The paper uses EFC as an explanatory coordinate. We want it as a *search
signal*, which as far as we know nobody has tried. The reason is specific to
this task and not a general claim: one rollout costs ~25 minutes and yields a
single scalar score, ~17 search tasks exist, and the in-distribution split is
near ceiling -- so the objective the search actually gets to see is nearly
flat. EFC is computable from logs we already write, for every trajectory,
without a ground-truth comparison, and it is *dense*: a rollout produces tens
of feedback events. A proposal that makes the harness's feedback arrive earlier
and land better should move EFC even on a task whose score cannot move.

Honesty about what these estimators are
---------------------------------------
Every quantity below is a **proxy computed from our event logs**, not the
paper's estimator. In particular:

* **informative** is "does the message name a locatable entity", which is a
  syntactic stand-in for "carries actionable content". It scores a validator
  error naming an attribute far above a bare "validation failed", which is the
  distinction we care about, but it will over-credit a message that names an
  irrelevant entity and under-credit prose that is genuinely actionable without
  naming anything.
* **valid** is "did the agent's next few actions touch the named entity". The
  paper's construct is whether the feedback was *correct*. We have no per-step
  oracle, so this measures the agent's *belief* in the feedback. Feedback that
  is confidently wrong and obeyed scores 1.0 here.
* **non-redundant** is exact-ish signature dedup with geometric decay. The
  decay rate is a choice, not a measurement; it encodes "the third identical
  schema error is worth much less than the first" without claiming to know how
  much less.
* **retained** is "did the action after the feedback differ from the action
  before it". This cannot distinguish acting *because of* the feedback from
  acting *coincidentally after* it.

How this can be gamed
---------------------
Stated up front because we intend to use it as an optimization target, and an
optimization target that can be gamed will be:

1. **Entity-stuffing.** A hook that prints "check <Solvers>, <Mesh>, <Events>"
   on every stop maximises informativeness for free. Partial guard: novelty
   decay kills the repeat, so the stuffing must also be *varied* to keep
   paying.
2. **Validity is agent belief.** A hook that names whatever file the agent just
   touched will nearly always be "addressed" by the next action. This is the
   sharpest hole and it is not closed by anything here.
3. **Retention rewards change.** A harness that perturbs the agent into doing
   something different after every message scores high retention. The
   conjunctive product with informativeness and validity limits, but does not
   eliminate, the payoff -- see the ``unearned_retention`` flag.
4. **EFC is a sum.** Many small distinct feedback events beat one excellent
   one. ``efc_density`` is reported alongside so the two are distinguishable.

Consequently EFC is a *search* signal only. Acceptance stays gated on task
score, per-task cliffs, and cost; nothing here is allowed near the metric of
record. Any candidate whose EFC rises while its score does not should be read
as a suspected gaming case first and a win second.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from statistics import fmean
from typing import Any, Mapping, Sequence

from harness_evolve.evidence.diagnostics import (
    FeedbackEvent,
    TrajectoryFeatures,
    extract_entities,
)
from harness_evolve.types import Cost

__all__ = [
    "EFCConfig",
    "EFCEventScore",
    "EFCReport",
    "efc",
    "efc_report",
    "feedback_from_validator_events",
]

_DIGITS_RE = re.compile(r"\d+")
_WS_RE = re.compile(r"\s+")

#: Keys a validator payload might carry its human-readable text under. Ordered
#: most-specific first; ``Finding.to_dict()`` lands on ``message``.
_VALIDATOR_TEXT_KEYS = ("message", "text", "output", "detail", "stderr", "reason", "error")


@dataclass(frozen=True)
class EFCConfig:
    """Tunable constants of the four estimators.

    Every number here is a modelling choice rather than a measurement, so they
    live in one dataclass where they can be swept, rather than scattered as
    literals. Defaults were picked to make the *ordering* of trajectories
    robust: exact values matter far less than that bare feedback ranks below
    entity-naming feedback, and repeats rank below firsts.
    """

    #: Floor for a feedback event that names nothing. Not zero: "it failed" is
    #: still worth more than silence, which is what v1's proposer got.
    bare_informativeness: float = 0.10
    #: Naming this many distinct entities saturates informativeness. Two,
    #: because "unknown attribute X on element Y" is the fully-located case.
    entity_saturation_k: int = 2

    #: Multiplier per prior occurrence of the same feedback signature.
    #: 0.35 => 1.00, 0.35, 0.12, 0.04 for the 1st..4th identical message.
    novelty_decay: float = 0.35

    #: How many subsequent actions may count as "addressing" the feedback.
    validity_window: int = 4
    validity_hit: float = 1.0
    validity_miss: float = 0.25
    #: Feedback naming no entity: validity is unknowable, not zero and not one.
    validity_unknown: float = 0.5

    retention_changed: float = 1.0
    #: Same tool on the same target but with different arguments: the agent
    #: adjusted rather than repeated. Partial credit.
    retention_same_target: float = 0.6
    retention_repeat: float = 0.0
    #: Feedback with no action after it was not retained -- by definition, not
    #: by failure. This is what makes terminal-only validation score zero.
    retention_no_followup: float = 0.0

    #: Denominator of ``harness_efficiency``.
    efficiency_basis: str = "tool_calls"


@dataclass(frozen=True)
class EFCEventScore:
    """Per-event breakdown. The components, not the product, are diagnosable."""

    index: int
    source: str
    category: str
    preview: str
    entities: tuple[str, ...]
    informative: float
    valid: float
    novel: float
    retained: float
    n_prior_occurrences: int = 0
    followup_tool: str = ""

    @property
    def contribution(self) -> float:
        """Product of the four properties: this event's contribution to EFC."""
        return self.informative * self.valid * self.novel * self.retained

    def render(self) -> str:
        return (
            f"  [{self.index:>4}] {self.source:<10} "
            f"I={self.informative:.2f} V={self.valid:.2f} N={self.novel:.2f} "
            f"R={self.retained:.2f} -> {self.contribution:.3f}  {self.preview}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "source": self.source,
            "category": self.category,
            "entities": list(self.entities),
            "informative": self.informative,
            "valid": self.valid,
            "novel": self.novel,
            "retained": self.retained,
            "contribution": self.contribution,
            "n_prior_occurrences": self.n_prior_occurrences,
        }


@dataclass
class EFCReport:
    """EFC for one trajectory, with its components broken out.

    Returning the scalar alone would make a drop uninterpretable: EFC falling
    because the harness stopped emitting feedback, because the feedback went
    stale, and because the agent stopped listening are three different bugs
    with three different fixes, and only the components tell them apart.
    """

    efc: float = 0.0
    n_events: int = 0
    informative_mean: float = 0.0
    valid_mean: float = 0.0
    novelty_mean: float = 0.0
    retention_mean: float = 0.0
    events: list[EFCEventScore] = field(default_factory=list)
    by_source: dict[str, float] = field(default_factory=dict)
    raw_compute: dict[str, float] = field(default_factory=dict)
    efficiency: dict[str, float] = field(default_factory=dict)
    harness_efficiency: float = 0.0
    efficiency_basis: str = "tool_calls"
    flags: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def efc_density(self) -> float:
        """EFC per feedback event: quality of feedback, independent of volume.

        Reported because ``efc`` is extensive and therefore rewards emitting
        more messages; density is the intensive companion that does not.
        """
        return self.efc / self.n_events if self.n_events else 0.0

    def render(self, max_events: int = 8) -> str:
        """Compact proposer- and human-facing summary."""
        lines = [
            f"EFC {self.efc:.2f} over {self.n_events} feedback events "
            f"(density {self.efc_density:.2f})",
            f"  informative {self.informative_mean:.2f} | valid {self.valid_mean:.2f} | "
            f"non-redundant {self.novelty_mean:.2f} | retained {self.retention_mean:.2f}",
        ]
        if self.by_source:
            lines.append(
                "  by source: "
                + ", ".join(f"{k}={v:.2f}" for k, v in sorted(self.by_source.items(), key=lambda kv: -kv[1]))
            )
        basis = self.raw_compute.get(self.efficiency_basis, 0.0)
        lines.append(
            f"  harness efficiency {self.harness_efficiency:.4f} EFC per "
            f"{self.efficiency_basis} (raw {basis:g})"
        )
        if self.flags:
            lines.append("  flags: " + ", ".join(self.flags))
        for event in self.events[:max_events]:
            lines.append(event.render())
        if len(self.events) > max_events:
            lines.append(f"  … {len(self.events) - max_events} more feedback events")
        for note in self.notes:
            lines.append(f"  note: {note}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "efc": self.efc,
            "efc_density": self.efc_density,
            "n_events": self.n_events,
            "informative_mean": self.informative_mean,
            "valid_mean": self.valid_mean,
            "novelty_mean": self.novelty_mean,
            "retention_mean": self.retention_mean,
            "by_source": dict(self.by_source),
            "raw_compute": dict(self.raw_compute),
            "efficiency": dict(self.efficiency),
            "harness_efficiency": self.harness_efficiency,
            "efficiency_basis": self.efficiency_basis,
            "flags": list(self.flags),
            "notes": list(self.notes),
            "events": [e.to_dict() for e in self.events],
        }


# --------------------------------------------------------------------------
# the four estimators
# --------------------------------------------------------------------------


def _informativeness(event: FeedbackEvent, cfg: EFCConfig) -> float:
    """Fraction of actionable content, proxied by how well the message locates itself.

    Length is deliberately not an input. A 4 kB stack trace naming nothing the
    agent can edit is less actionable than one line naming the offending
    attribute, and rewarding length would select for exactly the wrong harness.
    """
    n = len(event.entities)
    if n == 0:
        return cfg.bare_informativeness
    coverage = min(1.0, n / max(1, cfg.entity_saturation_k))
    return cfg.bare_informativeness + (1.0 - cfg.bare_informativeness) * coverage


def _signature(event: FeedbackEvent) -> tuple[str, str]:
    """Redundancy key: source plus digit-stripped, whitespace-collapsed text.

    Digits go because retry counters, line numbers, and timings differ between
    otherwise identical repeats of the same complaint -- and it is the complaint
    that repeats, not the rendering.
    """
    text = _WS_RE.sub(" ", _DIGITS_RE.sub("#", event.text)).strip().lower()
    return event.source, text[:240]


def _validity(
    event: FeedbackEvent, features: TrajectoryFeatures, cfg: EFCConfig
) -> tuple[float, str]:
    """Did the agent's next few actions engage the entity the feedback named?

    This is the weakest of the four proxies and the docstring at module level
    says why: it measures the agent's belief that the feedback was correct, not
    its correctness. It is kept because the alternative -- treating all
    feedback as equally valid -- makes the coordinate blind to the one failure
    mode we have actually observed, which is feedback the agent reads and then
    edits something else entirely.
    """
    if not event.entities:
        return cfg.validity_unknown, ""
    following = features.calls_after(event.index, cfg.validity_window)
    if not following:
        return cfg.validity_miss, ""
    for call in following:
        if any(call.mentions(entity) for entity in event.entities):
            return cfg.validity_hit, call.name
    return cfg.validity_miss, following[0].name


def _retention(
    event: FeedbackEvent, features: TrajectoryFeatures, cfg: EFCConfig
) -> tuple[float, str]:
    """Did the feedback change what the agent did next?

    Compares the first action after the event to the last action before it.
    Identical tool, target, and arguments means the message bounced off; a
    different target or tool means it landed; same target with different
    arguments is the adjust-in-place case and takes partial credit.
    """
    nxt = features.next_call_after(event.index)
    if nxt is None:
        return cfg.retention_no_followup, ""
    prev = features.prev_call_before(event.index)
    if prev is None:
        return cfg.retention_changed, nxt.name
    if nxt.name != prev.name or nxt.target != prev.target:
        return cfg.retention_changed, nxt.name
    if nxt.arg_digest != prev.arg_digest:
        return cfg.retention_same_target, nxt.name
    return cfg.retention_repeat, nxt.name


# --------------------------------------------------------------------------
# validator events
# --------------------------------------------------------------------------


def feedback_from_validator_events(
    validator_events: Sequence[Mapping[str, Any]],
    *,
    default_index: int,
) -> list[FeedbackEvent]:
    """Turn ``Rollout.validator_events`` payloads into positioned feedback.

    Each payload may carry its own ``index``/``step`` in the action stream. When
    it does not -- the common case today, because validation runs after the
    agent stops -- it is placed after the final action, where it scores zero
    retention by construction. That is the correct reading, not a bug: feedback
    the agent never saw cannot have changed anything it did, and one direct
    consequence we want the search to feel is that moving validation inline is
    worth more than improving a terminal report.
    """
    out: list[FeedbackEvent] = []
    for i, payload in enumerate(validator_events):
        if not isinstance(payload, Mapping):
            continue
        text = ""
        for key in _VALIDATOR_TEXT_KEYS:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                text = value
                break
        if not text:
            continue
        location = payload.get("location")
        if isinstance(location, str) and location:
            text = f"{text} (at {location})"
        raw_index = payload.get("index", payload.get("step"))
        index = int(raw_index) if isinstance(raw_index, (int, float)) else default_index + i
        out.append(
            FeedbackEvent(
                index=index,
                turn=-1,
                source="validator",
                text=text,
                entities=extract_entities(text),
                category=str(payload.get("severity") or payload.get("category") or "validator"),
            )
        )
    return out


# --------------------------------------------------------------------------
# aggregation
# --------------------------------------------------------------------------


def _raw_compute(features: TrajectoryFeatures, cost: Cost | None) -> dict[str, float]:
    """Raw-compute denominators, preferring the runner's accounting over the log.

    The paper's point is that these fit near zero on their own; they are here
    only as the denominator of an efficiency ratio and as the thing EFC must be
    compared against before anyone believes it.
    """
    tool_calls = float(cost.tool_calls) if cost and cost.tool_calls else float(features.n_tool_uses)
    wall = float(cost.wall_seconds) if cost and cost.wall_seconds else float(features.wall_seconds)
    out_tokens = float(cost.output_tokens) if cost and cost.output_tokens else float(features.output_tokens)
    return {
        "tool_calls": tool_calls,
        "wall_minutes": wall / 60.0,
        "output_ktokens": out_tokens / 1000.0,
    }


def _flag(report: EFCReport, cfg: EFCConfig) -> None:
    """Attach gaming/diagnostic flags. Cheap, and they are the first thing to read."""
    if report.n_events == 0:
        report.flags.append("no_feedback")
        return
    if report.n_events >= 4 and report.novelty_mean < 0.5:
        report.flags.append("low_novelty")
    if report.retention_mean >= 0.8 and report.valid_mean <= 0.35:
        report.flags.append("unearned_retention")
    if report.informative_mean >= 0.7 and report.retention_mean <= 0.2:
        report.flags.append("informative_but_ignored")
    if all(e.retained == cfg.retention_no_followup for e in report.events):
        report.flags.append("all_feedback_terminal")


def efc_report(
    features: TrajectoryFeatures,
    *,
    validator_events: Sequence[Mapping[str, Any]] = (),
    cost: Cost | None = None,
    config: EFCConfig | None = None,
) -> EFCReport:
    """Score one trajectory's feedback and combine it into an :class:`EFCReport`.

    The combination is a **product across the four properties, summed over
    events**: EFC counts feedback that was informative *and* valid *and* novel
    *and* retained, so a conjunction is the faithful aggregate -- an event
    failing any one property should contribute nothing regardless of how well
    it does on the other three. Summation over events keeps the coordinate
    extensive, matching the paper's use of it as a scaling axis.

    Never raises: an unavailable trajectory yields a zeroed report whose notes
    say why, so a candidate with no logs is scored 0 rather than skipped.
    """
    cfg = config or EFCConfig()
    report = EFCReport(efficiency_basis=cfg.efficiency_basis)

    if not features.available:
        report.notes.append(
            "trajectory unavailable; EFC reported as 0 rather than absent so that "
            "a candidate producing no logs cannot outrank one producing bad logs"
        )
        report.notes.extend(features.notes)
        report.raw_compute = _raw_compute(features, cost)
        return report

    last_index = features.calls[-1].index if features.calls else 0
    events: list[FeedbackEvent] = list(features.feedback)
    validator_feedback = feedback_from_validator_events(
        validator_events, default_index=last_index + 1
    )
    if validator_feedback:
        terminal = sum(1 for e in validator_feedback if e.index > last_index)
        if terminal:
            report.notes.append(
                f"{terminal} validator event(s) carried no step index and were placed "
                "after the final action; they score retention 0 by construction "
                "(the agent had already stopped). Log validator runs with a step "
                "index if they happen inline."
            )
        events.extend(validator_feedback)
    events.sort(key=lambda e: e.index)

    seen: dict[tuple[str, str], int] = {}
    scored: list[EFCEventScore] = []
    by_source: dict[str, float] = {}

    for event in events:
        signature = _signature(event)
        prior = seen.get(signature, 0)
        seen[signature] = prior + 1
        novel = cfg.novelty_decay**prior
        informative = _informativeness(event, cfg)
        valid, _ = _validity(event, features, cfg)
        retained, followup = _retention(event, features, cfg)
        score = EFCEventScore(
            index=event.index,
            source=event.source,
            category=event.category,
            preview=event.preview(),
            entities=event.entities,
            informative=informative,
            valid=valid,
            novel=novel,
            retained=retained,
            n_prior_occurrences=prior,
            followup_tool=followup,
        )
        scored.append(score)
        by_source[event.source] = by_source.get(event.source, 0.0) + score.contribution

    report.events = scored
    report.n_events = len(scored)
    report.efc = sum(s.contribution for s in scored)
    report.by_source = by_source
    if scored:
        report.informative_mean = fmean(s.informative for s in scored)
        report.valid_mean = fmean(s.valid for s in scored)
        report.novelty_mean = fmean(s.novel for s in scored)
        report.retention_mean = fmean(s.retained for s in scored)
    else:
        report.notes.append(
            "no feedback events in this trajectory: the harness told the agent "
            "nothing it could act on"
        )

    report.raw_compute = _raw_compute(features, cost)
    report.efficiency = {
        key: (report.efc / value if value > 0 else 0.0)
        for key, value in report.raw_compute.items()
    }
    report.harness_efficiency = report.efficiency.get(cfg.efficiency_basis, 0.0)
    _flag(report, cfg)
    return report


def efc(
    features: TrajectoryFeatures,
    *,
    validator_events: Sequence[Mapping[str, Any]] = (),
    cost: Cost | None = None,
    config: EFCConfig | None = None,
) -> float:
    """Scalar EFC for a trajectory. Prefer :func:`efc_report` -- see its docstring."""
    return efc_report(
        features, validator_events=validator_events, cost=cost, config=config
    ).efc
