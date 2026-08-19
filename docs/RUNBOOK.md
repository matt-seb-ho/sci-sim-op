# Runbook — getting to a first real result

The order below is not arbitrary. Each step either removes a way for the result
to be meaningless, or is cheap enough that doing it out of order wastes real
money. Steps 1–4 cost nothing and must all pass before step 5 spends anything.

Everything here is derived from the two dry runs
([01](EXPERIMENT_01_proposer_control.md), [02](EXPERIMENT_02_protocol_dryrun.md)),
which exist so these problems were found for $0 rather than mid-experiment.

---

## 1. Plan the budget against the held-out slice — *before* anything else

```bash
python3 scripts/evolve.py plan --held-out 10 --seeds 5 --anchor 8 --wanted 150
```

Parallel scaling spends `k` draws per cell, so a baseline can only be matched at
**multiples of `|held_out| × n_seeds`**. A search budget picked for any other
reason lands between the reachable points and *cannot be matched afterwards* —
by the time that is visible, the rollouts are spent. Experiment 02 hit exactly
this: 126 search rollouts against 4 held-out tasks needed k=11, costing 2.10× the
search, against a control at 0.19×.

For the expected shape — 10 held-out tasks, 5 final seeds, 8-task anchor, 2
search seeds — the reachable budgets are:

| search rollouts | k | candidates | ≈ USD | ≈ wall (4 workers) |
|---:|---:|---:|---:|---:|
| 50 | 1 | 3 | $3 | 5 h |
| 150 | 3 | 9 | $10 | 16 h |
| 250 | 5 | 15 | $17 | 26 h |
| **350** | **7** | **21** | **$23** | **37 h** |

**350 rollouts / 21 candidates is the ceiling**, because beyond k=7 the
sequential-refinement arm runs past the stop policy's retry cap and cannot be
constructed without changing the harness — which unfreezes the thing the claim
holds fixed.

**Recommended: 150 rollouts (k=3, ~9 candidates).** Small enough to rerun after a
mistake, large enough that a null result is informative rather than a
non-attempt.

---

## 2. Clear preflight

```bash
python3 scripts/evolve.py preflight --simulator geos \
    --ground-truth-dir /path/to/experiments_gt
```

It currently reports two blockers, both real:

**(a) The container drops the stop-policy environment.**
`docker_cmd.py` forwards a fixed `GEOS_HOOK_*` allowlist; `GEOS_EVOLVE_FEEDBACK_SHAPE`
and `GEOS_EVOLVE_CHECKS` do not survive it. Until they do, a search that varies
the stop policy varies a knob nothing reads — and it looks entirely normal in the
logs, because the candidates really are different and the scores really do
differ.

*The test that settles it:* run one task at `feedback_shape=minimal` and one at
`errors_plus_tables`, then diff the hook's own event log. Identical feedback text
means it is not wired. Do not skip this because the config "looks right"; that is
the exact failure mode.

**(b) The hygiene corpus needs the real ground-truth tree.** Without it the
content, numeric, structural and rare-token rules are inert and the gate degrades
to filename matching. See §4.

---

## 3. Verify the validator actually emits repair directives

The derived-constraint mechanism assumes the validator names the legal action
space, not just a verdict. Check it on one deliberately broken deck:

```bash
geosx -i broken.xml --validate-input 2>&1 | tee /tmp/validator.txt
python3 -c "
import sys; sys.path.insert(0,'src')
from harness_evolve.evidence.directives import parse_validator_output, summarize
print(summarize(parse_validator_output(open('/tmp/validator.txt').read())))"
```

Expect a non-zero `actionable_fraction`. If it reads 0%, the mechanism does not
apply to this validator build and should not be claimed — the ledger reports
that number precisely so the honest answer is available.

---

## 4. Recalibrate the hygiene gate against the real tree

The gate's content, numeric, structural and rare-token thresholds were tuned
against synthetic fixtures plus two real leaked artifacts. They have never seen
the real ground-truth decks.

```bash
python3 scripts/evolve.py audit --adapter-dir plugin \
    --ground-truth-dir /path/to/experiments_gt
```

Two things must both hold, and they pull in opposite directions:

- the two known-leaky artifacts still **block**;
- the hand-designed adapter — which is legitimate and must remain usable —
  produces **no errors**.

If the second fails, raise `rare_token_df_fraction` and `ngram_error` rather than
disabling a rule. A gate people route around is worse than no gate.

---

## 5. Baseline run, and only then the search

```bash
# baseline: identifies which tasks are in play, and seeds the slice construction
python3 scripts/evolve.py slices --tasks tasks.txt --held-out held_out.txt \
    --stats baseline_stats.json --anchor 8 --out slices.json
```

Freeze `slices.json` and **record the decision**. Changing the anchor mid-search
invalidates every comparison made before the change — which is how the
predecessor's per-round task slices made its rounds incomparable.

Then run the search at the budget from step 1.

---

## 6. Final evaluation — once

The held-out slice is served **exactly once, to one candidate**. The protocol
object enforces this and a second release raises; that is deliberate, since "we
only looked twice" is how a held-out set becomes a validation set.

Run the compute-matched suite and render the report. Read the **verdict section
first**, before the numbers — the criterion is fixed in advance precisely so it
cannot be adjusted after seeing them.

---

## A consequence of the seed count that is not obvious

The noise band is derived from the **sample** across-seed SD. At n=2 seeds that
is √2 ≈ 1.41× the population SD, so the band is ~41% wider than it would
otherwise be — more ties, fewer wins, a more conservative verdict.

That is the right direction (conservative where the evidence is thinnest) but it
is a consequence of an estimator choice rather than something anyone selected.
It means **the seed count moves the verdict through two channels**: directly, by
how much noise there is, and indirectly, by how wide the band estimated from it
turns out to be. Going from 2 to 3 search seeds narrows the band by ~18% on top
of the direct variance reduction.

Pinned in `tests/test_stats_verification.py` so it cannot drift silently.

## What a good outcome looks like

Not "the search won". These, in order:

1. **The verdict is `survives`, `mechanism_only`, or `fails` — and it is
   believed.** All three are publishable. `fails` on a compute-matched
   comparison is a real contribution given the published evidence that automatic
   harness evolution does not reliably beat test-time scaling.
2. **The tail statistics show the mechanism** — zero-rate reduction, rescues
   without matching losses — even where the mean comparison is inconclusive.
   Experiment 01 showed exactly this shape, and it is the expected one.
3. **The budget ledger is auditable** and every arm sits inside tolerance.
4. **The decision log shows calibrated predictions**: a proposer whose named
   beneficiaries actually move is evidence of judgement, not churn.

## The pre-registered kill criterion

Published evidence predicts a search in this regime **returns its seed**: a
well-designed fixed prompt beat every reflective optimizer at comparable training
size, and the variance-amplification effect of reflective optimization is
headroom-dependent — at high base accuracy you get the variance without the gain.
We are at a small task count with a hand-designed seed already near ceiling.

**If the search returns its seed under the no-regression floor, that is the
predicted outcome. Report it and stop.** Do not loosen the gate until something
passes. A gate tuned until it admits a winner is not a gate, and the resulting
number would be exactly the kind this project exists to stop producing.
