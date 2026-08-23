# W9 — the evolution strategy as a pluggable arm

Owns `src/harness_evolve/evolvers/` and `tests/test_evolvers.py`. The only files
touched outside those paths are the package-map blocks in `README.md` and
`docs/ARCHITECTURE.md`, which `tests/test_docs_consistency.py` requires a new
module directory to appear in.

---

## 2026-08-23 — session 1: four arms and a comparison that can refuse

### Why this exists

Before this, there was exactly one evolution strategy in the repository, and it
was not a *choice* — it was the body of `core/search.py`. Pareto parent
selection, gated screening, and a four-clause regression gate are each defensible
and each traceable to a measured property of this task, but together they are one
point in a space, and a point with no neighbours to compare against is a claim
with no control.

arXiv:2607.12227 is the reason that matters here rather than being a matter of
taste. Its finding is that automatic harness evolution frequently fails to beat
trivial baselines once feedback and inference budgets are matched — and, more
damagingly, that the failures go unnoticed because the arms were never run under
one protocol at one enforced budget. We had already accepted that argument for
the *outer* comparison (W5's compute-matched baselines). We had not accepted it
for the search method itself, which is where it applies just as directly: our
gated search versus SkillOpt versus random sampling is exactly the comparison
that paper says nobody runs properly.

### The four arms, and what each one is for

| Arm | Accept rule | Selection basis | What it is testing |
|---|---|---|---|
| `gated_search` | four-clause `RegressionGate` (cliff, aggregate, new zeros, efficiency, cumulative-vs-seed) | anchor | the strategy we already had |
| `skillopt` | strict improvement on a **disjoint validation slice** | validation | does holding data out pay for itself at n≈6? |
| `ahe_component_wise` | two clauses: no aggregate drop past tolerance, no new zero | anchor | does a declared component schedule beat letting a proposer pick? |
| `random_search` | none | anchor | did any of the structure buy anything? |

All four return `archive.best()`. That is deliberate: the arms differ in *which
candidates they put in the archive and on which slice they scored them*, never in
how the winner is read off. Anything else would relocate the difference between
methods into the reporting, which is the same class of error the whole package is
built to prevent.

### Decisions, and what forced each one

**D1. Budget is enforced by the runner, not by the method.** `RolloutBudget` is a
hard cap in rollouts; `BudgetedRunner` charges it *before* each rollout and raises
`BudgetExhausted` on the one that would cross the line. There is no other path to
the simulator, so a method cannot overspend without going around its own runner.
The alternative — a counter each method promises to check — puts correctness of
the comparison in the hands of whoever writes the next arm.

`run_many` is overridden rather than inherited, so a runner with a batched
implementation still gets charged per rollout and a batch refused half-way
through still records what it spent. Rolling that back would be the more
"correct-looking" behaviour and would be a lie about what was executed.

**D2. Rollouts, not dollars, are the matched unit.** Cost is carried alongside
because it is what a reader checks, but matching on it would let a method whose
candidates happen to be cheaper per rollout take more of them.

**D3. Spend includes everything thrown away.** Screened-out, hygiene-blocked,
gate-rejected, and free-rejected candidates all sit on the ledger — the free ones
distinguishably, under their own labels, since a method that mostly fails for free
has not quietly been handed a larger share. `test_spend_counts_the_candidates_a_method_threw_away`
pins this by forcing SkillOpt to reject everything and asserting the full cap was
still spent.

**D4. `Search` is wrapped, not rewritten.** It carries 20+ tests and a
cumulative-drift clause that only surfaced when the loop was first run end to end.
`SearchEvolver` hands it a budgeted runner, catches the cap at the loop boundary,
and transcribes its decision log into the shared trace shape. The archive is an
attribute of the `Search` object, so catching `BudgetExhausted` outside `run()`
still leaves everything evaluated before the refusal available for selection —
which is why no change to `core/search.py` was needed at all.

The one behavioural decision made in the wrapper: the default candidate budget is
set to the rollout cap, an upper bound no search can reach, so the *rollout*
budget is what stops the loop. A candidate-count limit that bit first would make
this arm silently under-spend, and an under-spending arm in a matched comparison
is precisely the failure being guarded against.

**D5. The protocol does not mention a proposer.** Two of the four arms do not use
one. A protocol that required one would make the control inexpressible, and the
control is the most important arm.

**D6. One shared `EditVocabulary`.** Every arm without a proposer draws from the
same object — the same reachable candidate set, the same `proposers/edits.py`
add/delete/replace vocabulary, deterministic move enumeration. Giving the
sophisticated arms a richer action space than the baseline is the standard way to
manufacture a win.

**D7. Residual budget goes to re-measuring the winner.** Arms have different
per-candidate costs (SkillOpt pays for a propose pass plus a validation pass; the
component-cycling arm pays for one anchor pass), so each stops with a different
remainder, and remainders of a few percent are enough to push a comparison
outside a 10% tolerance. Leaving them unspent is not neutral — it hands the arm
with cheaper candidates the smaller budget. Extra seeds on the incumbent cannot
manufacture a better candidate (nothing new is proposed); they only sharpen the
estimate of the one already chosen, which at n=2 seeds is the quantity everything
downstream is about. See "possibly over-built" below.

**D8. The ranking measurement comes out of a separate purse.** SkillOpt selects on
its validation slice and the others on the anchor, so their reported means come
from different populations and putting them in one column would be the same error
in a smaller font. `compare_evolvers` scores every arm's *selection* on one common
slice at one common seed set, from a budget that is not the search budget. An arm
is not penalised for being measured and cannot be credited for it.

**D9. The comparison refuses, and the refusal carries the evidence.**
`BudgetMismatch` is raised when spends differ by more than the tolerance, and it
holds the partial `Comparison` — re-running four searches to find out which arm
was short would cost the whole budget again. `strict=False` waives the raise but
`Comparison.winner()` still refuses, so waiving the guard does not also waive the
conclusion.

### What each method does differently, and when I expect it to win

**SkillOpt** trades slice size for honesty. Its accept decision is made on tasks
that took no part in choosing the edit, which is the right protection against
selecting on the noise in a small slice — and it costs you those tasks in the
slice that does the choosing. **Prediction:** it wins when the anchor is large
enough that a 2-task hold-out is cheap, and when the score has real headroom, so
that "strictly better" is a bar something can clear. It loses when the hold-out
lands on tasks with no headroom, because then no edit can ever show a strict gain
and the method correctly returns its seed. That is not a hypothetical — it is
`test_a_method_can_lose_to_random_search`, and the construction is the honest
failure mode of holding data out at n=6, not a trick.

Its cheap rounds are an underrated advantage: on the default fixture it gets 11
rounds where the anchor-scoring arms get 7, because a validation pass over 2 tasks
costs a third of an anchor pass over 6.

**AHE-style** trades proposer freedom for coverage. A proposer picking its own
target concentrates on whatever it finds easiest to write about, which is prose;
the ablation says the gains are elsewhere. An explicit schedule guarantees every
component gets attention and makes an ablation of the schedule itself possible.
**Prediction:** it wins when the binding component is *not* the one a proposer
would pick — which the interface-dependence finding says is simulator-specific and
therefore unknown in advance, which is the whole argument for having a schedule.
It loses when one component dominates, because round-robin spends a fixed
fraction of the budget on components that cannot move.

The prediction-accuracy reordering is the only use of the prediction channel that
changes what the search *does* rather than what it reports. An unvisited component
is treated as maximally promising rather than maximally bad — the opposite
convention lets the order of the first cycle decide which components ever get
attention at all.

**Random search** is the control and is built to be able to win. Same budget, same
vocabulary, same final selection rule; candidates are drawn afresh from the seed
at a random edit depth rather than from the incumbent, because a random walk that
keeps its last step is hill climbing without a gate — a different method, and a
much weaker control. **Prediction:** it wins whenever the useful edits are shallow
(one or two lines) and the gate's job is mostly to reject noise that was not there.
In a deterministic mock with a clean gradient it does badly, because gating costs
nothing when there is nothing to gate against; in the real regime, where a
single unlucky zero-score termination is worth ~0.08 of cell sigma, it should be
much more competitive than it looks here.

### Honest answer to "which wins in a sample-starved, near-ceiling regime"

**Random search, or the null result, more often than anyone would like — and
`gated_search` second.**

The reasoning is not about search quality. At ~17 tasks, 2 seeds, and
in-distribution scores of 0.86–0.92, the between-candidate differences the
methods are choosing between are smaller than the measurement error on them.
Under those conditions:

- A method's accept rule is mostly a *variance filter*, not a quality filter. The
  strictest rule (SkillOpt) rejects almost everything and returns the seed. The
  loosest (random) accepts everything and then picks the luckiest measurement,
  which is a winner's-curse estimator — it will look good on the anchor and
  regress on held-out.
- The four-clause gate is the only arm whose rule is aimed at the quantity that
  actually moves here: zero-score terminations. Its per-task-cliff and
  new-zeros clauses are the ones with real signal, and they are *cheap* signal —
  a task going from 0.9 to 0.0 is far above the noise floor even at n=2, which is
  exactly why the tail is where the effect was found in the first place.
- Holding data out is the wrong trade at this n. SkillOpt's separation is correct
  in principle and unaffordable in practice; the 2 tasks it holds out are ~12% of
  the anchor and, given the effect is concentrated in ~2 of 10 tasks, there is a
  real chance the hold-out contains the entire effect or none of it.

So: I expect the honest ranking on held-out to be `gated_search` ≈ `random_search`
> `ahe_component_wise` > `skillopt`, with all four inside each other's confidence
intervals, and with `random_search` beating `gated_search` on the *anchor* while
losing to it on held-out. If that is what comes back, the finding is not "our
method is best" — it is "at this sample size the accept rule is doing more work
than the search, and the only clause earning its keep is the zero-rate clause."
That is a publishable null under arXiv:2607.12227, and it is a better result than
a two-point lift nobody can check.

### Possibly over-built

- **The residual top-up (D7).** It exists to make exact budget matching reachable,
  and it is real spend on real rollouts, but it is machinery in service of a
  tolerance rather than of the search. If the comparison were always run at a cap
  that is a common multiple of every arm's per-candidate cost, it would be
  unnecessary. Kept because that condition is fragile and silently violating it
  produces an unmatched comparison, which is the one failure mode this package
  exists to prevent.
- **`EvolverTrace.metadata` as an open dict.** Everything else here is a
  dataclass. Methods genuinely have things to say that no shared schema
  anticipates (SkillOpt's slice split, AHE's schedule history), so the escape
  hatch is deliberate, but it is the one place where a reader cannot tell from the
  types what will be there.
- **`Comparison.render()`.** A table plus per-arm reasons. Arguably belongs in
  `evaluation/report.py`. Left here because it is the thing that makes a
  comparison readable at the point of running it, and moving it would couple two
  workstreams for a formatting function.

### Known limitations, recorded rather than hidden

- **Consolidation strips all-or-nothing.** Removing unearned additions one at a
  time and keeping each removal on its own merit would be strictly better, and
  costs one full anchor evaluation *per line*. At ~25 minutes a rollout that is a
  different project. The all-or-nothing version recovers the case where the
  additions were inert and declines when at least one was load-bearing, which is
  most of the value at a twentieth of the price — and the declining case is a test
  (`test_ahe_consolidation_declines_when_the_shorter_document_measures_worse`),
  not an assumption.
- **The residual pass folds the archive's per-task mean in as a single
  observation** when the caller has no per-seed distribution to hand. All three
  in-repo arms do pass one; the fallback under-weights the original estimate.
  Documented at the call site rather than silently corrected, because the fix is
  to carry rollouts on `ArchiveEntry`, which is a shared dataclass three other
  workstreams depend on.
- **The move set is text-only.** `Edit` is line-and-anchor shaped, so a stop-policy
  move (retry budget, feedback shape, which checks run) cannot be expressed in it.
  That is a real gap for the AHE arm specifically, whose whole argument is that
  structure matters more than prose, and whose most structural component is
  therefore out of reach. Deferred rather than bolted on because *both* the AHE arm
  and the random control would need it simultaneously to stay matched — a policy
  move added to one arm and not the other reintroduces exactly the asymmetry D6
  removes. This is the first thing I would add.
- **`SearchEvolver` labels all its spend `search`.** The inner loop does anchor
  evaluation, screening, and probing through one runner and does not expose which
  is which, so the per-phase breakdown other arms produce is not available for
  this one. Fixing it means touching `core/search.py`.

### Open questions

1. **Does the accept rule or the search do the work?** The clean experiment is
   available now and costs nothing on the mock: run `gated_search` with the gate
   replaced by "accept everything" and see whether it becomes random search. If it
   does, the Pareto archive and gated screening are not contributing.
2. **Which single gate clause is carrying `gated_search`?** My bet is the new-zeros
   clause and nothing else. A four-arm comparison with one clause disabled per arm
   would settle it, and at mock prices it is free.
3. **Is SkillOpt's hold-out recoverable?** A rotating hold-out — a different pair of
   tasks each round, with acceptance requiring a gain on whichever pair is held out
   — would keep the separation without permanently sacrificing 12% of the anchor.
   Whether that is still "held out" in any meaningful sense is the question.
4. **Should the comparison's common measurement be the held-out slice?** It is the
   anchor today, which every arm optimised against, so the ranking it produces is
   optimistic for all of them and most optimistic for the arm that optimised the
   anchor hardest (random). Using held-out would be the honest choice and would
   spend the one slice the protocol permits touching exactly once. That is a
   protocol decision, not a W9 decision, and it belongs with W5.

### Tests

`tests/test_evolvers.py`, 20 tests, offline against the mock simulator and mock
runner, ~2s, $0. Coverage: the cap refuses the rollout that would cross it and a
mid-batch refusal keeps an honest ledger; spend counts discarded candidates; slices
refuse to overlap; all four arms run at an identical enforced budget; the
comparison refuses on mismatch and an unmatched comparison cannot become a verdict;
SkillOpt decides on a slice disjoint from the one that chose the edit, and returns
its seed when nothing strictly improves; AHE visits components in its declared
order, reorders by prediction accuracy, does not bury an unvisited component,
consolidates when the shorter document measures no worse and declines when it does
not, and never strips an edit the winner never absorbed; random search keeps a
candidate the regression gate would have refused; the gated-search arm still writes
the decision log it always did and stops on the cap rather than dying on it; and
**a method losing to random search is a reachable, asserted outcome.**
