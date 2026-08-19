"""Paired statistics for a sample-starved, tail-driven comparison.

Everything here is paired on the *task*. With ~10 held-out tasks, 3 seeds, and
an effect that lives in two of those tasks, an unpaired comparison of cell means
has no power at all: the between-task spread of this benchmark (0.35 to 0.95) is
an order of magnitude larger than the effect being estimated, and it cancels
exactly when the same task is compared to itself.

Two further properties of this measurement drive the module's shape:

* **Failures are zeros, and the zeros are the effect.** Adapter cells sit at
  sigma ~= 0.002-0.005 against a bare baseline at sigma ~= 0.081, and the whole
  difference is zero-score runs. A comparison that reports only means throws
  away the finding, so tail statistics (zero rate, per-task minimum,
  catastrophic-run count, rescue count) are first-class results here, not
  appendix material.
* **n is too small for most of what one would normally report.** So the guard
  rails refuse: :class:`BootstrapResult` and :class:`PermutationResult` can come
  back saying "we cannot tell", and that outcome renders as prominently as a
  number would. A confident-looking interval computed from four tasks is worse
  than no interval, because it will be quoted.

Stdlib only, by project constraint; the numerics below are written out rather
than imported.
"""

from __future__ import annotations

import itertools
import math
import random
from dataclasses import dataclass, field
from statistics import median as _median
from typing import Callable, Iterable, Literal, Mapping, Sequence

from harness_evolve.types import Rollout, TaskId

__all__ = [
    "Aggregator",
    "ArmScores",
    "BootstrapResult",
    "Comparison",
    "EffectSizes",
    "Interval",
    "PairedDelta",
    "PermutationResult",
    "RescueLedger",
    "TailStats",
    "WinLossTie",
    "agg_mean",
    "agg_min",
    "agg_median",
    "compare",
    "cluster_bootstrap_ci",
    "headroom_capture",
    "matched_pairs_rank_biserial",
    "noise_band_from_seeds",
    "paired_bootstrap_ci",
    "paired_deltas",
    "paired_permutation_test",
    "rescue_ledger",
    "tail_stats",
    "win_loss_tie",
    "wilson_interval",
]

#: Below this many paired tasks the percentile bootstrap is reporting the shape
#: of a handful of atoms rather than a sampling distribution: with n=4 the 2.5th
#: percentile of the resample distribution is decided by whether one particular
#: task was drawn, so the endpoints are quantization artifacts. Refuse instead.
MIN_N_FOR_CI = 6

#: Below this many tasks with a non-zero delta the bootstrap is resampling a
#: two-point distribution -- exactly the reported situation (2 of 10 tasks
#: moved). The interval would then be a re-description of "did the two movers
#: get drawn", which is not evidence about the population of tasks.
MIN_MOVERS_FOR_CI = 3

#: A run below this is not a near miss; it is a structural failure (unparseable
#: deck, missing sections, timeout). The reported rescues -- 0.355 and 0.541 --
#: sit above it, so it is deliberately a *conservative* cliff marker: the
#: catastrophic count tracks the failure mode, and ``rescue_threshold`` in
#: :func:`compare` is what tracks the softer "was pulled off the floor" event.
CATASTROPHIC_THRESHOLD = 0.25

#: Used only when across-seed spread cannot be estimated (one seed per task).
#: Deliberately wide: with a single run per cell we cannot see run-to-run noise
#: at all, and calling a 0.02 move a "win" is how the predecessor's headline was
#: built.
DEFAULT_NOISE_BAND = 0.05

#: Floor on any derived noise band. Three seeds can never *demonstrate* a band
#: tighter than this, and a similarity score is not stable to better than ~0.01
#: under irrelevant reorderings of an equivalent deck, so a delta below it is
#: not a finding no matter how reproducible it looks.
MIN_NOISE_BAND = 0.01

Aggregator = Callable[[Sequence[float]], float]


def agg_mean(values: Sequence[float]) -> float:
    """Mean across seeds -- the default per-task summary."""
    return sum(values) / len(values)


def agg_min(values: Sequence[float]) -> float:
    """Worst seed for a task.

    The acceptance question is "did anything fall off a cliff", and a cliff in
    one seed of three is still a cliff: averaging it away is precisely the
    reporting error this module exists to prevent.
    """
    return min(values)


def agg_median(values: Sequence[float]) -> float:
    """Median across seeds; a compromise summary, robust to a single bad seed."""
    return float(_median(values))


AGGREGATOR_NAMES: dict[str, Aggregator] = {
    "mean": agg_mean,
    "min": agg_min,
    "median": agg_median,
}


# --------------------------------------------------------------------------
# containers
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Interval:
    """A closed interval with the confidence level that produced it."""

    low: float
    high: float
    confidence: float = 0.95

    @property
    def width(self) -> float:
        return self.high - self.low

    def contains(self, value: float) -> bool:
        return self.low <= value <= self.high

    def render(self) -> str:
        return f"[{self.low:+.4f}, {self.high:+.4f}]"

    def to_dict(self) -> dict[str, float]:
        return {"low": self.low, "high": self.high, "confidence": self.confidence}


@dataclass(frozen=True)
class ArmScores:
    """Every score for one arm, keyed by task, one value per seed.

    An "arm" is a *model x harness configuration*, never a "system": the
    Harness-Bench critique is that a bare system label hides the configuration
    that produced the number, and every consumer of this class labels rows with
    the full configuration (see :mod:`harness_evolve.evaluation.report`).

    Seeds are kept unaggregated because across-seed spread is the quantity the
    reliability claim is about; collapsing here would make it unrecoverable.
    """

    label: str
    per_task: Mapping[TaskId, tuple[float, ...]]

    def __post_init__(self) -> None:
        for task, values in self.per_task.items():
            if not values:
                raise ValueError(f"arm {self.label!r}: task {task!r} has no scores")

    @classmethod
    def from_rollouts(cls, label: str, rollouts: Iterable[Rollout]) -> "ArmScores":
        """Collect rollouts into an arm.

        Rollouts carry ``Score.value`` already under the failures-as-zero
        convention, so nothing is filtered here: dropping errored rollouts would
        turn a reliability difference into a missing-data difference.
        """
        acc: dict[TaskId, list[float]] = {}
        for r in rollouts:
            acc.setdefault(r.task, []).append(r.score.value)
        return cls(label=label, per_task={t: tuple(v) for t, v in acc.items()})

    @property
    def tasks(self) -> tuple[TaskId, ...]:
        return tuple(sorted(self.per_task))

    @property
    def n_runs(self) -> int:
        return sum(len(v) for v in self.per_task.values())

    def values(self, task: TaskId) -> tuple[float, ...]:
        return self.per_task[task]

    def all_values(self) -> list[float]:
        return [v for t in self.tasks for v in self.per_task[t]]

    def aggregate(self, task: TaskId, agg: Aggregator = agg_mean) -> float:
        return agg(self.per_task[task])

    def seed_sd(self, task: TaskId) -> float:
        """Across-seed sample standard deviation for one task (0.0 at n=1)."""
        return _sample_sd(self.per_task[task])

    def subset(self, tasks: Sequence[TaskId]) -> "ArmScores":
        """Restrict to ``tasks`` -- used to align two arms before pairing."""
        return ArmScores(
            label=self.label, per_task={t: self.per_task[t] for t in tasks}
        )


@dataclass(frozen=True)
class PairedDelta:
    """One task's paired outcome: baseline, treatment, and their difference."""

    task: TaskId
    baseline: float
    treatment: float

    @property
    def delta(self) -> float:
        return self.treatment - self.baseline


# --------------------------------------------------------------------------
# small numerics (stdlib only)
# --------------------------------------------------------------------------


def _sample_sd(values: Sequence[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mu = sum(values) / n
    return math.sqrt(sum((v - mu) ** 2 for v in values) / (n - 1))


def _quantile(sorted_values: Sequence[float], q: float) -> float:
    """Linear-interpolated quantile of an already-sorted sequence."""
    if not sorted_values:
        raise ValueError("quantile of an empty sequence")
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = q * (len(sorted_values) - 1)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return sorted_values[int(pos)]
    return sorted_values[lo] * (hi - pos) + sorted_values[hi] * (pos - lo)


def _z_for(confidence: float) -> float:
    """Two-sided normal critical value, by bisection on ``math.erf``.

    scipy is unavailable by project constraint and a hardcoded 1.96 would
    silently ignore the ``confidence`` argument, which is the kind of quiet
    mismatch this module is meant to make impossible.
    """
    target = confidence  # P(|Z| < z) = confidence
    lo, hi = 0.0, 10.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if math.erf(mid / math.sqrt(2)) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


# --------------------------------------------------------------------------
# pairing
# --------------------------------------------------------------------------


def paired_deltas(
    baseline: ArmScores, treatment: ArmScores, agg: Aggregator = agg_mean
) -> list[PairedDelta]:
    """Per-task paired outcomes for two arms scored on the same tasks.

    Refuses on a task-set mismatch rather than intersecting silently: a
    comparison over "whichever tasks both arms happened to finish" is a
    survivorship comparison, and under failures-as-zero a missing task is
    usually a task the weaker arm crashed on.
    """
    if baseline.tasks != treatment.tasks:
        only_b = sorted(set(baseline.tasks) - set(treatment.tasks))
        only_t = sorted(set(treatment.tasks) - set(baseline.tasks))
        raise ValueError(
            "paired comparison requires identical task sets; "
            f"only in {baseline.label!r}: {only_b}; only in {treatment.label!r}: {only_t}"
        )
    return [
        PairedDelta(
            task=t,
            baseline=baseline.aggregate(t, agg),
            treatment=treatment.aggregate(t, agg),
        )
        for t in baseline.tasks
    ]


# --------------------------------------------------------------------------
# bootstrap
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class BootstrapResult:
    """A paired bootstrap CI, or an explicit refusal to produce one.

    ``interval is None`` together with ``refusal`` is the "we cannot tell"
    outcome. It is a normal, expected result at this sample size and callers
    must render it, not skip it.
    """

    point: float
    n: int
    n_movers: int
    resamples: int
    confidence: float
    seed: int
    interval: Interval | None = None
    refusal: str | None = None

    @property
    def reportable(self) -> bool:
        return self.interval is not None

    @property
    def excludes_zero(self) -> bool:
        """True only when an interval exists *and* is entirely one side of zero."""
        return self.interval is not None and not self.interval.contains(0.0)

    def render(self) -> str:
        if self.interval is None:
            return f"point {self.point:+.4f}; **no CI** -- {self.refusal}"
        return (
            f"point {self.point:+.4f}, {self.confidence:.0%} CI "
            f"{self.interval.render()} (n={self.n}, {self.resamples} resamples)"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "point": self.point,
            "n": self.n,
            "n_movers": self.n_movers,
            "resamples": self.resamples,
            "confidence": self.confidence,
            "seed": self.seed,
            "interval": self.interval.to_dict() if self.interval else None,
            "refusal": self.refusal,
        }


def paired_bootstrap_ci(
    deltas: Sequence[float],
    *,
    resamples: int = 10_000,
    confidence: float = 0.95,
    seed: int = 20260819,
    min_n: int = MIN_N_FOR_CI,
    min_movers: int = MIN_MOVERS_FOR_CI,
    noise_band: float = 0.0,
) -> BootstrapResult:
    """Percentile bootstrap over per-task deltas, resampling *tasks*.

    Tasks are the resampling unit because tasks are the pairing unit and the
    thing we want to generalize over; resampling runs would ask "would this
    rerun differently", which is not the question a held-out claim makes.

    **Why the percentile variant and not BCa.** BCa's acceleration is a
    jackknife over the same ~10 tasks. When two tasks carry the entire effect,
    leaving one of them out moves the statistic by more than everything else
    combined, so the acceleration estimate is itself a two-point quantity and
    the corrected endpoints acquire a precision the data cannot support. The
    percentile interval is transparently a re-description of the empirical
    delta distribution, which is the honest object at this n. The guard rails
    below are doing the work that a bias correction could not.

    ``noise_band`` (optional) counts a task as a "mover" only if its delta
    exceeds the band, so a set of tiny numerical jitters cannot satisfy the
    mover guard rail.
    """
    n = len(deltas)
    point = sum(deltas) / n if n else float("nan")
    n_movers = sum(1 for d in deltas if abs(d) > noise_band)
    base = dict(
        point=point,
        n=n,
        n_movers=n_movers,
        resamples=resamples,
        confidence=confidence,
        seed=seed,
    )
    if n < min_n:
        return BootstrapResult(
            **base,
            refusal=(
                f"n={n} paired tasks is below the floor of {min_n}; a percentile "
                "interval here reports which of a handful of tasks was drawn, not "
                "a sampling distribution"
            ),
        )
    if n_movers < min_movers:
        return BootstrapResult(
            **base,
            refusal=(
                f"only {n_movers} of {n} tasks moved by more than the noise band "
                f"{noise_band:.3f}; the resample distribution is supported on those "
                f"{n_movers} points, so an interval would describe the movers, not "
                "the task population"
            ),
        )

    rng = random.Random(seed)
    means: list[float] = []
    data = list(deltas)
    for _ in range(resamples):
        sample = rng.choices(data, k=n)
        means.append(sum(sample) / n)
    means.sort()
    alpha = (1.0 - confidence) / 2.0
    return BootstrapResult(
        **base,
        interval=Interval(
            low=_quantile(means, alpha),
            high=_quantile(means, 1.0 - alpha),
            confidence=confidence,
        ),
    )


def cluster_bootstrap_ci(
    groups: Sequence[Sequence[float]],
    statistic: Callable[[Sequence[float]], float],
    *,
    resamples: int = 10_000,
    confidence: float = 0.95,
    seed: int = 20260819,
    min_groups: int = MIN_N_FOR_CI,
) -> BootstrapResult:
    """Bootstrap a run-level statistic while resampling whole *tasks*.

    Run-level quantities (notably the zero rate) are clustered: three seeds of
    the same task fail together far more often than three seeds of different
    tasks. Resampling runs independently would understate the interval by
    roughly the cluster factor; resampling tasks and carrying their seeds along
    keeps the dependence intact.
    """
    n = len(groups)
    flat = [v for g in groups for v in g]
    point = statistic(flat) if flat else float("nan")
    base = dict(
        point=point,
        n=n,
        n_movers=n,
        resamples=resamples,
        confidence=confidence,
        seed=seed,
    )
    if n < min_groups:
        return BootstrapResult(
            **base,
            refusal=(
                f"{n} task clusters is below the floor of {min_groups}; the "
                "interval would be an artifact of which tasks were drawn"
            ),
        )
    rng = random.Random(seed)
    stats: list[float] = []
    for _ in range(resamples):
        drawn = rng.choices(range(n), k=n)
        sample = [v for i in drawn for v in groups[i]]
        stats.append(statistic(sample))
    stats.sort()
    alpha = (1.0 - confidence) / 2.0
    return BootstrapResult(
        **base,
        interval=Interval(
            low=_quantile(stats, alpha),
            high=_quantile(stats, 1.0 - alpha),
            confidence=confidence,
        ),
    )


def wilson_interval(successes: int, n: int, confidence: float = 0.95) -> Interval:
    """Wilson score interval for a proportion.

    Wilson rather than Wald because the proportions of interest here sit at the
    boundary: an adapter arm with zero zero-scores has a Wald interval of
    exactly [0, 0], which reads as certainty from three runs. Wilson keeps
    finite width at 0 and 1.

    This treats runs as independent, which they are not (seeds cluster within a
    task), so it is reported as the *naive* interval alongside the clustered
    bootstrap in :class:`TailStats`.
    """
    if n <= 0:
        raise ValueError("wilson_interval needs at least one observation")
    z = _z_for(confidence)
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return Interval(low=max(0.0, center - half), high=min(1.0, center + half), confidence=confidence)


# --------------------------------------------------------------------------
# permutation
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PermutationResult:
    """A paired sign-flip permutation test, with its own power ceiling attached.

    ``min_achievable_p`` is the smallest p this design *could* have produced.
    At three tasks it is 0.25; at two movers it is 0.5. Reporting it next to the
    p-value is what stops "p = 0.5, no effect" from being read as evidence of
    absence when the test was incapable of saying anything else.
    """

    observed: float
    p_value: float
    n: int
    n_movers: int
    exact: bool
    n_permutations: int
    min_achievable_p: float
    alpha: float
    alternative: str

    @property
    def underpowered(self) -> bool:
        return self.min_achievable_p > self.alpha

    @property
    def significant(self) -> bool:
        return (not self.underpowered) and self.p_value <= self.alpha

    def render(self) -> str:
        kind = "exact" if self.exact else f"sampled x{self.n_permutations}"
        note = (
            f" -- **underpowered**: the smallest p this design can produce is "
            f"{self.min_achievable_p:.3f} > alpha {self.alpha:.2f}"
            if self.underpowered
            else ""
        )
        return f"p = {self.p_value:.4f} ({kind}, {self.n_movers}/{self.n} tasks moved){note}"

    def to_dict(self) -> dict[str, object]:
        return {
            "observed": self.observed,
            "p_value": self.p_value,
            "n": self.n,
            "n_movers": self.n_movers,
            "exact": self.exact,
            "n_permutations": self.n_permutations,
            "min_achievable_p": self.min_achievable_p,
            "alpha": self.alpha,
            "alternative": self.alternative,
        }


def paired_permutation_test(
    deltas: Sequence[float],
    *,
    alternative: Literal["two-sided", "greater", "less"] = "two-sided",
    resamples: int = 10_000,
    seed: int = 20260819,
    alpha: float = 0.05,
    exact_max_movers: int = 20,
    noise_band: float = 0.0,
) -> PermutationResult:
    """Sign-flip permutation on paired deltas, exact whenever it can be.

    The exchangeability assumed is the paired null: under "the adapter changed
    nothing", the sign of each task's delta is arbitrary. That is a much weaker
    assumption than a t-test's normality, which is untenable here -- the delta
    distribution is a spike at zero plus two large positive values.

    Only tasks with |delta| > ``noise_band`` are enumerated: flipping the sign of
    a zero delta produces the same statistic, so those tasks contribute nothing
    but exponent. This is also why ``min_achievable_p`` is governed by the
    number of movers rather than the number of tasks.
    """
    n = len(deltas)
    if n == 0:
        raise ValueError("permutation test needs at least one paired delta")
    movers = [d for d in deltas if abs(d) > noise_band]
    fixed_sum = sum(d for d in deltas if abs(d) <= noise_band)
    m = len(movers)
    observed = sum(deltas) / n

    def _stat(signs: Sequence[int]) -> float:
        return (fixed_sum + sum(s * d for s, d in zip(signs, movers))) / n

    if m == 0:
        # Nothing to permute: every arrangement gives the observed statistic.
        return PermutationResult(
            observed=observed,
            p_value=1.0,
            n=n,
            n_movers=0,
            exact=True,
            n_permutations=1,
            min_achievable_p=1.0,
            alpha=alpha,
            alternative=alternative,
        )

    def _extreme(stat: float) -> bool:
        if alternative == "two-sided":
            return abs(stat) >= abs(observed) - 1e-12
        if alternative == "greater":
            return stat >= observed - 1e-12
        return stat <= observed + 1e-12

    if m <= exact_max_movers:
        total = 2**m
        count = sum(
            1
            for signs in itertools.product((1, -1), repeat=m)
            if _extreme(_stat(signs))
        )
        p = count / total
        min_p = (2.0 / total) if alternative == "two-sided" else (1.0 / total)
        return PermutationResult(
            observed=observed,
            p_value=p,
            n=n,
            n_movers=m,
            exact=True,
            n_permutations=total,
            min_achievable_p=min(1.0, min_p),
            alpha=alpha,
            alternative=alternative,
        )

    rng = random.Random(seed)
    count = 0
    for _ in range(resamples):
        signs = [1 if rng.random() < 0.5 else -1 for _ in range(m)]
        if _extreme(_stat(signs)):
            count += 1
    # +1 in both places: a Monte-Carlo p of exactly 0 is not attainable evidence.
    return PermutationResult(
        observed=observed,
        p_value=(count + 1) / (resamples + 1),
        n=n,
        n_movers=m,
        exact=False,
        n_permutations=resamples,
        min_achievable_p=1.0 / (resamples + 1),
        alpha=alpha,
        alternative=alternative,
    )


# --------------------------------------------------------------------------
# effect size
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class EffectSizes:
    """Three effect measures, because no single one fits this measurement.

    ``rank_biserial`` is the headline. ``headroom_capture`` carries magnitude,
    which the rank measure discards. ``cohens_dz`` is diagnostic only.
    """

    rank_biserial: float
    n_movers: int
    headroom_capture: float
    cohens_dz: float | None
    mean_delta: float

    def render(self) -> str:
        dz = "n/a" if self.cohens_dz is None else f"{self.cohens_dz:+.2f}"
        return (
            f"r_rb = {self.rank_biserial:+.3f} (over {self.n_movers} moved tasks); "
            f"headroom captured = {self.headroom_capture:+.1%}; "
            f"d_z = {dz} (diagnostic only)"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "rank_biserial": self.rank_biserial,
            "n_movers": self.n_movers,
            "headroom_capture": self.headroom_capture,
            "cohens_dz": self.cohens_dz,
            "mean_delta": self.mean_delta,
        }


def matched_pairs_rank_biserial(
    deltas: Sequence[float], *, noise_band: float = 0.0
) -> tuple[float, int]:
    """Matched-pairs rank-biserial correlation; returns ``(r, n_movers)``.

    **Why this one.** The data are paired, bounded in [0,1], and the delta
    distribution is a spike at zero with two large values in the tail. Every
    standardized mean difference (Cohen's d, d_z, Hedges' g) divides by a
    dispersion estimated from the same handful of tasks; here that denominator
    is dominated by whether the two rescued tasks are in the sample, so d_z
    swings wildly for reasons unrelated to the effect. It is also unbounded,
    which is meaningless for a bounded outcome. The rank-biserial correlation
    derived from the signed-rank statistic is bounded in [-1, 1], needs no
    dispersion estimate, and is invariant to the (definitely non-linear) mapping
    from deck quality to similarity score -- an increment from 0.35 to 0.45 is
    not the same amount of "better" as 0.85 to 0.95, and a rank measure does not
    have to pretend otherwise.

    Its known cost: it is deaf to magnitude, so a rescue from 0.36 to 0.76 ranks
    the same as a 0.001 drift. That is exactly why it is reported next to
    :func:`headroom_capture` and the tail statistics rather than alone.
    """
    movers = [d for d in deltas if abs(d) > noise_band]
    if not movers:
        return 0.0, 0
    ranks = _average_ranks([abs(d) for d in movers])
    pos = sum(r for r, d in zip(ranks, movers) if d > 0)
    neg = sum(r for r, d in zip(ranks, movers) if d < 0)
    total = pos + neg
    return ((pos - neg) / total if total else 0.0), len(movers)


def _average_ranks(values: Sequence[float]) -> list[float]:
    """Ranks starting at 1, ties sharing their average rank."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        shared = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = shared
        i = j + 1
    return ranks


def headroom_capture(pairs: Sequence[PairedDelta]) -> float:
    """Fraction of the remaining headroom the treatment captured.

    ``sum(treatment - baseline) / sum(1 - baseline)``. Bounded above by 1 by
    construction of the [0,1] score, and it answers the question a mean delta
    cannot on a saturating metric: +0.04 on a task already at 0.95 is most of
    what was left, while +0.04 on a task at 0.35 is almost nothing. Undefined
    (returns nan) when every baseline task is already perfect.
    """
    head = sum(1.0 - p.baseline for p in pairs)
    if head <= 1e-12:
        return float("nan")
    return sum(p.delta for p in pairs) / head


def cohens_dz(deltas: Sequence[float]) -> float | None:
    """Paired standardized mean difference. Reported for comparability only.

    Kept so a reader who expects it can find it, and deliberately not the
    headline: see :func:`matched_pairs_rank_biserial` for why its denominator is
    untrustworthy at this n. Returns None when the deltas have no spread.
    """
    if len(deltas) < 2:
        return None
    sd = _sample_sd(deltas)
    if sd <= 1e-12:
        return None
    return (sum(deltas) / len(deltas)) / sd


def effect_sizes(
    pairs: Sequence[PairedDelta], *, noise_band: float = 0.0
) -> EffectSizes:
    """Bundle the three effect measures for one paired comparison."""
    deltas = [p.delta for p in pairs]
    r, movers = matched_pairs_rank_biserial(deltas, noise_band=noise_band)
    return EffectSizes(
        rank_biserial=r,
        n_movers=movers,
        headroom_capture=headroom_capture(pairs),
        cohens_dz=cohens_dz(deltas),
        mean_delta=sum(deltas) / len(deltas) if deltas else float("nan"),
    )


# --------------------------------------------------------------------------
# tail statistics -- the actual mechanism
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class TailStats:
    """Distributional-tail summary for one arm.

    These are the primary results, not diagnostics. The reported effect is a
    variance collapse driven by zero-score runs disappearing; a mean is a lossy
    projection of that, and it is the projection under which the predecessor's
    headline looked like a quality gain.
    """

    label: str
    n_tasks: int
    n_runs: int
    zero_runs: int
    catastrophic_threshold: float
    catastrophic_runs: int
    per_task_min: Mapping[TaskId, float]
    per_task_seed_sd: Mapping[TaskId, float]
    zero_rate_ci: BootstrapResult
    zero_rate_ci_naive: Interval

    @property
    def zero_rate(self) -> float:
        return self.zero_runs / self.n_runs if self.n_runs else float("nan")

    @property
    def catastrophic_rate(self) -> float:
        return self.catastrophic_runs / self.n_runs if self.n_runs else float("nan")

    @property
    def tasks_with_any_catastrophe(self) -> tuple[TaskId, ...]:
        """Tasks where at least one seed fell off the cliff.

        Task-level rather than run-level because one bad seed in three is a
        reliability failure for that task, and the acceptance gate is per-task.
        """
        return tuple(
            t
            for t, m in sorted(self.per_task_min.items())
            if m < self.catastrophic_threshold
        )

    @property
    def mean_per_task_min(self) -> float:
        vals = list(self.per_task_min.values())
        return sum(vals) / len(vals) if vals else float("nan")

    @property
    def max_seed_sd(self) -> float:
        vals = list(self.per_task_seed_sd.values())
        return max(vals) if vals else 0.0

    @property
    def pooled_seed_sd(self) -> float:
        """Root-mean-square of within-task across-seed SDs: the run-to-run noise."""
        vals = list(self.per_task_seed_sd.values())
        if not vals:
            return 0.0
        return math.sqrt(sum(v * v for v in vals) / len(vals))

    def to_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "n_tasks": self.n_tasks,
            "n_runs": self.n_runs,
            "zero_runs": self.zero_runs,
            "zero_rate": self.zero_rate,
            "zero_rate_ci": self.zero_rate_ci.to_dict(),
            "zero_rate_ci_naive": self.zero_rate_ci_naive.to_dict(),
            "catastrophic_threshold": self.catastrophic_threshold,
            "catastrophic_runs": self.catastrophic_runs,
            "catastrophic_rate": self.catastrophic_rate,
            "tasks_with_any_catastrophe": list(self.tasks_with_any_catastrophe),
            "per_task_min": dict(self.per_task_min),
            "per_task_seed_sd": dict(self.per_task_seed_sd),
            "pooled_seed_sd": self.pooled_seed_sd,
        }


def tail_stats(
    arm: ArmScores,
    *,
    catastrophic_threshold: float = CATASTROPHIC_THRESHOLD,
    zero_threshold: float = 1e-9,
    resamples: int = 10_000,
    confidence: float = 0.95,
    seed: int = 20260819,
) -> TailStats:
    """Compute the tail summary for one arm."""
    tasks = arm.tasks
    groups = [list(arm.values(t)) for t in tasks]
    zero_runs = sum(1 for g in groups for v in g if v <= zero_threshold)
    n_runs = sum(len(g) for g in groups)
    return TailStats(
        label=arm.label,
        n_tasks=len(tasks),
        n_runs=n_runs,
        zero_runs=zero_runs,
        catastrophic_threshold=catastrophic_threshold,
        catastrophic_runs=sum(
            1 for g in groups for v in g if v < catastrophic_threshold
        ),
        per_task_min={t: min(arm.values(t)) for t in tasks},
        per_task_seed_sd={t: arm.seed_sd(t) for t in tasks},
        zero_rate_ci=cluster_bootstrap_ci(
            groups,
            lambda vals: sum(1 for v in vals if v <= zero_threshold) / len(vals),
            resamples=resamples,
            confidence=confidence,
            seed=seed,
        ),
        zero_rate_ci_naive=wilson_interval(zero_runs, n_runs, confidence)
        if n_runs
        else Interval(0.0, 1.0, confidence),
    )


@dataclass(frozen=True)
class RescueLedger:
    """Which tasks crossed the cliff threshold, in each direction.

    This is the claimed mechanism stated as a countable event. "Two tasks
    rescued" is falsifiable in a way "+0.069 mean" is not: it names the tasks,
    so the next round can check whether the same two moved for the same reason.
    """

    threshold: float
    aggregator: str
    rescued: tuple[TaskId, ...]
    lost: tuple[TaskId, ...]
    stayed_below: tuple[TaskId, ...]
    stayed_above: tuple[TaskId, ...]

    @property
    def net_rescues(self) -> int:
        return len(self.rescued) - len(self.lost)

    def render(self) -> str:
        return (
            f"rescued {len(self.rescued)} {list(self.rescued)}, "
            f"lost {len(self.lost)} {list(self.lost)} "
            f"(threshold {self.threshold:.2f} on per-task {self.aggregator})"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "threshold": self.threshold,
            "aggregator": self.aggregator,
            "rescued": list(self.rescued),
            "lost": list(self.lost),
            "stayed_below": list(self.stayed_below),
            "stayed_above": list(self.stayed_above),
            "net_rescues": self.net_rescues,
        }


def rescue_ledger(
    baseline: ArmScores,
    treatment: ArmScores,
    *,
    threshold: float = CATASTROPHIC_THRESHOLD,
    agg: Aggregator = agg_min,
    aggregator_name: str = "min",
) -> RescueLedger:
    """Tasks that crossed ``threshold`` between the two arms.

    Defaults to the per-task *minimum* across seeds: a task counts as rescued
    only when its worst seed came off the floor. Using the mean would let a
    task with one surviving zero out of three seeds be recorded as a rescue,
    which is the opposite of a reliability claim.
    """
    pairs = paired_deltas(baseline, treatment, agg)
    rescued = tuple(
        p.task for p in pairs if p.baseline < threshold <= p.treatment
    )
    lost = tuple(p.task for p in pairs if p.treatment < threshold <= p.baseline)
    stayed_below = tuple(
        p.task for p in pairs if p.baseline < threshold and p.treatment < threshold
    )
    stayed_above = tuple(
        p.task for p in pairs if p.baseline >= threshold and p.treatment >= threshold
    )
    return RescueLedger(
        threshold=threshold,
        aggregator=aggregator_name,
        rescued=rescued,
        lost=lost,
        stayed_below=stayed_below,
        stayed_above=stayed_above,
    )


# --------------------------------------------------------------------------
# win / loss / tie
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class WinLossTie:
    """Per-task decomposition with an explicit noise band.

    A mean delta of +0.069 built from two large rescues and eight unchanged
    tasks is indistinguishable, in the mean, from a broad +0.069 improvement on
    every task -- and the two support completely different claims. This makes
    the difference unhideable: the tie count is a headline number.
    """

    noise_band: float
    band_source: str
    wins: tuple[TaskId, ...]
    losses: tuple[TaskId, ...]
    ties: tuple[TaskId, ...]

    @property
    def n(self) -> int:
        return len(self.wins) + len(self.losses) + len(self.ties)

    def render(self) -> str:
        return (
            f"{len(self.wins)}W / {len(self.losses)}L / {len(self.ties)}T "
            f"at noise band +-{self.noise_band:.4f} ({self.band_source})"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "noise_band": self.noise_band,
            "band_source": self.band_source,
            "wins": list(self.wins),
            "losses": list(self.losses),
            "ties": list(self.ties),
        }


def noise_band_from_seeds(
    arms: Sequence[ArmScores], *, k: float = 2.0, floor: float = MIN_NOISE_BAND
) -> tuple[float, str]:
    """Derive a noise band from across-seed spread; returns ``(band, source)``.

    Within-task across-seed variation is the only direct estimate of run-to-run
    noise available, so the band is ``k`` times the largest *median* within-task
    SD among the arms compared.

    Two choices worth their justification. The band takes the **median** across
    tasks, not the pooled RMS: pooling is dominated by exactly the one or two
    catastrophic tasks whose deltas the comparison is testing, so an RMS band
    would grow until it swallowed the effect it was supposed to adjudicate. And
    it takes the **max across arms**, because a band calibrated on the
    low-variance adapter arm (sigma ~= 0.003) would score ordinary jitter in the
    bare baseline (sigma ~= 0.081) as a loss.

    Falls back to :data:`DEFAULT_NOISE_BAND` when no arm has more than one seed
    per task, because with one run per cell the noise is unobserved, not zero.
    """
    medians: list[float] = []
    for arm in arms:
        if not any(len(arm.values(t)) > 1 for t in arm.tasks):
            continue
        medians.append(float(_median([arm.seed_sd(t) for t in arm.tasks])))
    if not medians:
        return DEFAULT_NOISE_BAND, "default (single seed per cell: noise unobservable)"
    observed = max(medians)
    band = max(observed * k, floor)
    source = f"{k:g}x max median across-seed SD ({observed:.4f})"
    if band > observed * k:
        source += f", raised to floor {floor:.3f}"
    return band, source


def win_loss_tie(
    pairs: Sequence[PairedDelta], *, noise_band: float, band_source: str = "supplied"
) -> WinLossTie:
    """Classify each task as win, loss, or tie against the noise band."""
    wins = tuple(p.task for p in pairs if p.delta > noise_band)
    losses = tuple(p.task for p in pairs if p.delta < -noise_band)
    ties = tuple(p.task for p in pairs if abs(p.delta) <= noise_band)
    return WinLossTie(
        noise_band=noise_band,
        band_source=band_source,
        wins=wins,
        losses=losses,
        ties=ties,
    )


# --------------------------------------------------------------------------
# the whole comparison
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Comparison:
    """Everything one paired arm-vs-arm comparison produces.

    Held as a value so the report renderer has no statistics in it and the
    numbers in a report are exactly the numbers that were computed.
    """

    baseline: ArmScores
    treatment: ArmScores
    aggregator: str
    pairs: tuple[PairedDelta, ...]
    bootstrap: BootstrapResult
    permutation: PermutationResult
    effects: EffectSizes
    wlt: WinLossTie
    tail_baseline: TailStats
    tail_treatment: TailStats
    rescues: RescueLedger

    @property
    def mean_delta(self) -> float:
        return self.effects.mean_delta

    @property
    def zero_rate_delta(self) -> float:
        return self.tail_treatment.zero_rate - self.tail_baseline.zero_rate

    @property
    def conclusive(self) -> bool:
        """Whether the paired evidence can distinguish the arms at all.

        Deliberately strict: an interval that exists and excludes zero, or a
        permutation test that is powered and rejects. Everything else is "we
        cannot tell" -- which, at n=10 with 2 movers, is the expected answer and
        must not be silently upgraded by reading a point estimate.
        """
        return self.bootstrap.excludes_zero or self.permutation.significant

    def to_dict(self) -> dict[str, object]:
        return {
            "baseline": self.baseline.label,
            "treatment": self.treatment.label,
            "aggregator": self.aggregator,
            "pairs": [
                {"task": p.task, "baseline": p.baseline, "treatment": p.treatment, "delta": p.delta}
                for p in self.pairs
            ],
            "mean_delta": self.mean_delta,
            "bootstrap": self.bootstrap.to_dict(),
            "permutation": self.permutation.to_dict(),
            "effects": self.effects.to_dict(),
            "win_loss_tie": self.wlt.to_dict(),
            "tail_baseline": self.tail_baseline.to_dict(),
            "tail_treatment": self.tail_treatment.to_dict(),
            "rescues": self.rescues.to_dict(),
            "conclusive": self.conclusive,
        }


def compare(
    baseline: ArmScores,
    treatment: ArmScores,
    *,
    aggregator: str = "mean",
    noise_band: float | None = None,
    noise_band_k: float = 2.0,
    catastrophic_threshold: float = CATASTROPHIC_THRESHOLD,
    rescue_threshold: float | None = None,
    resamples: int = 10_000,
    confidence: float = 0.95,
    alpha: float = 0.05,
    seed: int = 20260819,
) -> Comparison:
    """Run the full paired comparison of two arms scored on the same tasks.

    ``noise_band=None`` derives the band from across-seed spread rather than
    letting a caller pick a flattering one after seeing the deltas.
    """
    agg = AGGREGATOR_NAMES[aggregator]
    pairs = paired_deltas(baseline, treatment, agg)
    deltas = [p.delta for p in pairs]
    if noise_band is None:
        band, band_source = noise_band_from_seeds(
            [baseline, treatment], k=noise_band_k
        )
    else:
        band, band_source = noise_band, "supplied by caller"
    return Comparison(
        baseline=baseline,
        treatment=treatment,
        aggregator=aggregator,
        pairs=tuple(pairs),
        bootstrap=paired_bootstrap_ci(
            deltas,
            resamples=resamples,
            confidence=confidence,
            seed=seed,
            noise_band=band,
        ),
        permutation=paired_permutation_test(
            deltas, resamples=resamples, seed=seed, alpha=alpha, noise_band=band
        ),
        effects=effect_sizes(pairs, noise_band=band),
        wlt=win_loss_tie(pairs, noise_band=band, band_source=band_source),
        tail_baseline=tail_stats(
            baseline,
            catastrophic_threshold=catastrophic_threshold,
            resamples=resamples,
            confidence=confidence,
            seed=seed,
        ),
        tail_treatment=tail_stats(
            treatment,
            catastrophic_threshold=catastrophic_threshold,
            resamples=resamples,
            confidence=confidence,
            seed=seed,
        ),
        rescues=rescue_ledger(
            baseline,
            treatment,
            threshold=(
                catastrophic_threshold if rescue_threshold is None else rescue_threshold
            ),
        ),
    )
