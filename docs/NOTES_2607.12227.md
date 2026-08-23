# Notes — *Rethinking the Evaluation of Harness Evolution for Agents* (arXiv:2607.12227)

Read 2026-08-23. This is the most serious published threat to the premise of
this project, and it should be treated as a specification for what our result
has to survive rather than as an objection to be argued around.

## What it actually found

Terminal-Bench 2.1, unified budget **K=5**, harness evolution instantiated as
AHE with the explore agent disabled, sampling m=1 rollout per task so the
rollout budget matches.

**Without unit tests** (self-judgment selection), pass@1, averaged over Claude
Opus 4.6 / GPT-5.4 / GPT-5.4-mini:

| method | average |
|---|---:|
| Direct sampling | 68.2 |
| **Parallel sampling** | **72.3** |
| Sequential refinement | 69.3 |
| **Harness evolution** | **67.4** |
| Harness scaling | 71.8 |

**Harness evolution scored below direct sampling.** Not below the best baseline —
below doing nothing at all with the extra budget.

**With unit tests** (oracle feedback), pass@1 / pass@5 average: parallel
86.0/86.0, sequential 84.3/**91.8**, harness evolution 75.8/86.2.

**Held-out** (45 train / 10 val / 34 test): evolution gained **+0.6 average** —
+1.2 on Opus 4.6, **+0.0** on GPT-5.4. In their words, *"the evolved harness
yields only marginal gains over the initial harness on the test set."*

## Why this is not fatal to us, stated carefully

The paper prescribes its own scope condition, and it is the most important
sentence in it for our purposes. Future work should study harness evolution

> *"on benchmarks that satisfy two conditions: (1) the tasks are difficult
> enough that current agents leave substantial headroom for improvement, and
> (2) performance depends heavily on the harness."*

And it says plainly why Terminal-Bench may not be such a benchmark:

> *"Terminal-Bench may simply not be very sensitive to harness design: a minimal
> setup consisting of a shell tool and a basic prompt already suffices for most
> solvable tasks."*

So the result is scoped by its own authors to benchmarks where the harness does
not matter much. The question is whether ours is different, and that is an
empirical question we happen to have data on.

### Condition (2) — harness sensitivity — we satisfy, with margin

Direct measurements from the prior work on this exact task family:

- **OpenFOAM:** the termination gate alone is worth **+0.168** mean over 30
  tasks, and every adapter cell holds full required-file coverage where two
  purpose-built native agents leave **8–12 tasks incomplete**.
- **LAMMPS:** procedural memory **+2.13**, retrieval **+1.55**.
- **GEOS:** across-run σ falls from **0.081 to 0.002–0.005** — roughly an order
  of magnitude — driven entirely by preventing zero-score terminations.
- **MOOSEnger** (arXiv:2608.15881), an independent system on a different
  multiphysics framework: **90% vs 5%** for the bare model.

A shell tool and a basic prompt emphatically does *not* suffice to author a
valid simulator input deck. The agent lacks the simulator's executable contract,
and supplying that contract is what the harness does. This is close to a
best case for condition (2).

### Condition (1) — headroom — we currently **fail**, and this is the actionable finding

Our in-distribution split sits at **0.86–0.92**. That is exactly the saturation
the paper blames for its own null result — *"the small set of remaining failures
may stem from limitations in the underlying model rather than deficiencies in
the harness."*

We already knew not to optimize against that split. What this paper adds is that
**reporting on it at all is a design error**, not merely an efficiency one. Two
consequences, both of which change what we do:

1. **The held-out split (0.72–0.79) is where the evaluation belongs**, and even
   there the effect is concentrated in a tail of two tasks. That is thin.
2. **We should manufacture headroom deliberately.** The relaxed-brief direction —
   handing the agent less-specified tasks so more of the scientific
   decision-making is its responsibility — creates headroom by construction, and
   the prior work already measured the drop (X+M: 0.921 easy → 0.829 medium →
   0.835 hard). That is a harder benchmark with room to move, and it is
   independently something we want for other reasons.

**Recorded as a requirement: no headline claim on the saturated split.**

## The two structural arguments

These are ours, not the paper's, and both need stating with their limits.

### A. Our test-time-scaling baseline is genuinely weaker than theirs, for a real reason

Their strongest baselines depend on **an oracle selector**. With unit tests
available, parallel sampling reaches 86.0 because you can cheaply tell which of
k attempts is correct. Take the oracle away and parallel sampling drops to 72.3.

**In deck authoring there is no cheap selector.** Deciding which of k generated
decks is best is the original problem restated — scoring requires the ground
truth we are trying to produce. The best available selector is the simulator's
own validator, which is *partial*: it separates loads-or-not from
does-not-load, and says nothing about whether a deck that loads is the right
deck.

This is not an excuse, it is a structural property of the domain, and it cuts
both ways: it weakens TTS *and* it is the reason harness improvements have
somewhere to be useful. Our `evaluation/baselines.py` already reports best-of-k
under **both** an oracle selector (an unrealizable upper bound) and a validator
selector (what a real system could do), and the gap between them is itself a
reportable quantity. We should report it prominently — it measures exactly how
much of TTS's advantage in their setting is unavailable in ours.

### B. Zero-marginal-cost improvement cannot lose a compute-matched comparison

The matched-budget critique bites because harness evolution *spends rollouts to
search*. A mechanism that spends **no additional rollouts** is not subject to it.

Our derived-constraint mechanism (`evidence/directives.py`) is one. The
simulator's validator, on rejecting a deck, prints the full table of valid
attributes or the legal tag list — it names the correct action space at the point
of failure. That output arrives as a by-product of **every rollout already
spent**, including the baseline rollouts you must run regardless. Deriving a
negative constraint from it costs one parse and one aggregation, both CPU-only.

So at any matched rollout budget, this mechanism is strictly *additive* to
whatever the baseline does with those rollouts. There is no budget at which the
comparison can be run that excludes it.

**Where this argument is weak, stated plainly.** It only establishes that the
mechanism is *free*, not that it *works* — whether derived constraints improve
anything is an open empirical question, and the ledger reports
`actionable_fraction` precisely so a null is visible rather than hidden. And it
applies only to mechanisms of this shape; the rest of the search is not immune
and must face the matched comparison on its own terms.

### C. Amortization completes the critique rather than dodging it

TTS is a **recurring** per-task inference cost — best-of-k costs k× on every task
forever. A harness artifact is a **one-time** cost, free at inference thereafter.
Charging the one-time cost to a single benchmark run is the right conservative
check and the wrong economics for a deployed system.

The honest completion is the **crossover point**: after how many task-solutions
does the evolved harness beat TTS in total compute? That is computable and
statable.

**This argument is only available if the evolved harness beats the seed at k=1.**
If it does not, there is nothing to amortize and the crossover is a category
error. The implementation gates on exactly that, and the report states the
matched-budget verdict *first*. Amortization is reported alongside a verdict,
never instead of one.

## What this changes about what we do

| | |
|---|---|
| **Kill the saturated split** | No headline claim on in-distribution scores clustering at 0.86–0.92. It is the same saturation the paper blames for its own null. |
| **Report the selector gap** | Oracle-best vs validator-best on our TTS baselines measures how much of TTS's advantage is unavailable here. Free to compute; already implemented. |
| **Foreground zero-marginal-cost mechanisms** | They are the only class immune to the matched-budget critique, and we have one. |
| **Report amortization, never in place of the verdict** | Gated on beating the seed at k=1. |
| **Manufacture headroom** | Move toward relaxed briefs, where the measured drop to 0.83 leaves room a harness can address. |
| **Expect to lose, and be able to say so** | Their harness-evolution arm scored *below direct sampling*. Our pre-registered kill criterion already says: if the search returns its seed, report it and stop. This paper is the reason that criterion exists. |

## The uncomfortable summary

If our result comes out looking like theirs, the correct conclusion is not that
our setting was different — it is that automatic harness evolution does not work
at this budget, and that the hand-designed adapter (which demonstrably *does*
work: σ 0.081 → 0.002) was the contribution all along. That is a publishable and
useful finding, and the evaluation machinery is built to reach it rather than
avoid it.

The genuinely interesting claim we might get instead is narrower than "harness
evolution works": it is that **the subset of harness improvement which costs no
search — deriving the interface contract from the checker's own error messages —
is worth having, and is invisible to the compute-matched framing because it
spends nothing.**
