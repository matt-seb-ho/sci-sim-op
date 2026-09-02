# KICKOFF — self-evolution methods on GEOS, unattended overnight run

**Date:** 2026-09-02 · **Deadline:** initial numbers for the grant project sync tomorrow.
**Mode:** unattended, zero interaction. Invoke the **`deli-autoresearch`** skill and run
under its protocol for the whole session.

---

## 0. Read these first, in this order

1. `docs/PROJECT_PRIMER.md` — **new, and the north star.** Goals, constraints, and the
   strategy. §6 item 3 is the work you are doing; §7 is what keeps it honest.
2. `docs/2026-08-26_followup-goals.md` — the same programme in operational detail.
3. `worklogs/2026-08-26_overnight.md` §13 (exact commands), §18 (closing summary),
   §§16–17 and §§21–23 (the two open blockers, and a correction the author made to their
   own top recommendation — read it before repeating it).
4. `docs/2026-08-26_BUDGET_PLAN.md` — measured per-rollout costs, rollout counts, and the
   minimum-detectable-effect analysis that says which tasks to drop.
5. `docs/2026-08-26_KICKOFF_free-window-campaign.md` — the previous brief. **Its budget
   policy is superseded by §2 below.** Everything else in it still holds.

## 1. The job

Produce **initial, honest numbers** on whether the modernized self-evolution loop does
anything on GEOS, with compute-matched baselines, for tomorrow's sync.

The deliverable is a short report a non-author can read, plus the corpus it was computed
from. **It is not a leaderboard number.** Per `docs/PROJECT_PRIMER.md` §7, a clean null is
a first-class result and is pre-registered. Report what happened.

## 2. Budget — this SUPERSEDES the free-models-only policy

The free window closed (`stealth/ox-alpha` ended mid-session on 2026-08-26). We are now
paying, deliberately.

- **Model:** `z-ai/glm-5.3-flash` — measured $0.0381/rollout, 12.6 min, scores
  indistinguishable from `gpt-5.6-luna` at a seventh the price. Set it with
  `export HARNESS_EVOLVE_MODEL=z-ai/glm-5.3-flash` (`scripts/_geos.py:MODEL` still
  defaults to the now-dead `z-ai/glm-5.2:free`).
- **Authorized spend: $20 on OpenRouter.**
- **The account can afford it; the API key cannot — yet.** Two different numbers, and an
  earlier draft of this brief conflated them. Measured 2026-09-02 10:21:

  | scope | endpoint | reading |
  |---|---|---|
  | **account balance** | `/api/v1/credits` | `total_credits 210`, `total_usage 168.323` → **$41.68 available** |
  | **this API key** | `/api/v1/key` | `limit 10`, `usage 1.271071093`, **`limit_remaining 8.729`** |

  The `$10` is a **per-key spending cap**, not the balance. The full $20 is affordable to
  the account; only the key cap is in the way, and it is raised from the OpenRouter
  dashboard (this key is not a provisioning key, so it cannot raise itself).
- **Poll the cap; do not hardcode it.** Before each rollout batch read `/api/v1/key` and
  recompute the ceiling as `min(20.00, limit_remaining)` of *additional* spend, measured
  against the `usage` baseline of **$1.271071093**. If the owner raises the key limit
  while you are running, `limit_remaining` jumps and you should simply keep going, up to
  the full $20 — no restart, no confirmation, log the change at `level=decision`.
- **Stop rule.** Halt spending when additional spend since baseline reaches the current
  ceiling, or when `limit_remaining` falls below the cost of one more batch. Then write up
  what you have and escalate (`PushNotification`). Do **not** switch to a free model
  mid-experiment — that silently changes the independent variable.
- **Plan pessimistic, spend into optimistic.** Sequence so the first ~$8.50 buys the §4
  priority items in order (~220 rollouts). If the cap is raised, §4 item 5 — the ablations,
  which are the programme's real deliverable — comes into range. Take them in §4's order.

**Enforcement — do this before spending anything.** The existing `CostLedger` hard-stops
on *non-zero* cost, which was the free-window rule and will abort instantly on a paid
model. It also only sees *proposer* calls; **rollout cost is spent by the agent inside the
container and is invisible to it.** So:

1. Change the policy from "cost must be zero" to "cumulative cost must stay under a cap".
2. Enforce it against the provider, not just local accounting: poll
   `https://openrouter.ai/api/v1/key` (send a `User-Agent`) and read both `data.usage` and
   `data.limit_remaining`. Baseline `usage` is **$1.271071093**; hard-stop when
   `usage - 1.271071093 >= min(20.00, limit_remaining)`. Check `/api/v1/credits` once at
   start to confirm the account balance is not the binding limit (it was $41.68 at 10:21).
3. Poll it between rollout batches, and log every reading to `.evolve/provider_calls.jsonl`.
4. Keep per-generation attribution in the loop. `docs/2026-08-26_BUDGET_PLAN.md` §2.1
   records a rollout nominally on one model that was **85% billed to Claude Sonnet 5** via
   an unblocked subagent — a validity problem before it is a cost problem. Verify
   `Task`/`Agent`/`TaskCreate` are still in the disallowed-tool list before the first run.

## 3. Environment — one fact that breaks everything if missed

**The former `repo3` checkout is now `/home/matt/projects/siga`** (2026-09-02 home reorg).
`find_repo3()` does not search that path, so preflight reports three spurious blockers
without this:

```bash
cd /home/matt/projects/sci-sim-op
export PATH="$HOME/.local/bin:$PATH"
export REPO3_PATH=/home/matt/projects/siga
export HARNESS_EVOLVE_MODEL=z-ai/glm-5.3-flash
export REPO3_CONTAINER_BACKEND=enroot
```

Verified on 2026-09-02 with those set:

```
uv run python -m pytest tests/ -q                     # 579 passed, 7 skipped
uv run python scripts/evolve.py preflight --simulator geos \
  --ground-truth-dir /home/matt/projects/siga/data/eval/experiments_gt
    # R1 VERIFIED (hook d65d0ee76aee); contamination corpus 46 tasks
    # only remaining blocker: GEOSX_EXECUTABLE, which scripts/_geos.py sets itself
```

Also confirmed present: `geosx` at `/home/brian/.geosx_docker_runtime/install/bin/geosx`;
enroot image `geos-eval`; scratch `/data/matt/tmp_geos`; resume corpus
`.evolve/geos_search/rollouts.jsonl` with **51 rollouts already paid for** — stages 2–4
replay it, so the seed evaluation is not re-bought.

**Run `scripts/provider_watch.py` first anyway.** If any of the above disagrees with this
document, say so in the worklog and trust the measurement, not the document.

## 4. Priority order — spend the budget in this order, stop when it runs out

Wall-clock, not money, is the binding constraint (~12.6 min/rollout, 8-way parallel).

| # | Stage | Rollouts | Why it is in this position |
|---|---|---|---|
| **1** | Unblock acceptance (§5) — **no rollouts** | 0 | Until this is resolved the search accepts nothing and any "null" it reports is an artifact. Non-negotiable first step. |
| **2** | `--stage baseline` (replay + top-up to the pruned task set) | ~20 | Drop the two noisiest tasks per BUDGET_PLAN §3.1 — costs a third fewer rollouts and improves sensitivity 3×. `ExampleDPWellbore` (σ=0.32) is excluded from the mean and reported separately. |
| **3** | `--stage search --budget 3` (all four methods on) | ~90 | The actual experiment. |
| **4** | `--stage baselines` (compute-matched, k derived from the ledger) | ~90 | **Mandatory, not optional.** An unmatched win is not a win. If the budget only covers 3 or 4, it covers both — never ship 3 without 4. |
| **5** | Ablations, one switch at a time (`--ablate gate\|evidence\|pareto\|delta`) | ~90 each | The real deliverable of the programme, but out of budget tonight. Run whichever single ablation the evidence most calls for, and say which you chose and why. |
| **6** | `scripts/report_geos.py` — recompute everything from the corpus, free | 0 | Run this repeatedly; it costs nothing. |

Exact commands: `worklogs/2026-08-26_overnight.md` §13, "The campaign pipeline".

**Two ablation results are already in hand without spending a rollout**, and belong in the
report: the stop policy is measurably **inert** on this pool (zero hook interventions
across a 0.09–0.98 score range while demonstrably delivered and read), and the **zero rate
is already 0.000**, so the regression gate's central clause cannot bind. Two of the
search's four instruments are inert *before the search starts*. Check §22 of the worklog
first — the author partially reversed the "inert" claim after measuring the noise floor.
Report the corrected version.

## 5. Two open decisions — you have authority to settle them. Log them as decisions.

The previous session deliberately left both for a human. Under the `deli-autoresearch`
zero-interaction rule you decide them yourself, write the reasoning to the worklog at
`level=decision`, and make the decision **auditable** — record the metric both ways.

1. **The hygiene false positive** (worklog §17, §§20–21). `rare_token_overlap` blocks the
   seed by flagging **public GEOS API names** — `ExtendedDruckerPrager` appears 24 times in
   `schema.xsd`, which the agent can already read from its own mounted tools. A
   public-vocabulary allowlist is implemented but **off by default**; note there is also a
   `--hygiene-profile {train,strict}` switch, so check whether the knob you need already
   exists before writing code. **Read §21 before acting — the author tested their own top
   recommendation and it failed.** Also remove the `kgdToughnessDominated` line from the
   seed cheatsheet. Record the hygiene verdict with the allowlist on *and* off, so the
   decision can be re-litigated from the artifact.
2. **`checks/` is not vendored into the plugin mount** (worklog §2.6), so
   `required_sections` and `constraints` cannot run in the container — and those are the
   two instruments that detect the binding constraints we actually measured
   (TutorialSneddon's 221 missing elements; Buckley-Leverett's wrong values). The previous
   session called this the highest-value change available. Do it, and prove it ran by
   showing the check firing in a real rollout, not by showing it registered.

## 6. Standing constraints that still hold

- The null result is first-class and pre-registered. Do not tune until something looks
  positive.
- Compute-matched baselines are budgeted in from the start, never added afterwards.
- Efficiency is an acceptance gate, not a metric.
- Do not build a DGM/Hyperagents-style open-ended archive.
- Do not reintroduce retrieval-gated memory (`memory_lookup` was called **zero** times
  across every test-set run while verified functional).
- Do not modify `siga/src/runner/` or `siga/src/eval/` beyond what is already done;
  `docker_cmd.py` rendering is pinned byte-for-byte by `tests/test_container_spec.py`.
- The v4 quarantine stays quarantined. Hygiene runs **before** any rollout is spent.
- Credentials are in `.env` (gitignored, mode 600). Never commit, echo into a log, or put
  them in a URL.
- **The dangerous bugs here are the ones that produce a plausible number, not the ones
  that crash.** Four were found in one night — each by running the thing and reading what
  it produced, never by reading code. Prefer measuring to asserting.

## 7. The clock — this is tighter than "overnight"

**Hard deliverable deadline: 09:00 PT / 16:00 UTC on 2026-09-02.** Established
2026-09-02 03:38 PT, which left **5.4 hours**. Convert to your own clock at every wakeup;
do not assume a full night.

| time (PT) | time (UTC) | gate |
|---|---|---|
| **08:00** | **15:00** | **Stop launching new rollouts.** Anything not started by now will not finish. Let in-flight work drain. |
| **08:30** | **15:30** | Final `report_geos.py` recompute over whatever is in the corpus. Costs nothing. |
| **09:00** | **16:00** | **`REPORT.md` final and committed.** |

At ~12.6 min/rollout and 8-way parallel that is **~150–180 rollouts of real capacity**, not
the ~490 the budget alone would buy. **Money stopped being the binding constraint the
moment the cap was raised; wall-clock is.** Re-plan §4 against wall-clock:

- §4 items 1–4 (unblock, baseline, search, **compute-matched baselines**) are the
  commitment. An unmatched win is not a win — never ship item 3 without item 4.
- §4 item 5 (ablations) is **in budget but probably not in time.** If the clock says one
  ablation arm fits, run the single arm the evidence most calls for and say why you chose
  it. Do not start four and finish none.
- **Prefer one coherent, complete result over four half-finished arms.** A partial arm is
  not a weaker result, it is an uninterpretable one.

## 8. Reporting — the worklog is written as you go, not at the end

Two artifacts, both required. The worklog is a *running* record; the report is a *standing*
document. Do not defer either.

### 8.1 The worklog — `/home/matt/projects/sci-sim-op/worklogs/2026-09-02_overnight.md`

Append **as you go**, following the convention of `worklogs/2026-08-26_overnight.md` — that
file is the model, read its shape before starting. Rules:

- **Time-ordered entries**, each stamped, appended. Never rewrite history: when a later
  measurement contradicts an earlier entry, **correct it in place with a marked note**
  (`**CORRECTION:** …`) rather than silently editing. §§21–22 of the 2026-08-26 log are
  the reference for how to do this well — the author overturned two of their own claims
  and the log is more useful for it, not less.
- **Write the plan before the work**, not after. An entry that only appears once something
  succeeded hides the branches you abandoned, and those are usually the informative part.
- **Every decision gets a `level=decision` entry** with the reasoning and the evidence that
  settled it — especially the two §5 blockers, where the metric must be recorded *both ways*.
- **Absolute paths, always.** Every artifact you produce — corpus files, rollout
  workspaces, receipts, JSON results, logs, plots — is named by full absolute path in the
  worklog at the point it is created. The reader is picking this up cold on a machine they
  have not used. `.evolve/foo.json` is not an answer; `/home/matt/projects/sci-sim-op/.evolve/foo.json` is.
- **Results go in as they land**, with n, and with the command that produced them, so any
  number in the report can be traced back to a reproducible invocation.
- **Cost readings** from each `/api/v1/key` poll, so the spend curve is reconstructable.

### 8.2 The report — `/home/matt/projects/sci-sim-op/.evolve/geos_search/REPORT.md`

**Create it early and keep it current.** Write a first version as soon as the baseline
lands, and refresh it after every stage. The point is that there is a shippable report at
every moment, so an unexpected stop costs you the *last* increment rather than the whole
deliverable. Finalize by 09:00 PT.

It must stand alone for a reader who has not seen the worklog, and it must contain:

1. **What was run** — arms, tasks, seeds, n per cell, and the exact commands.
2. **What it cost** — dollars, rollouts, wall-clock; the spend curve against the cap.
3. **The numbers** — per-task and paired, never a bare mean. Report the tail (zero rate,
   per-task minimum) as a first-class quantity, not an afterthought; that is the objective.
4. **What is NOT believable, and why.** The most important section. Which cells are
   underpowered, which comparisons are unmatched, which arms did not finish, what the
   noise floor implies about the minimum detectable effect. `docs/2026-08-26_BUDGET_PLAN.md`
   §3.1 measured σ from 0.0035 to 0.32 across tasks — a mean over that without a dispersion
   statistic is not a result.
5. **Absolute paths to every artifact** a reader would want to inspect.
6. **The verdict, stated plainly**, including `mechanism_only` or a clean null if that is
   what happened. Per `docs/PROJECT_PRIMER.md` §7 the null is pre-registered and
   first-class. Do not soften it, and do not tune to avoid it.

**This is going in front of a grant project sync.** Write for a reader who is technical but
has not been in this codebase: lead with the finding, put the caveat next to the number it
qualifies rather than in a footnote, and never present a number whose provenance you cannot
name.

## 9. Working conventions

- Commit as you go on `master`. Attribution footer:
  ```
  Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_017xHgB9a13QYRXriSue2ppA
  ```
- **Escalate rather than abandon.** If the budget runs out, the container breaks, or the
  provider stops serving: write the full report, `PushNotification` the owner, and keep
  working on whatever does not depend on the blocked thing.
