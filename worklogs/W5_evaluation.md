# W5 — evaluation protocol (baselines, paired statistics, reports)

Owns `src/harness_evolve/evaluation/` and `tests/test_evaluation.py`. Nothing
outside those paths was touched.

---

## 2026-08-19 — session 1: the whole protocol

### Why this workstream is shaped the way it is

arXiv:2607.12227 says automatic harness evolution does not consistently beat
simple test-time scaling once feedback and inference budgets are matched, and
generalizes poorly off the search benchmark. Its argument bites here: harness
evolution *is* an iterative search that repeatedly evaluates candidates against
task feedback, so a gain over one un-evolved run is confounded with having spent
more compute. The predecessor reported "+0.069 from self-evolution" with no
compute-matched baseline anywhere, which makes it unfalsifiable rather than
wrong. Everything in this package is machinery for making the next claim
checkable by a reader who starts out sceptical.

Second constraint, from the measurement itself: n is tiny (3 seeds, <=17 search
tasks, 10 held out), the effect is two catastrophic-failure rescues out of ten
tasks, and the mechanism is *variance collapse* (adapter cells sigma ~= 0.002-0.005
vs bare sigma ~= 0.081, all of it zero-score runs). So means are the wrong headline
and most standard statistics are underpowered by construction. The design goal
was therefore not "compute a p-value" but "make the honest answer representable
and prominent".

### Statistical choices

**Paired throughout, task as the unit.** Between-task spread on this benchmark
(0.35-0.95) dwarfs the effect; it cancels exactly under pairing.
`paired_deltas` refuses on a task-set mismatch rather than intersecting,
because under failures-as-zero a missing task is usually a task the weaker arm
crashed on, and silently intersecting turns a reliability difference into a
survivorship comparison.

**Bootstrap variant: percentile, over tasks.** Resampling tasks (not runs)
because tasks are what we generalize over. Percentile rather than BCa: BCa's
acceleration is a jackknife over the same ten tasks, and when two of them carry
the whole effect the leave-one-out statistic is dominated by exactly those two,
so the correction is itself a two-point estimate and the endpoints acquire
precision the data cannot support. Percentile is transparently a re-description
of the empirical delta distribution, which is the honest object at n=10. The
guard rails do the work a bias correction could not.

**Effect size: matched-pairs rank-biserial correlation (primary).** Bounded in
[-1,1], no dispersion estimate in the denominator, invariant to the (definitely
non-linear) map from deck quality to similarity score. Every standardized mean
difference divides by a spread estimated from the same handful of tasks, where
that spread is dominated by whether the two rescued tasks are in the sample; d_z
swings for reasons unrelated to the effect and is unbounded on a bounded
outcome. Its known cost — rank measures are deaf to magnitude, so a 0.36->0.76
rescue ranks like a 0.001 drift — is why it is reported next to
`headroom_capture` (`sum(delta) / sum(1 - baseline)`: the fraction of remaining
headroom captured, the right magnitude measure for a saturating bounded score)
and next to the tail statistics. `cohens_dz` is computed and labelled
diagnostic-only so a reader who expects it can find it without being led by it.

**Permutation: exact sign-flip whenever possible.** Exchangeability assumed is
the paired null; that is far weaker than normality, which is untenable when the
delta distribution is a spike at zero plus two large positives. Only movers are
enumerated (flipping a zero delta changes nothing), which is also why
`min_achievable_p` is governed by the mover count: with 2 movers the smallest
two-sided p attainable is 0.5. Reporting that ceiling next to the p-value is
what stops "p=0.5" from being read as evidence of no effect.

**Noise band is derived, not chosen.** `noise_band_from_seeds` = k x the max
across arms of the *median* within-task across-seed SD, floored at 0.01.
Median, not pooled RMS: pooling is dominated by the same catastrophic tasks
whose deltas are under test, so an RMS band grows until it swallows the effect
it was meant to adjudicate. Max across arms, because a band calibrated on the
low-variance adapter would score ordinary jitter in the bare baseline as a loss.
Floor, because three seeds cannot demonstrate a tighter band and a similarity
score is not stable to better than ~0.01 under irrelevant deck reorderings.

**Tail statistics are first-class**, not an appendix: zero rate with a
task-clustered bootstrap CI (seeds within a task fail together; an unclustered
interval would be too narrow by roughly the cluster factor) plus a naive Wilson
interval reported beside it and labelled naive; per-task minimum; catastrophic
run count; and a `RescueLedger` naming the tasks that crossed the cliff. Rescue
detection defaults to the per-task *minimum* across seeds — a task with one
surviving zero out of three seeds is not rescued, and using the mean would
record it as such.

**Win/loss/tie** with the derived band, because 2W/0L/8T and "a broad +0.097 on
every task" are the same mean and completely different claims.

### What the guard rails refuse to do

- No CI below `MIN_N_FOR_CI = 6` paired tasks. At n=4 the 2.5th percentile of
  the resample distribution is decided by whether one particular task was drawn;
  the endpoints are quantization artifacts wearing a confidence level.
- No CI when fewer than `MIN_MOVERS_FOR_CI = 3` tasks moved beyond the noise
  band — i.e. exactly the reported situation. The interval would describe the
  movers, not the task population.
- The cluster bootstrap refuses below 6 task clusters for the same reason.
- Refusals are values (`BootstrapResult.refusal`, `reportable=False`), render as
  "**no CI** — <reason>", and propagate into the verdict as `indeterminate` or
  `mechanism_only`. `Comparison.conclusive` is strict: a point estimate can
  never be upgraded into a finding by a reader in a hurry.
- The permutation test never refuses (it is exact) but always publishes
  `min_achievable_p` and `underpowered`.

### Budget matching, made auditable

`BudgetLedger` accounts every arm — the search included — in three kinds of
unit: **rollouts**, **attempts** (agent attempts inside a rollout: initial try
plus stop-hook retries), and every `Cost` field. `record_rollouts` sums cost
from the actual `Rollout` objects rather than estimating, since an estimated
ledger is exactly as trustworthy as the assertion it replaces. `match()` reports
the ratio in *every* unit and marks units where the reference spent nothing as
`unmeasured`, so a runner that never populates `usd` cannot appear perfectly
matched. `render_markdown` prints the table into the report.

The unavoidable honesty point the ledger forces: **parallel and sequential
scaling are not matchable in the same unit.** Best-of-k spends k rollouts per
cell; refinement spends one rollout containing k attempts. So a claim must name
its unit, and `VerdictCriterion.budget_unit` does.

`plan_matched_k` converts the search's rollout spend into k and rounds *up* by
default, giving leftover budget to the baseline. Rounding the other way shaves
the comparison toward our own claim; the resulting over-spend is recorded as
`surplus` and printed.

**Baselines.** (1) `SeedControl` — seed adapter, same seeds, no extra budget;
the cheapest and most important arm. (2) `BestOfK` — k independent draws per
cell, with *both* selectors: `oracle_best` (labelled everywhere as an
unrealizable upper bound, since the score is similarity to a held-out reference
deck) and `ValidatorBest` (picks on validator evidence, structurally unable to
see `Score`; ties break on cost then order, never on score). Their difference is
reported as `selection_gap`, and it is itself a result: a large gap means the
parallel-sampling headline is unreachable in deployment. (3)
`SequentialRefinement` — expressed through the seed adapter's own
`stop_policy.retries`, because that policy *is* this harness's refinement
mechanism; comparing against a bespoke refinement loop would be comparing
against a harness we do not have. It raises rather than clamps when k exceeds
the policy's cap of 7 attempts, since a clamped baseline under-spends exactly
the budget it was supposed to match.

### Slice discipline

`EvaluationProtocol` refuses rather than warns. Held-out for any purpose other
than the final report raises; held-out is released exactly once, and a second
release raises even for the same candidate ("we only looked twice" is how a
held-out set becomes a validation set, and the object cannot distinguish an
innocent re-read from a second selection round); probe for selection raises;
overlapping slices raise at construction. Two after-the-fact guards catch the
other route into contamination — a cached corpus or a hardcoded task list:
`assert_selection_safe` rejects non-anchor rollouts at the point of a selection
decision, `assert_final_arm` rejects a final arm assembled without an audited
release. Every access is an `AccessRecord`; `render_audit()` puts the trail in
the report. `from_split` is deterministic (sorted ids) so a split cannot be
re-drawn after seeing results.

### Report

`EvaluationReport` renders configuration header (model x harness config per row,
per arXiv:2605.27922 — no row is labelled with a bare system name), criterion,
budget ledger, per-task paired table, paired statistics, tail statistics,
verdict, audit trail. The criterion renders *above* every number and the verdict
is computed from it by `decide()`, never written by hand. Four outcomes:
`survives`, `mechanism_only` (beats control and matched baselines on the tail
mechanism, but the paired tests cannot confirm it — the expected honest answer
at this n), `indeterminate`, `fails`. An arm the ledger cannot vouch for is
dropped from the decision and named; with no ledger at all the verdict is
`fails`, because an unmatched comparison tests nothing.

### Tests

40 tests in `tests/test_evaluation.py`, all fixtures inline, no `/data`
dependency. Notable: bootstrap against a degenerate known case and against
normal theory at n=200; exact permutation p = 2/1024 on a constructed uniform
effect; both guard rails firing; the **tail-driven fixture** (2 rescues, 8
unchanged) paired against a broad-gain fixture constructed to have *the same
mean*, asserting that the mean cannot tell them apart while W/L/T, rescues,
zero rate, and pooled seed SD all can; the validator selector picking the
*lower-scoring* draw when validator evidence disagrees with score (a selector
that peeked would fail the test); and the protocol raising on held-out during
selection, on a second release, and on contaminated selection rollouts.

### Deliberately not built

- No multiplicity correction across arms. With four arms and a test that cannot
  reach p<0.5 on the real fixture, a Bonferroni factor would be theatre; the
  verdict requires beating *every* baseline, which is the stricter rule anyway.
- No Bayesian / hierarchical model over tasks x seeds. It would produce a
  posterior with confident-looking intervals from priors doing most of the work
  — the exact failure mode the guard rails exist to prevent.
- No power analysis / minimum detectable effect calculator. `min_achievable_p`
  and the refusal messages already say what the design can and cannot see.
- No plotting, no HTML, no persistence layer. Markdown out, `to_dict()` on
  every value type for whoever wants to serialize.
- No re-implementation of a refinement loop; sequential scaling goes through the
  existing stop policy on purpose.

### Open questions / notes for the integrator

0. **`Rollout` gained a `slice` field while this workstream was in flight**
   (`types.py`, not mine to edit). `assert_selection_safe` now rejects a rollout
   if *either* the protocol's task lists or the rollout's own label say
   non-anchor — agreement between the two is not assumed, because the label goes
   stale on a resumed run and the task lists go stale on a re-split. It is read
   with `getattr` so the guard survives either version of the contract.
1. **Validator-event schema is not frozen by the shared contracts.**
   `Rollout.validator_events` is `list[dict]` with no agreed keys.
   `validator_error_proxy` reads `severity`/`level`/`kind` defensively and falls
   back to an `errors` count. If W6's runners settle on a shape, the proxy
   should be tightened — or callers pass their own `ValidatorBest(proxy=...)`.
2. **`SequentialRefinement.refined_candidate()` produces a new `cid`** (it edits
   the stop policy through `Candidate.with_edits`, which bumps generation and
   sets `parent`). It is the seed adapter with a widened policy, not a searched
   candidate; reports should label it that way, and the archive should not
   ingest it.
3. **Attempt accounting assumes the stop policy is honoured.** `attempts` is
   derived as `retries + 1` per rollout; if a runner terminates early on
   success, actual attempts are fewer and the ledger over-states the baseline's
   spend (conservative direction, but W6 could report actual attempt counts in
   `Cost` or `Rollout` and we would use them).
4. **`Cost` has no attempts/rollout field**, which is why attempts live on
   `BudgetEntry` instead. If `types.py` ever unfreezes, an `attempts` field on
   `Cost` would make the ledger derivable straight from rollouts.
5. **Who records the search's own spend?** The ledger has a `search` arm by
   convention (`EvaluationReport.search_arm`); the search loop (W1) must call
   `ledger.record_rollouts("search", ...)` for every rollout it spends,
   including rejected candidates and free-gate re-runs. If it does not, the
   verdict comes back `fails` for lack of an audited match — deliberately, but
   the integrator should wire it rather than discover it.
6. **The anchor slice is scored by the search; the held-out slice must be run
   for the baselines too.** Budget matching is about the *search's* total spend
   versus the baselines' spend on the held-out slice; those are different task
   sets, and the ratio is only meaningful under the assumption that a rollout
   costs about the same on both. Worth stating in the paper rather than hiding
   in the ledger.
