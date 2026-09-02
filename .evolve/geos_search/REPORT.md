# GEOS self-evolution — initial numbers

**Run:** 2026-09-02, unattended · **Model:** `z-ai/glm-5.3-flash` ·
**Deadline:** 2026-09-02 16:00 UTC (grant project sync)
**Status: IN PROGRESS — baseline arm running.** This file is refreshed after every stage;
whatever it says now is shippable now.

Worklog (how every number here was arrived at):
`/home/matt/projects/sci-sim-op/worklogs/2026-09-02_overnight.md`

---

## 1. The finding so far

**Two defects in the measurement apparatus would each have produced a plausible,
publishable-looking number that meant something other than its label. Both were found
before any rollout was spent, and both are fixed.** No experimental arm has landed yet, so
there is as yet **no evidence either for or against the search helping**.

That is the honest headline at this timestamp, and it is deliberately not dressed up. It is
also, in itself, the campaign's own thesis holding: *the dangerous bugs here are the ones
that produce a plausible number, not the ones that crash.*

| # | defect | what it would have produced |
|---|---|---|
| **F1** | The rollout corpus keyed replays on `(candidate, task, seed)` — **not the inference model** — and held 51 rollouts produced by `stealth/ox-alpha`, whose free window closed on 2026-08-26. | `--stage baseline` would have replayed 18 ox-alpha rollouts, reported them as `glm-5.3-flash` results at **$0.00**, and handed the search a **seed baseline measured on a different model**. The resume line it prints is a normal feature of the harness. |
| **F2** | The proposer's backend defaulted to `stealth/ox-alpha` — dead. | Every proposal call 404s; the search proposes nothing, evaluates nothing, and **returns its seed** — i.e. reports the pre-registered null *for entirely the wrong reason*. |

F1 would have fabricated the **baseline**; F2 would have fabricated the **null**. Together
they would have produced a complete, internally consistent, entirely meaningless result.

**Both fixed, and the fix is visible in the running system** rather than asserted:

```
corpus: 0 row(s) match model 'z-ai/glm-5.3-flash' and are replayable; 51 row(s) were
        recorded under stealth/ox-alpha and will NOT be replayed -- a rollout is a
        property of (candidate, task, seed, model), not of the first three
```

---

## 2. What was run

| arm | status | rollouts | tasks × seeds |
|---|---|---|---|
| Unblock acceptance (hygiene + vendoring) | **done**, 0 rollouts | 0 | — |
| `baseline` — noise floor on `glm-5.3-flash` | **running** (launched 10:42 UTC) | 18 | 6 × 3 |
| `search --budget N` | not started | ~60 | sized from the baseline's measured wall-clock |
| `baselines` — compute-matched | not started | ~60 | k derived from the search ledger |
| one ablation | **planned as not fitting** | ~60 | only if the arms above come in under wall-clock |

### Exact commands

```bash
cd /home/matt/projects/sci-sim-op
export PATH="$HOME/.local/bin:$PATH"
export REPO3_PATH=/home/matt/projects/siga
export HARNESS_EVOLVE_MODEL=z-ai/glm-5.3-flash
export REPO3_CONTAINER_BACKEND=enroot
OUT=/home/matt/projects/sci-sim-op/.evolve/geos_search

uv run python scripts/search_geos.py --stage baseline --parallel 8 --seeds 1,2,3 \
  --timeout 2400 --task-list AdvancedExampleDruckerPrager,buckleyLeverettProblem,\
ExampleDPWellbore,ExampleIsothermalLeakyWell,ExampleMandel,TutorialSneddon --out $OUT

uv run python scripts/report_geos.py --out $OUT --model z-ai/glm-5.3-flash   # free, any time
```

---

## 3. What it cost

| reading (UTC) | key `usage` | key `limit` | ceiling | spent this campaign |
|---|---|---|---|---|
| 10:12 (baseline reading) | $1.271071 | 10 | $8.729 | $0.000 |
| 10:36 (owner raised the cap) | $1.283724 | **20** | **$18.729** | $0.0127 |
| 10:42 (baseline launch) | $1.283724 | 20 | $18.729 | $0.0127 |

Full spend curve, one line per poll:
`/home/matt/projects/sci-sim-op/.evolve/provider_calls.jsonl`

**Money is not the binding constraint; wall-clock is.** $18.73 of headroom buys ~491
rollouts at the measured $0.0381/rollout, but the 16:00 UTC deadline allows only
**~164**.

---

## 4. The numbers

*Nothing to report yet — the baseline arm has not landed.* This section will carry per-task
means with dispersion, the zero rate, and the per-task minimum. It will not carry a bare
mean: per-task σ on the previous model spanned **0.0035 to 0.32**, and a mean over that
without a dispersion statistic is not a result.

### 4.1 Two ablation results already in hand, at zero rollout cost

Carried forward from 2026-08-26 (`stealth/ox-alpha`, n=18), **with the corrections the
author of that log later applied to their own claims**:

- **The stop policy fires and has nothing to say — on rollouts where the agent ends its
  turn.** 5/5 `allow`, 0 retries, across a 0.09–0.98 score range. That claim stands.
- **CORRECTED — it does not follow that the stop policy cannot affect the score.** On the
  one rollout that scored 0.0000, the stop policy was the *right* instrument and was
  structurally prevented from running: the rollout timed out, the agent never ended its
  turn, and the Stop hook only fires at turn end. That is a delivery failure, not
  inertness.
- **CORRECTED — the zero rate is not 0.000, it is 0.056.** One rollout in eighteen
  terminated catastrophically (`--` inside an XML comment, which XML forbids). The
  regression gate's central clause therefore *does* have something to bind on. The
  earlier "0.000, so the gate cannot bind" inference is withdrawn.

The corrected version matters for tonight: **the regression gate is live, not inert**, and
the timeout is a mechanism rather than a nuisance — which is why every arm tonight runs at
a fixed, generous 2400 s.

---

## 5. What is NOT believable

The most important section, and it is populated before the results rather than after.

1. **Nothing about the search, yet.** No search arm has run. Any statement about whether
   self-evolution helps on GEOS is, at this timestamp, unsupported.
2. **The 2026-08-26 numbers are `stealth/ox-alpha`'s and cannot be pooled with anything
   measured tonight.** That model no longer exists; the 18 rollouts are a frozen dataset.
   Per-task σ is a property of *model × task*, so even the task-pruning advice in
   `docs/2026-08-26_BUDGET_PLAN.md` §3.1 is computed from a model we are not running.
   Tonight's baseline re-measures it.
3. **`ExampleDPWellbore` is not measurable at this n.** σ = 0.32 on the previous model;
   at n=3 the 95% interval on its mean is roughly ±0.36. It would need ~41 seeds to detect
   a 0.2 effect. It is reported separately and excluded from any headline mean.
4. **`ExampleMandel` is timeout-censored.** It hit the wall on two of three seeds
   previously. Its rate of hitting the timeout is reported alongside its score.
5. **The vendored checks are expected to fire at near zero, and that is pre-registered.**
   `required_sections` is a *section-presence* check; the failure actually measured
   (`TutorialSneddon`, 38 elements against a 252-element ground truth) has **all** required
   and optional sections present. `constraints` is a content check and the seed ships an
   empty constraint set. Vendoring makes them *runnable*; it does not make them able to see
   under-generation. **No check in the registry measures completeness**, and writing one is
   not attempted here because every cheap way to write it leaks ground truth through the
   feedback channel.
6. **Any arm that does not finish is reported as not-run, never as a number.** A partial
   arm is uninterpretable, not weaker.

---

## 6. Verdict

**Pending.** The null is pre-registered (`docs/PROJECT_PRIMER.md` §7) and is a first-class
outcome: published evidence (arXiv:2607.12227) predicts a search in this regime returns its
seed, loses to plain parallel sampling at matched compute, and encodes task-specific
shortcuts rather than better harness design. If that is what tonight measures, that is the
result, and it will be reported without softening.

What can already be said: **the apparatus is now measuring what it claims to measure**, in
two specific respects where it demonstrably was not this morning.

---

## 7. Artifacts — absolute paths

| what | where |
|---|---|
| this report | `/home/matt/projects/sci-sim-op/.evolve/geos_search/REPORT.md` |
| worklog | `/home/matt/projects/sci-sim-op/worklogs/2026-09-02_overnight.md` |
| rollout corpus (every number recomputes from this) | `/home/matt/projects/sci-sim-op/.evolve/geos_search/rollouts.jsonl` |
| pre-migration corpus backup | `/home/matt/projects/sci-sim-op/.evolve/geos_search/rollouts.jsonl.pre-model-tag.bak` |
| decision log | `/home/matt/projects/sci-sim-op/.evolve/geos_search/decisions.jsonl` |
| spend curve, one line per poll | `/home/matt/projects/sci-sim-op/.evolve/provider_calls.jsonl` |
| R1 receipt (hook SHA-pinned) | `/home/matt/projects/sci-sim-op/.evolve/r1_verification/receipt.json` |
| R1 arms + raw hook events | `/home/matt/projects/sci-sim-op/.evolve/r1_verification/arms.json` |
| seed adapter | `/home/matt/projects/sci-sim-op/.evolve/seed/` |
| public-vocabulary allowlist actually used | `/home/matt/projects/sci-sim-op/.evolve/geos_public_vocabulary.json` |
| raw rollout workspaces | `/home/matt/projects/sci-sim-op/.evolve/geos_search/rollouts/` |
| baseline console log | `/tmp/claude-1009/baseline.log` |
| autonomous-run state and event logs | `/home/matt/projects/sci-sim-op/.autoresearch/` |
