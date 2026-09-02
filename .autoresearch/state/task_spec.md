# Task spec — GEOS self-evolution initial numbers (unattended, 2026-09-02)

**Brief:** `docs/2026-09-02_KICKOFF_selfevo-benchmark.md`
**Protocol:** `deli-autoresearch`, zero interaction.
**Deadline:** grant project sync, morning of 2026-09-03.

## Goal
Produce initial, honest numbers on whether the modernized self-evolution loop does
anything on GEOS, with compute-matched baselines. A clean null is a first-class,
pre-registered result. Do not tune until something looks positive.

## Milestones (priority order from brief §4)
- M0  Budget enforcement rewritten from "cost must be zero" to "cumulative cap",
      enforced against the OpenRouter account (`data.usage`), polled between batches,
      logged to `.evolve/provider_calls.jsonl`. Verify Task/Agent/TaskCreate disallowed.
- M1  Unblock acceptance (brief §5): settle both open decisions, log at level=decision,
      record the metric BOTH ways. 0 rollouts.
      (a) hygiene false positive / public-vocabulary allowlist + drop the
          `kgdToughnessDominated` cheatsheet line.
      (b) vendor `checks/` into the plugin mount, and prove a check FIRES in a real
          rollout (not merely that it registered).
- M2  `--stage baseline` on the pruned task set (~20 rollouts). Drop 2 noisiest tasks
      per BUDGET_PLAN §3.1; ExampleDPWellbore excluded from the mean, reported separately.
- M3  `--stage search --budget 3`, all four methods on (~90 rollouts).
- M4  `--stage baselines`, compute-matched, k derived from the ledger (~90 rollouts).
      MANDATORY. Never ship M3 without M4.
- M5  One ablation, chosen by evidence, if budget remains. Say which and why.
- M6  `.evolve/geos_search/REPORT.md` standing alone + `worklogs/2026-09-02_overnight.md`.

## Success criteria (evaluable by a fresh session with no context)
1. `.evolve/geos_search/REPORT.md` exists and states: what was run, what it cost,
   the numbers, and what is NOT believable and why.
2. Both §5 decisions appear in `worklogs/2026-09-02_overnight.md` at `level=decision`,
   each with the metric recorded with the change ON and OFF.
3. At least M2 and (M3 AND M4) completed, or an explicit written account of why not.
4. Every number in the report is recomputable from `.evolve/geos_search/rollouts.jsonl`
   by `scripts/report_geos.py`.
5. Total OpenRouter `data.usage` <= $9.75.

## Kill criteria (stop spending; write up; PushNotification)
- K1 OpenRouter `data.usage` > $9.75. HARD STOP on spend.
- K2 Provider stops serving `z-ai/glm-5.3-flash` (do NOT swap to a free model
     mid-experiment; that silently changes the independent variable).
- K3 Container backend broken such that >50% of rollouts return harness_error.
- K4 Wall-clock: stop launching new rollout batches after 2026-09-03T12:00Z so the
     report is written before the sync.
- K5 4 consecutive stalled iterations (stale_count>=4) -> escalate, keep working on
     whatever does not depend on the blocked thing.

## Pre-registered predictions (record before running)
- P1 The search returns its seed (null), per arXiv:2607.12227.
- P2 Compute-matched best-of-k >= search at matched budget.
- P3 Movement on the 3 quiet tasks (sigma<=0.011) is the only detectable movement.
