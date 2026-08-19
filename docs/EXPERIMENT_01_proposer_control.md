# Experiment 01 — can the search beat a random-edit control?

**Date:** 2026-08-19 · **Cost:** $0 · **Runtime:** ~40 s · **Script:**
`scripts/experiment_proposer_control.py`

## What this is and is not

Run entirely against the **mock** simulator and runner. It says **nothing about
GEOS**. Two things it does say, both worth knowing before any real
infrastructure exists:

1. **A falsification test of the machinery.** The mock world has a *planted*
   gradient with a known optimum. If the search cannot beat a random-edit
   control here — noise controllable, gradient guaranteed — it certainly will
   not on a domain-knowledge-bound task with a near-ceiling reward. Failing this
   would be a conclusion about the code, not the method.
2. **A rehearsal of the whole stack** — search, gate, archive, budget ledger,
   paired statistics, tail statistics — composing into an experiment rather than
   merely into a library.

The control is not a straw man. `RandomEditProposer` obeys every rule the real
proposer does: one bounded edit, a prediction attached, budgets enforced, the
same gate. It differs only in drawing from a line pool that mixes useful phrases
with plausible-but-inert filler, versus one that contains only useful ones. That
is the honest synthetic analogue of a proposer that diagnoses versus one that
churns — and since harness-*updating* capability is reported roughly flat across
model tiers (arXiv:2605.30621), the question is live.

**Setup:** 4 trials × 10 candidates per arm, 10 tasks (3 with planted
difficulty), 2 seeds during search, winners re-scored at 3 *fresh* seeds so the
reported number is not the one selection maximised.

## Result

```
arm         trials   accept   rollouts   final mean
informed         4   56-75%    176-220       0.4493
control          4   25-75%    196-218       0.3148
seed adapter                                 0.1865
```

Both arms moved off the seed (informed +0.263, control +0.128). **The machinery
works: the search climbs a planted gradient.**

### The mean comparison is inconclusive — correctly

```
mean delta          +0.1345
bootstrap CI        REFUSED — only 0 of 10 tasks moved by more than the
                    noise band 0.305; an interval would describe the movers,
                    not the task population
permutation p       1.000  (min achievable 1.000)
win / loss / tie    0 / 0 / 10   (band = 2x max median across-seed SD)
```

A visible 0.13 mean gap, and the statistics refuse to call it. That is the
correct answer: the across-seed spread is large enough that no per-task delta
clears the band, and with zero movers **no design at this n could reach
significance** — which `min_achievable_p = 1.000` states outright rather than
letting a p-value near 1 be misread as weak evidence of no effect.

### The reliability difference is unambiguous

```
            zero runs      rate    95% CI              catastrophic runs
control       17/120      0.142    [0.108, 0.183]              41
informed       5/120      0.042    [0.000, 0.083]              20
rescued 4 tasks, lost 0
```

Non-overlapping intervals, catastrophic runs halved, four tasks rescued and none
lost.

## Why this matters more than the ranking

**The two views disagree, and the disagreement is the point.** On the mean, this
comparison is a tie with no path to significance. On the tail, it is a clear,
separable effect.

That is exactly the shape of the finding this project is built around — adapters
buy reliability rather than average quality, and a cell mean at small n cannot
distinguish rescuing the tail from getting lucky on it — reproduced here in
miniature on a synthetic world. It is a direct check that the evaluation stack
surfaces the mechanism a mean would bury, which is the property the whole
protocol exists to guarantee.

It also means the honest verdict for a run of this shape is `mechanism_only`:
the effect is real and localised, and the aggregate cannot carry it. Reporting
the mean gap alone would overclaim; reporting the tie alone would miss the
effect entirely.

## Caveats

- Synthetic world, planted gradient, no domain knowledge involved. Transfer to
  GEOS is **not** implied.
- 4 trials per arm. The trial-to-trial spread (informed 0.343–0.560) is wide
  relative to the gap between arms.
- The "informed" arm is given the right vocabulary by construction. It models a
  proposer that diagnoses correctly, not one that has to.
- The mock's zero-rate model and the simulator's are independent; only the
  runner's is exercised here.

## What to do with it

- Re-run as a regression check whenever the gate or the archive changes. A
  search that stops beating the control on a planted gradient has a bug.
- Treat the `mechanism_only` shape as the *expected* reporting outcome for the
  real experiment, not a disappointment.
- The next version should use the real `LLMProposer` against a scripted
  control, once an API key and a budget are available.
