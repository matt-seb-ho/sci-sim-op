# W10 — amortization and zero-marginal-cost accounting

Owns `src/harness_evolve/evaluation/amortization.py`,
`src/harness_evolve/evaluation/zero_marginal.py`, `tests/test_amortization.py`,
and additive edits to `src/harness_evolve/evaluation/report.py`. Nothing else
was touched.

---

## 2026-08-23 — session 1

### The problem

arXiv:2607.12227 gives harness evolution and test-time scaling the same budget
and finds evolution behind. Terminal-Bench 2.1, K=5, pass@1 averaged over three
models: direct 68.2, parallel 72.3, sequential 69.3, **evolution 67.4** — below
doing nothing with the extra budget. Held-out: +0.6 average, +0.0 on one model.

`evaluation/baselines.py` already runs that comparison against us and
`evaluation/report.py` renders a four-outcome verdict from it. What was missing
is the analysis that answers the critique rather than living beside it.

The answer is an asymmetry the matched-budget framing collapses. TTS is a
**recurring** per-task cost: best-of-k costs k× on every task, forever. A harness
artifact is a **one-time** cost that is free at inference thereafter. Charging
the search to a single benchmark run is a conservative check, not a deployment's
economics. The completion is the crossover point.

`docs/NOTES_2607.12227.md` §B and §C (written the same day, in a separate
workstream) state both arguments; this workstream is the implementation, and the
two agree on the gate: amortization is only available if the evolved harness
beats the seed at k=1.

### What I built

**`amortization.py`.** `AmortizationAnalysis` composes three values —
`OneTimeCost` (the constant term), two `ArmEconomics` (the two slopes), and a
`QualityPrecondition` — and returns an `AmortizationResult` that is either a
crossover schedule or an explicit refusal.

- `crossover_n(one_time, evolved, tts)` is the whole arithmetic:
  `floor(one_time / (tts - evolved)) + 1`, or `None`. Strict inequality — at the
  tie point the evolved arm has spent the same *and* additionally run a search,
  so the horizon where it is ahead is one task later. Rounding the other way
  would shave the comparison toward our own claim, which is the exact failure
  `baselines.plan_matched_k` exists to prevent.
- Reported in **all three** of rollouts, USD and wall-seconds, never one. They
  disagree routinely: in the test fixture the arms cross at 23 rollouts, 13 wall
  units and 37 dollars, because the evolved arm's rollouts are not
  proportionally cheaper. Publishing the earliest is the same selective
  reporting `BudgetLedger.match` refuses for budget matching.
- `BreakevenHorizon` converts n\* into calendar days at a stated deployment rate,
  and keeps the search's own wall-clock **separate** rather than folded in: a
  16–37 hour search is a delay before the first deployed task, a different
  scheduling fact from the rate at which the artifact pays back. It prints
  sub-day searches in hours, because "0.0 days of search" reads as free.
- `ArmEconomics.from_measured` / `from_result` divide a *measured* total by the
  task-solutions it produced, following `BudgetLedger.record_rollouts`: an
  estimated per-task cost would be exactly as trustworthy as the assertion it
  replaces, and it sets the slope that decides everything.

**The gate is two conditions, in order.** `QualityPrecondition.from_comparisons`
takes both comparisons and neither is optional:

1. **Beats the seed at k=1.** Same rule `report.decide` applies to the control
   (more wins than losses, positive mean, no task newly pushed below the
   catastrophic threshold), so the two cannot disagree. If this fails there is
   no numerator: the one-time cost bought nothing and dividing nothing over a
   longer horizon still yields nothing. This is checked first, rendered first,
   and produces the louder of the two refusal messages.
2. **Matches or beats the TTS arm.** Deliberately weaker than gate 1 — *equal*
   passes, because equal quality at lower recurring cost is the entire claim
   being tested. The matched-budget verdict continues to count a tie as a
   failure; these are different questions and both are printed.

Refusal is a value, not an exception path: `AmortizationResult.defined` is False,
`crossovers` is empty, and `crossover()` raises if called anyway. That is the
same stance `stats.BootstrapResult` takes when n is too small — the refusal
renders as prominently as a number would, because the situation it describes is
the one the paper reports as typical.

**`revalidation_interval`** is the one thing I added that nobody asked for and
that I think matters most. A one-time cost is one-time only while the artifact
stays valid; a base-model upgrade or a simulator release re-opens the search and
resets the constant term. Set the expected artifact lifetime in task-solutions
and `Crossover.outlives_revalidation` says whether the crossing is reached before
then. Left unset, the report prints the assumption as an assumption. Without
this the module would be a machine for producing arbitrarily favourable numbers
by extending the horizon.

**`zero_marginal.py`.** `ZeroMarginalLedger` takes the rollouts of a *donor* arm
— ideally the compute-matched baseline itself — runs each `ZeroMarginalMechanism`
over them, and splits the registered `Improvement`s by whether a mechanism
actually derived their key. The shipped mechanism, `DerivedConstraints`, wraps
`evidence.directives.ConstraintLedger` unchanged.

Four properties keep it honest:

- **Attribution is by key, minted from the mined evidence.** Nothing can be
  declared free. An improvement whose key no mechanism produced is search-funded
  regardless of what it is called, and support still has to accumulate before a
  complaint becomes a constraint.
- **Discovery is free; confirmation is not.** `confirmation_rollouts` reports
  what the search still spent putting derived constraints through the regression
  gate. Suppressing that number is precisely the special pleading this module is
  supposed to prevent.
- **`strictly_additive` is True only when the donor is a baseline.** Constraints
  mined from the *search's* rollouts are cheap, not free: those rollouts came out
  of the same envelope the baseline is handed, so the matched comparison is a
  real contest and the argument does not apply. The report says so in that case.
- **Zero renders as prominently as a favourable number.** A validator that emits
  verdicts rather than legal action spaces yields nothing, and the section then
  says the mechanism does not apply to that simulator.

**`report.py`** gains two optional fields and two sections after the verdict.
Amortization is **suppressed entirely when the verdict is `fails`** — it prints
the failure and no crossover, because amortization compares the cost of two
routes to the same quality and a system a baseline beat has not reached it. The
zero-marginal section renders unconditionally, including under a failing
verdict: where the gain came from is a fact about the result, not a defence of
it. Nothing in the verdict logic changed.

### Where the amortization argument is weakest

Four places, ordered by how much they worry me.

1. **The horizon is a free parameter and nobody audits it.** n\* = 23 sounds
   modest; n\* = 4,000 sounds modest too if you say "over the artifact's
   lifetime". The only real defence is `revalidation_interval`, and its value is
   an estimate someone supplies. If a reviewer wants one number to attack, that
   is the one, and they would be right to. I built the check; I cannot make
   anyone set it honestly.
2. **The quality gate accepts a tie, and ties are cheap to manufacture at n=10
   with two movers.** `Comparison.conclusive` is expected to be False in this
   regime, so "matches the TTS arm" will usually rest on an underpowered
   comparison that could not have detected a real difference either way. The gate
   is directional-only by design (it must not require significance, or an
   underpowered tie would block a legitimate cost argument), but that means it
   passes in exactly the situations where we know the least. The one-sided
   protection is that gate 1 is *not* a tie test — the evolved arm must actually
   beat the seed — so a system that measured nothing anywhere still gets refused.
3. **Per-task cost is measured on the held-out slice, and deployment is not the
   held-out slice.** The slope that decides the crossover comes from ten tasks at
   three seeds. If deployed tasks are systematically harder, the evolved arm's
   per-task cost rises (more retries, more tool calls) and the TTS arm's rises
   with it, but not necessarily proportionally. The crossover is a point estimate
   with no interval on it, and I deliberately did not put one on it: a CI
   computed from these ten tasks would be quoted, which is the failure `stats.py`
   is built around.
4. **The one-time cost is understated by everything we did not count.** The
   ledger records the search's rollouts. It does not record the human time spent
   designing the manifest, the proposer prompts, the check plugins, or this
   evaluation package. A strict accounting of "one-time cost" would include the
   engineering, and then the crossover moves a long way right. The defence is
   that TTS has design cost too and it is much smaller — but that is a claim, not
   a measurement, and I have not measured it.

### What would have to be true for it to be wrong

- **The evolved harness does not beat the seed at k=1.** Then the whole section
  is void, and the code returns a refusal rather than a number. This is the
  pre-registered likely outcome (`worklogs/00_OVERALL.md`: RLMOpt and MAGE
  jointly predict the search returns its seed at N=17 with a 0.86–0.92 seed).
  Amortization does not rescue that case and was not built to.
- **Artifacts turn over faster than they amortize.** Model releases in this
  lineage have been roughly monthly. If an adapter's useful life is shorter than
  n\*, the crossover is arithmetic about a world that does not arrive.
- **A deployment does not actually run at k=1.** The comparison assumes the
  evolved arm ships without scaling. If a real deployment runs the evolved
  harness *with* best-of-k — which it would, because they compose — then the
  right comparison is evolved-plus-scaling against seed-plus-scaling, both
  recurring, and the one-time/recurring asymmetry stops being the interesting
  axis. This is the objection I have the least answer to, and the module does not
  model it. It is the honest reason amortization is a *supplement* to the matched
  comparison rather than a replacement for it.
- **The zero-marginal mechanism derives nothing on a given simulator.**
  `actionable_fraction` in the directive ledger and a zero here are the same
  finding from two directions, and both are supposed to be visible.

### Honest assessment

The zero-marginal argument answers arXiv:2607.12227 head-on and the amortization
argument does not; it reframes. The difference is that zero-marginal cost is a
**structural** property — a mechanism whose input is the baseline's own output
is additive to the baseline at every budget, so there is no matched comparison
that can exclude it. That is a statement about the scope of the critique.
Amortization, by contrast, accepts the matched comparison entirely and then
argues about which cost model a deployment should use. That is a legitimate
argument and it is not a dodge, but it changes the question rather than answering
the one asked. Which is precisely why the code refuses to print it when the
verdict is `fails`: the reframe is only admissible after the original question
has been answered in our favour.

### Scope notes

- `evaluation/__init__.py` was **not** touched, so the two new modules are
  imported by path (`harness_evolve.evaluation.amortization`). The workstream
  brief enumerated the files I own and `__init__.py` was not among them; whoever
  next edits it should re-export `AmortizationAnalysis`, `ZeroMarginalLedger` and
  their value types.
- `tests/test_docs_consistency.py::test_package_map_lists_every_module_directory`
  fails on both README and ARCHITECTURE, for `src/harness_evolve/evolvers/` — an
  untracked package from a concurrent workstream that is not in either package
  map. Not caused by, and not fixable from, this workstream. Everything else
  passes: 486 passed, 2 skipped, of which 34 are `tests/test_amortization.py`.
