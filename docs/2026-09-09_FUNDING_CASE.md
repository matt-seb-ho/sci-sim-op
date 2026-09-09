# Compute funding request — LLM agents for scientific simulation

**For:** project advisor · **Prepared:** 2026-09-09 · **Ask: $400 of API credit.**

**Every cost below is measured on real rollouts of this pipeline, not estimated from a
rate card.** Where an earlier number was wrong, it is corrected here and the reason is
given. The work to date was funded personally; that is not sustainable and is the reason
for this request.

---

## 1. The ask, and what it buys

| | |
|---|---|
| **Requested** | **$400** |
| Core experimental programme | $70 |
| Two additional simulators (OpenFOAM, LAMMPS) | $140 |
| Cross-model panel + replication | $100 |
| Contingency (1.4×, re-runs and defects) | $90 |

**$400 is roughly two days of one GPU on a cloud instance.** The reason it is this small
is the project's central constraint: we have no training budget, so the method optimizes
the *harness* around a frozen model and spends inference instead of gradient steps.

## 2. What the money answers

One question, framed so that it is publishable whichever way it resolves:

> **Does harness self-evolution produce a real, generalizing gain for scientific-simulator
> configuration when the train/test split is clean, the baselines are compute-matched, and
> the error bars are reported — and if so, which ingredient carries it?**

This matters because the field currently cannot answer it:

- Of six methods surveyed, **only one uses a three-way split**. One has no split at all;
  another adapts on the test stream.
- **None of the three main comparison papers reports any dispersion statistic or
  significance test.** Every published delta is a point estimate over ≤2 repeats.
- The one paper with a genuinely disjoint split (arXiv:2607.12227) finds harness evolution
  gains **+1.2 and +0.0** held-out, scores **below its own starting harness** without unit
  tests, and **loses to plain parallel sampling at matched compute**.
- In our own predecessor codebase, **11 of the 17 tasks its self-evolution loop optimized
  on sat inside its own designated test split.**

So the contribution is not "we made self-evolution work." It is **"here is what it is worth
when measured properly"** — with a clean split and error bars nobody in this literature
currently reports. **A null is a publishable result** and is pre-registered as such.

## 3. Why the funding is credible now: the pipeline has been de-risked

The last two weeks were spent making the measurement trustworthy rather than making the
number look good. **Eight defects were found, each of which would have produced a
plausible, publishable number that meant something other than its label.** Six sat in the
path between a rollout and a reported score:

| | defect | what it would have produced |
|---|---|---|
| F1 | replay key ignored the inference model | a baseline replayed from a different model, at $0.00 |
| F2 | proposer pointed at a retired model slug | "search returns its seed" — the right answer for the wrong reason |
| F7 | timed-out rollouts scored before the workspace finished copying | fabricated zeros, which then nominated their own tasks as search anchors |
| F8 | infrastructure failures averaged into candidate scores | a manufactured *positive* result in a campaign pre-registered to expect a null |
| R1 | stop-policy setting that no consumer read | a search over a knob nothing observed, looking entirely normal in the logs |
| — | hygiene gate blocking every candidate | 0% acceptance, so the "null" was an artifact |

**The through-line: in a harness-evolution loop the dangerous bugs are not the ones that
crash, they are the ones that produce a plausible number.** Every one was found by running
the pipeline and reading what it actually produced — none by reading code. All are fixed,
with tests (579 in the search repo, 66 in the evaluation harness).

This is the strongest argument for funding: **the instrument is now calibrated.** Money
spent from here buys measurements rather than debugging.

## 4. What has been measured

| | |
|---|---|
| Real GEOS rollouts to date | **109** |
| Seed baseline, 6 tasks | mean 0.655, zero rate 0.000 |
| Paired champion vs seed | **+0.116, 95% CI [−0.083, +0.314] — spans zero** |
| Replication of the one decisive cell | **did not replicate** |
| Cost per rollout | **$0.134** (measured, §5) |

The honest reading: **no effect this design can resolve, and the apparent effect was one
cell that failed to replicate.** That is consistent with the published prediction, and it
is why the next phase is about statistical power rather than more search.

## 5. Cost, measured — and a correction

An earlier internal estimate of **$0.0381/rollout** was wrong by ~4×. The reasons are worth
stating, because they are the reasons the new number is trustworthy:

1. It was an **n=2 probe on the two easiest tasks**, with no variance estimate.
2. **The setup got heavier afterwards** — three additional validity checks were added to
   the stop policy. Real cost, incurred deliberately, never repriced.
3. **The agent began running full simulations nobody asked for** — a capability granted as
   a side effect of a validator change, latent five weeks, and once used it became the
   single largest cost driver in the campaign. Now blocked at the mount and in the prompt.
4. **The estimator itself was structurally wrong.** Pricing from token counts
   over-predicts by 2.25×; the provider does not bill the token accounting the transcript
   records.

**Standing rule adopted:** every experimental arm is bracketed with a billing-API read and
priced by the delta. It is the only method that has ever been right.

| configuration | $/rollout | turns | wall-clock |
|---|---|---|---|
| with self-directed simulation runs | $0.194 | 173 | 3186 s |
| **scope stated in the task prompt** | **$0.134** | 103 | 1888 s |
| block only, without stating scope | $0.213 | 138 | 1724 s |

The third row is a finding in its own right: **blocking a behaviour without explaining why
cost 59% more than explaining it without blocking**, because a refusal invites another
variation rather than ending the attempt.

## 6. The programme

| phase | question | rollouts | cost |
|---|---|---|---|
| **P0** | characterize the 46-task pool; select the study set on measured criteria | 80 | $11 |
| **P0.5** | seal the test split; pre-register endpoint, MDE, stopping rule | 0 | $0 |
| **P1** | does the evolved adapter beat the seed? | 72 | $10 |
| **P2** | does any gain survive compute-matching? | 72 | $10 |
| **P3** | which of four ingredients carries it? | 144 | $19 |
| **P4** | does evolving from scratch beat our handcrafted prior? | 72 | $10 |
| **P5** | does it transfer to a held-out physics family? | 24 | $3 |
| **P6** | does it transfer across models and harnesses? | 48 | $6 |
| | **core total** | **512** | **$70** |

**Design decisions, each derived rather than chosen** (detail in `RESEARCH_PROGRAM.md`):

- **12 tasks × 3 seeds = 36 cells per arm**, sized from measured per-task variance to give
  a minimum detectable effect of **0.04–0.06** — the scale this literature reports.
  Doubling to 60 cells improves that by 0.009 for 67% more money, so marginal budget buys
  *another arm*, not tighter intervals on one.
- **Splits are grouped by physics family, not by task.** The 46-task pool is really ~5
  families with heavy structural sharing — a random task-level split lets an adapter learn
  the Drucker-Prager family from one member and score on its siblings without generalizing
  at all. **This is the methodological choice that distinguishes our evaluation from every
  paper in the survey.**
- **The test split is sealed at the filesystem level, not by convention** — its
  ground-truth is not mounted during search. We learned this the hard way: a capability
  granted at the mount level went unnoticed for five weeks.
- **Honest limit, stated up front:** the project's headline quantity is the
  catastrophic-failure rate, and **we cannot afford to power it directly** — separating a
  6% failure rate from 2% needs 376 rollouts per arm. The primary endpoint is therefore the
  paired continuous score, with the failure rate reported descriptively. We would rather
  say this than publish an underpowered tail statistic.

## 7. Risks

1. **The result may be null.** Pre-registered, and publishable — the field's own strongest
   paper reports a null it treats as a finding.
2. **Wall-clock, not money, is the schedule risk.** ~46 h at 6-way; the machine is shared
   and has been observed at load 789 on 128 cores from other users.
3. **Provider volatility.** Five model free-periods ended during a single working session
   on 2026-08-26, one mid-run. Paid credit removes a dependency that proved unmanageable —
   and is part of why this request exists.
