# GEOS self-evolution — initial numbers

**Run:** 2026-09-02, unattended · **Model:** `z-ai/glm-5.3-flash` ·
**Deliverable deadline:** 2026-09-02 16:00 UTC — **missed; this is the 17:40 UTC state.**

Worklog (every number traces to a timestamped entry there):
`/home/matt/projects/sci-sim-op/worklogs/2026-09-02_overnight.md`

---

## 1. The finding

**The search arm produced no evaluated candidate, so there is no evidence here either for
or against self-evolution helping on GEOS.** That is the honest headline and it is not the
pre-registered null — a null requires a search that could have accepted something and did
not. This one never got a candidate as far as an evaluator.

What the night *did* produce is a working, audited measurement apparatus and one real
result:

> **Five defects were found, each of which would have produced a plausible, publishable
> number that meant something other than its label.** Four of them were in the path
> between a rollout and a reported score. All are fixed, tested, and committed.

and, at no additional cost:

> **A near-paired contrast over 35 rollouts shows the harness change had no detectable
> effect on score: paired mean delta −0.0350, 95% CI [−0.1473, +0.0772], spanning zero;
> zero rate 0.056 → 0.059.** Meanwhile the newly-enabled `cross_section_refs` check
> demonstrably *fired*, blocked a turn, and got a defect repaired. **Mechanism without
> measurable outcome.**

---

## 2. What was run

| arm | status | rollouts |
|---|---|---|
| Unblock acceptance — both §5 blockers settled | **done**, 0 rollouts | 0 |
| `baseline` — noise floor on `glm-5.3-flash`, 6 tasks × 3 seeds | **done** | 18 |
| Slice re-cut on the σ-pruned pool | **done, $0.00** (all replayed) | 0 |
| `search --budget 2` | **ran; produced no evaluated candidate** | 0 new (7 replayed) |
| `baselines` — compute-matched | **NOT RUN** | 0 |
| ablation | **NOT RUN** | 0 |

**Why the search produced nothing** — both proposals failed, and the second is a defect:

```
proposed 2, screened out 0, hygiene-blocked 0, proposer failures 2
proposal 1 failed: no <prediction> block; every edit must be falsifiable
proposal 2 failed: z-ai/glm-5.3-flash returned no content
                   (finish_reason=length, 35617 chars of reasoning):
                   the token budget was spent thinking.
```

The proposer's `max_tokens` was 8000 — a figure measured against the same model under its
old slug in August. It now spends the whole allowance reasoning and returns no answer.
**Raised to 32000; the arm is one command to re-run.** Note the hygiene gate blocked
nothing (`hygiene-blocked 0`), so the August blocker is genuinely cleared — this is a
different failure.

### Exact commands

```bash
cd /home/matt/projects/sci-sim-op
export PATH="$HOME/.local/bin:$PATH" REPO3_PATH=/home/matt/projects/siga
export HARNESS_EVOLVE_MODEL=z-ai/glm-5.3-flash REPO3_CONTAINER_BACKEND=enroot
OUT=/home/matt/projects/sci-sim-op/.evolve/geos_search

uv run python scripts/search_geos.py --stage baseline --parallel 8 --seeds 1,2,3 \
  --timeout 2400 --task-list AdvancedExampleDruckerPrager,buckleyLeverettProblem,\
ExampleDPWellbore,ExampleIsothermalLeakyWell,ExampleMandel,TutorialSneddon --out $OUT
uv run python scripts/rescore_corpus.py --model z-ai/glm-5.3-flash --apply
uv run python scripts/prune_pool.py   --model z-ai/glm-5.3-flash --drop 2
uv run python scripts/search_geos.py --stage search --budget 2 --seeds 1,2 \
  --parallel 8 --timeout 2400 --screen-tasks 0 --out $OUT
uv run python scripts/report_geos.py  --out $OUT --model z-ai/glm-5.3-flash   # free
```

---

## 3. What it cost

| reading (UTC) | key `usage` | spent this campaign |
|---|---|---|
| 10:12 baseline of record | $1.2711 | — |
| 10:42 baseline launch | $1.2837 | $0.0127 |
| 12:20 baseline end | $2.2805 | $1.0094 |
| 12:28 search launch | $4.7682 | $3.4971 |
| 17:37 | $4.7758 | **$3.5047** |

Ceiling **$18.7289** (the owner raised the key cap mid-run and the polled guard picked it
up with no restart). Spend curve, one line per poll:
`/home/matt/projects/sci-sim-op/.evolve/provider_calls.jsonl`

> **Measured cost is ≈$0.194/rollout — 5× the $0.0381 in
> `docs/2026-08-26_BUDGET_PLAN.md` §2.** That figure came from a two-task cost probe;
> these tasks run to the 2400 s timeout with far more turns. **The programme estimate of
> $21 for 560 rollouts should be read as ≈$109.** Money was not the binding constraint
> tonight — wall-clock was — but the number in the funding document is wrong by 5×.

---

## 4. The numbers

### 4.1 Seed baseline, `z-ai/glm-5.3-flash`, 6 tasks × 3 seeds

```
n=17 scored (1 harness error excluded)
mean 0.5919    zero rate 0.059    min 0.0000    max 0.9799
  ExampleIsothermalLeakyWell    0.9477 +/- 0.0524   n=3
  AdvancedExampleDruckerPrager  0.9157 +/- 0.0786   n=3
  buckleyLeverettProblem        0.5855 +/- 0.5170   n=3
  ExampleDPWellbore             0.5017 +/- 0.3603   n=3
  ExampleMandel                 0.3355 +/- 0.0084   n=2
  TutorialSneddon               0.1798 +/- 0.1649   n=3
```

**Read the tail, not the mean.** The mean of 0.5919 is an average over tasks whose σ spans
two orders of magnitude and one of which fails outright a third of the time. The
informative quantities are: **zero rate 0.059**, **per-task minimum 0.0000**
(`buckleyLeverettProblem`), and the spread itself.

### 4.2 The harness change: a clean null, and a mechanism that fired

`stealth/ox-alpha` **is** `z-ai/glm-5.3-flash` — the vendor's own retirement notice says
so, and the August log had quoted it truncated. So the August corpus and tonight's are the
**same model, same 6 tasks, same 3 seeds, same 2400 s timeout**, differing in the harness:
2 checks → 5 checks, one cheatsheet line removed, pre-release → production channel.

```
task                             Aug26 (2 checks)    Sep02 (5 checks)     delta
AdvancedExampleDruckerPrager     0.9060 +/- 0.0815   0.9157 +/- 0.0786   +0.0097
ExampleDPWellbore                0.7121 +/- 0.3192   0.5017 +/- 0.3603   -0.2103
ExampleIsothermalLeakyWell       0.9746 +/- 0.0054   0.9477 +/- 0.0524   -0.0269
ExampleMandel                    0.2155 +/- 0.1870   0.3355 +/- 0.0084   +0.1200
TutorialSneddon                  0.0879 +/- 0.0105   0.1798 +/- 0.1649   +0.0919
buckleyLeverettProblem           0.7801 +/- 0.0035   0.5855 +/- 0.5170   -0.1946

paired mean delta  -0.0350   95% CI [-0.1473, +0.0772]   n=6 tasks   CI SPANS ZERO
pooled mean        0.6127 -> 0.5919        zero rate     0.056 -> 0.059
```

And yet the mechanism is real. On the first rollout of the campaign,
`cross_section_refs` blocked the agent's turn:

```json
{"decision":"block","reason_category":"vendored_check","retries_so_far":1,
 "checks_vendored_findings":[{"source":"cross_section_refs","severity":"error",
   "message":"materialList names 'dummy', which is not a <Constitutive> child.
              Defined: ['DruckerPrager','ExtendedDruckerPrager','ModifiedCamClay',
              'ViscoDruckerPrager','ViscoExtendedDruckerPrager','ViscoModifiedCamClay']"}]}
```
33 seconds later: `{"decision":"allow","reason_category":"xml_clean"}`. The agent had left
a placeholder `materialList="{ dummy }"`; the check named it and the six legal
alternatives; the agent repaired it. **`geosx --validate-input` ran first in the same list
and passed the deck** — `materialList` resolves at solve time, not load time, a gap the
hook's own feedback text had warned about in writing before anyone saw it happen.

**So: the instrument works and the score does not move.** That is a specific, reportable
result, and it corrects the August log in both directions — that session first argued
vendoring mattered because `required_sections` would catch under-generation, then falsified
its own claim and generalised to "vendoring would fix nothing measured". The falsification
was right about `required_sections`; the generalisation was not. `cross_section_refs` was
in `BUILTIN_CHECKS` the whole time and neither analysis looked at it.

### 4.3 Minimum detectable effect — what this pool *can* resolve

| pool | one arm | arm vs arm |
|---|---|---|
| all 6 tasks | 0.1241 | **0.1756** |
| drop 1 noisiest | 0.0922 | 0.1304 |
| drop 2 noisiest (the pool the search used) | 0.0538 | **0.0761** |

At 3 seeds, **nothing smaller than ≈0.08 is detectable even on the pruned pool.** Published
harness-evolution effects in this regime are +1.2 and +0.0 points. **This design cannot
resolve the effect it is looking for**, and that is a fact about the measurement, not a
result.

---

## 5. What is NOT believable

1. **Anything about whether the search helps.** No candidate was evaluated. The search
   arm's `best` is its own seed because it is the only thing in the archive.
2. **No compute-matched baseline was run.** Even had the search produced a winner, it
   could not be claimed. An unmatched win is not a win.
3. **§4.2 is observational, not a designed ablation.** Three things changed at once
   (check set, one cheatsheet line, serving channel), n=6 paired tasks, and the CI hides
   anything below ≈±0.12. It is assembled after the fact from two runs that were not arms
   of one experiment.
4. **σ from n=3 is not a dispersion statistic here.** `buckleyLeverettProblem` moved from
   σ=0.0035 to σ=0.5170 **with the model held constant**. Its three values are 0.9790,
   0.7774, 0.0000 — the σ is carried entirely by one discrete failure (deck written outside
   the ground-truth-relative path), not by continuous spread. Every MDE in §4.3 inherits
   this and should be read as indicative.
5. **`ExampleMandel` is n=2**, not 3 — one rollout was lost to an OpenRouter
   `Upstream idle timeout exceeded`. Its σ=0.0084 is two points and means little.
6. **`empty_workspace` is a misleading status.** In one case it meant "the agent wrote a
   complete deck to the path its own PRIMER specifies, which is not where the scorer
   looks." Left unrenamed so as not to change the dependent variable mid-campaign.
7. **The August numbers are not a clean control.** They were recorded before the F7 scoring
   fix and on a pre-release serving channel.

---

## 6. Verdict

**`mechanism_only`.** The apparatus is now measuring what it claims to measure, in five
specific respects where it demonstrably was not this morning. One instrument
(`cross_section_refs`) is verified working end-to-end inside the container. The score did
not move. **No claim is made about self-evolution on GEOS, because the experiment that
would support one did not complete.**

The pre-registered null (`docs/PROJECT_PRIMER.md` §7) is **not** claimed and must not be
cited from this run — that would repeat the exact error the August session caught itself
making in its §16.2: confirming a prediction with a result that contains no information
about the thing predicted.

### The five defects, since they are the substance of the night

| | defect | what it would have produced |
|---|---|---|
| **F1** | Replay key omitted the inference model; 51 rollouts from a retired slug sat in the corpus | the seed baseline every arm is measured against, replayed from another configuration at $0.00, printing a normal-looking resume line |
| **F2** | Proposer backend defaulted to the retired slug | every proposal 404s → search returns its seed → the pre-registered null, for the wrong reason |
| **F3** | The F2 fix was committed **without having applied** | as F2. Found by reading the file for an unrelated reason |
| **F7** | Timed-out rollouts scored before the container workspace finished copying | fabricated `0.0000`s. One re-scored to **0.8250** from the same directory. Inflates the *zero rate* — the campaign's headline tail quantity — and steered `build_slices` to nominate the affected tasks as anchors |
| **F8** | `Search._evaluate` averaged `harness_error` zeros into candidate scores | an OpenRouter timeout on the seed halved its `ExampleMandel` score, so every child would beat a weakened seed — **manufacturing a positive result** in a campaign pre-registered to expect a null |

Four of the five were found by running something and reading what came out. **The one I got
wrong (F3) was the one I checked by reading.**

---

## 7. What to do next, in order

1. **Re-run the search** with `max_tokens=32000` (already committed). ~12 rollouts, ~$2.3,
   ~80 min. This is the missing deliverable.
2. **Then the compute-matched baselines.** Never ship 1 without 2.
3. **Raise seeds or shrink the claim.** At 3 seeds the pool cannot resolve anything below
   ≈0.08; the published effects are far smaller. Either budget for ~5+ seeds on a quiet
   pool, or state the MDE beside every reported delta.
4. **Fix the `empty_workspace`/path-layout contract** — decide whether the scorer follows
   the PRIMER or the PRIMER follows the scorer. It cost a hard zero tonight.
5. **Correct `docs/2026-08-26_BUDGET_PLAN.md`** to $0.194/rollout.

---

## 8. Artifacts — absolute paths

| what | where |
|---|---|
| this report | `/home/matt/projects/sci-sim-op/.evolve/geos_search/REPORT.md` |
| worklog | `/home/matt/projects/sci-sim-op/worklogs/2026-09-02_overnight.md` |
| rollout corpus (every number recomputes from this) | `/home/matt/projects/sci-sim-op/.evolve/geos_search/rollouts.jsonl` |
| corpus before model tagging | `…/rollouts.jsonl.pre-model-tag.bak` |
| corpus before F7 re-scoring | `…/rollouts.jsonl.pre-rescore.bak` |
| search result | `/home/matt/projects/sci-sim-op/.evolve/geos_search/search_result.json` |
| slice plan / pruned pool | `…/slices.json`, `…/pool.json` |
| decision log | `/home/matt/projects/sci-sim-op/.evolve/geos_search/decisions.jsonl` |
| spend curve | `/home/matt/projects/sci-sim-op/.evolve/provider_calls.jsonl` |
| R1 receipt (hook SHA-pinned) + arms | `/home/matt/projects/sci-sim-op/.evolve/r1_verification/` |
| public-vocabulary allowlist used | `/home/matt/projects/sci-sim-op/.evolve/geos_public_vocabulary.json` |
| raw rollout workspaces | `/home/matt/projects/sci-sim-op/.evolve/geos_search/rollouts/` |
| the check-firing event log (F5) | `…/rollouts/claude_code_repo3_plugin_xmllint_all/evolve-cand_d1c0f1f0f516-s2-AdvancedExampleDruckerPrager/` |
| console logs | `/tmp/claude-1009/baseline.log`, `/tmp/claude-1009/search.log` |
| autonomous-run state | `/home/matt/projects/sci-sim-op/.autoresearch/` |
