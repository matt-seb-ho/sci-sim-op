# Experiment 02 — dry-running the evaluation protocol

**Date:** 2026-08-19 · **Cost:** $0 · **Script:**
`scripts/experiment_protocol_dryrun.py` · **Output:**
[`protocol_dryrun_report.md`](protocol_dryrun_report.md)

The protocol is the part of this project that decides whether a result gets
believed. A protocol that has never been executed is a plan. So: run the whole
thing — search, compute-matched baselines, slice discipline, paired statistics,
tail statistics, budget ledger, verdict — against a synthetic world whose answer
we already know, before any real budget is attached.

## The headline

**The protocol returned `fails` on a run whose naive reading is a clear win.**

What a normal write-up would have reported:

> mean paired delta **+0.1251** against the control, **3 wins / 0 losses / 1
> tie**, and the evolved adapter beat best-of-k under both selectors.

What the protocol said, and why:

```
Verdict: `fails`.

(1) control: 3W / 0L / 1T, mean delta +0.1251                  -> passes
(1) control: tasks newly below the catastrophic threshold:
    ['task_12']                                                -> FAILS
(3) baselines: no budget-matched task-level baseline was
    available -- the central question is untested
(4) support: no CI (n=4 tasks, below the floor of 6);
    p = 0.2500, and the smallest p this design can produce
    is 0.250 > alpha 0.05                                      -> not established
(4b) mechanism: rescued 1 ['task_11'], lost 1 ['task_12'];
     zero-rate change +0.083                                   -> not visible

Arms whose budget was not matched: ['best_of_k_oracle',
'best_of_k_validator']. Their comparisons are reported but carry no
weight in this verdict.
```

Every one of those is right. The mean gain came with a task pushed into
catastrophic failure; the design could not have reached significance at any
outcome; the reliability mechanism the whole claim rests on moved the *wrong
way* (zero rate up, one rescue against one loss); and the baselines that would
have settled it were not actually budget-matched.

This is precisely the write-up the predecessor system produced, and precisely the
one this machinery exists to refuse.

## A planning constraint we did not know about

Budget matching failed for a structural reason worth stating in advance.

The search spent **126 rollouts** on a 6-task anchor. Matching that against a
**4-task** held-out slice at 3 seeds requires `k = ceil(126/12) = 11` draws per
cell — which costs **264 rollouts, 2.10x the search**. The control, meanwhile,
spends 24, or **0.19x**. Neither is inside the 10% tolerance, so neither can
carry the verdict.

**A held-out slice much smaller than the search slice cannot host a
budget-matched parallel baseline.** The arms are matchable only when

```
search_rollouts  ≈  |held_out| × n_seeds × k       for a small integer k
```

Concretely, for the real experiment: with 10 held-out tasks at 5 seeds, a search
spending ~150 rollouts gives k=3 and lands close to matched. A search spending
~500 would need k=10 and overshoot by a factor. **The search budget and the
held-out slice have to be planned together**, which is not obvious and is exactly
the kind of thing that gets discovered too late.

## A second arm that could not be constructed

Sequential refinement is expressed through the harness's own stop policy —
initial attempt plus validator-fed retries — because that *is* this system's
refinement mechanism. At k=11 that exceeds the policy's retry cap:

> cannot spend 11 refinement passes through the stop policy (retries out of
> range [0,6]); the sequential baseline cannot be budget-matched at this k
> without changing the harness, which would unfreeze it

The arm is reported as **missing, with the reason**, rather than dropped. "We
could not construct a comparable sequential baseline at this budget" is a finding
about the comparison, not a detail of it.

## What else the run demonstrated

- **Slice discipline held and is auditable.** The report ends with a timestamped
  access trail: anchor for selection, probe for evidence, held-out released once
  to one named candidate. A second release raises.
- **Small-n guard rails fired.** The bootstrap refused an interval at n=4 rather
  than producing a confident-looking one; the permutation test reported its
  *minimum achievable* p so that p=0.25 could not be misread as weak evidence of
  no effect.
- **Both best-of-k selectors were reported.** The oracle selector is an
  unrealizable upper bound; the validator selector is what a real system could
  do. Reporting only the first would flatter the baseline, only the second would
  flatter us.
- **Every arm is labelled by model x harness configuration**, not by a system
  name.

## Caveats

Synthetic world, planted gradient, random-edit proposer. This validates the
*protocol*, not any claim about a simulator.

## What to do with it

1. **Plan the search budget against the held-out slice size.** See the relation
   above. This is now a precondition, not an afterthought.
2. **Re-run this dry run whenever the criterion changes.** A criterion that
   cannot fail is not a criterion, and this is the cheapest way to check that it
   still can.
3. **Expect `fails` or `mechanism_only` from the real experiment.** Published
   evidence predicts a search in this regime returns its seed; the criterion is
   built so that outcome is reportable rather than embarrassing.
