"""Independent verification of the statistics against hand-computed values.

These are not the statistics module's own tests — it has those. These check the
same quantities from the outside, against values worked out by hand, because the
module produces the number that decides whether a result gets believed and
"the tests pass" and "the arithmetic is right" are different claims when the
tests were written by whoever wrote the code.

The cases are chosen to catch the failure modes that would be invisible in a
report: an inverted sign, a permutation test that cannot reject, a noise band
that swallows the effect, a rescue ledger pointing the wrong way.
"""

from __future__ import annotations

import statistics

import pytest

from harness_evolve.evaluation.stats import (
    ArmScores, agg_mean, compare, noise_band_from_seeds, paired_deltas,
)


def test_delta_sign_is_treatment_minus_baseline():
    """An inverted sign would turn every loss into a win and still look sane."""
    b = ArmScores("b", {"t1": (0.5,), "t2": (0.8,)})
    t = ArmScores("t", {"t1": (0.7,), "t2": (0.6,)})
    d = paired_deltas(b, t, agg_mean)
    assert d[0].delta == pytest.approx(0.2)
    assert d[1].delta == pytest.approx(-0.2)


def test_delta_is_antisymmetric_under_swapping_arms():
    b = ArmScores("b", {"t1": (0.5,), "t2": (0.8,)})
    t = ArmScores("t", {"t1": (0.7,), "t2": (0.6,)})
    assert compare(b, t, noise_band=0.0).mean_delta == pytest.approx(
        -compare(t, b, noise_band=0.0).mean_delta
    )


def test_exact_permutation_p_matches_a_hand_enumeration():
    """Three tasks, all moving the same way: two-sided sign-flip over 2^3 = 8
    assignments reaches |mean| >= observed only at all-positive and
    all-negative, so p = 2/8."""
    b = ArmScores("b", {"a": (0.0,), "b": (0.0,), "c": (0.0,)})
    t = ArmScores("t", {"a": (0.3,), "b": (0.2,), "c": (0.1,)})
    c = compare(b, t, noise_band=0.0)
    assert c.mean_delta == pytest.approx(0.2)
    assert c.permutation.p_value == pytest.approx(0.25)


@pytest.mark.parametrize("n", [3, 4, 5, 6, 7])
def test_minimum_achievable_p_is_two_over_two_to_the_n(n):
    """The number that stops p = 0.25 being misread as weak evidence of no
    effect. Below n=6 movers, alpha=0.05 is unreachable at any outcome."""
    b = ArmScores("b", {f"t{i}": (0.0,) for i in range(n)})
    t = ArmScores("t", {f"t{i}": (0.1 * (i + 1),) for i in range(n)})
    c = compare(b, t, noise_band=0.0)
    assert c.permutation.min_achievable_p == pytest.approx(2 / (2 ** n))
    assert (c.permutation.min_achievable_p <= 0.05) == (n >= 6)


def test_noise_band_uses_sample_sd_and_the_median_across_tasks():
    """Pinned because the choice has a real consequence at our seed count.

    `seed_sd` is the *sample* SD (n-1). At n=2 seeds — the search configuration —
    that is sqrt(2) ~= 1.41x the population SD, so the noise band is ~41% wider
    than a population-SD band would be. Wider band means more ties and fewer
    wins: the gate is more conservative exactly where the evidence is thinnest,
    which is the right direction, but it is a consequence of an estimator choice
    rather than something anyone selected, so it is asserted here rather than
    left implicit.
    """
    a = ArmScores("a", {"t1": (0.5, 0.6), "t2": (0.5, 0.7)})
    sample_median = statistics.median(
        [statistics.stdev([0.5, 0.6]), statistics.stdev([0.5, 0.7])]
    )
    band, source = noise_band_from_seeds([a], k=2.0)
    assert band == pytest.approx(2 * sample_median)
    assert band > 2 * statistics.median(
        [statistics.pstdev([0.5, 0.6]), statistics.pstdev([0.5, 0.7])]
    )
    assert "median" in source


def test_noise_band_takes_the_max_across_arms():
    """A band calibrated on the low-variance adapter arm would score ordinary
    jitter in the bare baseline as a loss."""
    quiet = ArmScores("quiet", {"t1": (0.90, 0.90), "t2": (0.90, 0.90)})
    noisy = ArmScores("noisy", {"t1": (0.10, 0.90), "t2": (0.20, 0.80)})
    both, _ = noise_band_from_seeds([quiet, noisy], k=2.0)
    only_quiet, _ = noise_band_from_seeds([quiet], k=2.0)
    assert both > only_quiet


def test_tail_counts_are_over_runs_not_tasks():
    """Under failures-as-zero the zero *rate* is the reliability claim, and
    collapsing runs to tasks first would hide an intermittent failure."""
    z = ArmScores("z", {"t1": (0.0, 0.9), "t2": (0.9, 0.9), "t3": (0.0, 0.0)})
    g = ArmScores("g", {"t1": (0.9, 0.9), "t2": (0.9, 0.9), "t3": (0.9, 0.9)})
    c = compare(z, g, noise_band=0.0)
    assert c.tail_baseline.n_runs == 6
    assert c.tail_baseline.zero_runs == 3
    assert c.tail_treatment.zero_runs == 0
    assert c.tail_baseline.per_task_min["t1"] == 0.0


def test_rescue_ledger_points_the_right_way():
    """An inverted ledger would report the mechanism working while it failed."""
    z = ArmScores("z", {"t1": (0.0, 0.9), "t2": (0.9, 0.9), "t3": (0.0, 0.0)})
    g = ArmScores("g", {"t1": (0.9, 0.9), "t2": (0.9, 0.9), "t3": (0.9, 0.9)})
    c = compare(z, g, noise_band=0.0)
    assert sorted(c.rescues.rescued) == ["t1", "t3"]
    assert list(c.rescues.lost) == []

    back = compare(g, z, noise_band=0.0)
    assert sorted(back.rescues.lost) == ["t1", "t3"]
    assert list(back.rescues.rescued) == []


def test_win_loss_tie_respects_both_band_and_direction():
    b = ArmScores("b", {"w": (0.10,), "l": (0.90,), "t": (0.50,)})
    t = ArmScores("t", {"w": (0.90,), "l": (0.10,), "t": (0.51,)})
    w = compare(b, t, noise_band=0.2).wlt
    assert list(w.wins) == ["w"]
    assert list(w.losses) == ["l"]
    assert list(w.ties) == ["t"]


def test_bootstrap_is_reproducible_and_brackets_its_point_estimate():
    b = ArmScores("b", {f"t{i}": (0.4,) for i in range(12)})
    t = ArmScores("t", {f"t{i}": (0.4 + 0.05 * (i % 5),) for i in range(12)})
    r1 = compare(b, t, noise_band=0.0, resamples=2000, seed=7).bootstrap
    r2 = compare(b, t, noise_band=0.0, resamples=2000, seed=7).bootstrap
    assert (r1.interval.low, r1.interval.high) == (r2.interval.low, r2.interval.high)
    assert r1.point == pytest.approx(
        statistics.mean([0.05 * (i % 5) for i in range(12)])
    )
    assert r1.interval.low <= r1.point <= r1.interval.high


def test_a_genuinely_null_effect_is_not_significant():
    b = ArmScores("b", {f"t{i}": (0.5,) for i in range(10)})
    t = ArmScores("t", {f"t{i}": (0.5,) for i in range(10)})
    c = compare(b, t, noise_band=0.05)
    assert c.permutation.p_value == pytest.approx(1.0)
    assert not c.conclusive


def test_mismatched_task_sets_are_refused_rather_than_intersected():
    """Comparing over 'whichever tasks both arms finished' is a survivorship
    comparison, and under failures-as-zero a missing task is usually one the
    weaker arm crashed on."""
    b = ArmScores("b", {"t1": (0.5,), "t2": (0.5,)})
    t = ArmScores("t", {"t1": (0.7,)})
    with pytest.raises(ValueError, match="identical task sets"):
        paired_deltas(b, t, agg_mean)
