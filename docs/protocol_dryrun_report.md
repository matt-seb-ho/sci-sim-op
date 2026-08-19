# Protocol dry run — mock simulator

## Configurations compared

Every row is one model x harness configuration. Numbers below belong to a row, never to a system name.

| arm | model | harness | adapter | gen | stop policy | simulator | seeds | test-time scaling | notes |
|---|---|---|---|---|---|---|---|---|---|
| evolved adapter | mock-v1 | harness-evolve/mock | cand_2bd84367be50 | g4 | structured_errors | mock | [7, 8, 9] | harness evolution |  |
| seed adapter (control) | mock-v1 | harness-evolve/mock | cand_6a85403f1d93 | g0 |  | mock | [7, 8, 9] | test-time |  |
| seed adapter + best-of-k (k=11, oracle_best) | mock-v1 | harness-evolve/mock | cand_6a85403f1d93 | g0 |  | mock | [7, 8, 9] | test-time |  |
| seed adapter + best-of-k (k=11, validator_best) | mock-v1 | harness-evolve/mock | cand_6a85403f1d93 | g0 |  | mock | [7, 8, 9] | test-time |  |

### Criterion (fixed before the numbers below)

1. **Beats the honest control.** Paired per-task comparison against the seed adapter at the same seed count: wins > losses at the derived noise band, and no task newly pushed below the catastrophic threshold.
2. **Budget is matched and audited.** Every baseline within 10% of the search's spend in `rollouts`, per the ledger below.
3. **Beats every compute-matched task-level baseline.** Best-of-k (oracle *and* realizable selector) and sequential refinement. A tie counts as a failure: equal score at equal compute is not better design.
4. **Paired statistical support.** A 95% bootstrap CI on the per-task deltas excluding zero, or a permutation test rejecting at alpha=0.05 while powered enough to do so.

If 1-3 hold but 4 does not, the outcome is `mechanism_only`: the tail mechanism is visible but the design cannot measure it. If 1 or 3 fails, the outcome is `fails`.

## Budget ledger

Plan: k = ceil(126/12) = 11; baseline spends 132 rollouts, 6 more than the search's 126.

| arm | rollouts | attempts | tool calls | wall (s) | in tok | out tok | USD | note |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| search | 126 | 126 | 5508.18 | 66097.8 | 5.16023e+06 | 660978 | 25.40 | anchor evaluation; probe evidence (not scored); anchor evaluation; anchor evaluation; anchor evaluation; anchor evaluation; anchor evaluation; anchor evaluation; anchor evaluation; anchor evaluation; probe evidence (not scored); anchor evaluation; anchor evaluation; anchor evaluation; anchor evaluation; anchor evaluation; anchor evaluation; anchor evaluation; anchor evaluation |
| control | 24 | 72 | 1139.72 | 13676.8 | 1.04171e+06 | 136768 | 5.18 | seed adapter, 3 seeds, no scaling; seed adapter, 3 seeds, no scaling |
| best_of_k | 264 | 792 | 12297.8 | 147572 | 1.12401e+07 | 1.47572e+06 | 55.86 | k=11 independent draws per (task, replicate); k=11 independent draws per (task, replicate) |
| evolved | 12 | 12 | 508.83 | 6105.79 | 492026 | 61057.9 | 2.39 | held-out evaluation |

Ratios against `search`:

| arm | rollouts | attempts | tool_calls | wall_seconds | input_tokens | output_tokens | usd |
|---|---:|---:|---:|---:|---:|---:|---:|
| control | 0.19x | 0.57x | 0.21x | 0.21x | 0.20x | 0.21x | 0.20x |
| best_of_k | 2.10x | 6.29x | 2.23x | 2.23x | 2.18x | 2.23x | 2.20x |
| evolved | 0.10x | 0.10x | 0.09x | 0.09x | 0.10x | 0.09x | 0.09x |

`attempts` counts agent attempts inside rollouts (initial try plus stop-hook retries). Parallel and sequential scaling are not matchable in the same unit, so both are reported and the verdict names the unit it uses.

## Per-task paired results

Slice: `held_out`; per-task summary across seeds: `mean` (worst seed in parentheses). Noise band +-0.1049 (2x max median across-seed SD (0.0524)).

| task | evolved adapter (min) | seed adapter (control) (min) | seed adapter + best-of-k (k=11, oracle_best) (min) | seed adapter + best-of-k (k=11, validator_best) (min) | delta vs seed_control | delta vs best_of_k_oracle | delta vs best_of_k_validator | vs control |
|---|---|---|---|---|---|---|---|---|
| task_10 | 0.187 (0.127) | 0.043 (0.043) | 0.043 (0.043) | 0.043 (0.043) | +0.144 | +0.144 | +0.144 | W |
| task_11 | 0.308 (0.308) | 0.043 (0.043) | 0.043 (0.043) | 0.043 (0.043) | +0.265 | +0.265 | +0.265 | W |
| task_12 | 0.317 (0.000) | 0.392 (0.392) | 0.392 (0.392) | 0.392 (0.392) | -0.075 | -0.075 | -0.075 | T |
| task_13 | 0.475 (0.475) | 0.308 (0.308) | 0.419 (0.308) | 0.364 (0.308) | +0.167 | +0.056 | +0.111 | W |

Win/loss/tie vs control: **3W / 0L / 1T at noise band +-0.1049 (2x max median across-seed SD (0.0524))**. The tie count is a headline number: a mean delta built from a couple of tasks is a different claim from a broad improvement.

## Paired statistics

### evolved adapter vs seed adapter (control) (`seed_control`)

- mean paired delta: **+0.1251**
- bootstrap: point +0.1251; **no CI** -- n=4 paired tasks is below the floor of 6; a percentile interval here reports which of a handful of tasks was drawn, not a sampling distribution
- permutation: p = 0.2500 (exact, 3/4 tasks moved) -- **underpowered**: the smallest p this design can produce is 0.250 > alpha 0.05
- effect size: r_rb = +1.000 (over 3 moved tasks); headroom captured = +15.6%; d_z = +0.87 (diagnostic only)
- win/loss/tie: 3W / 0L / 1T at noise band +-0.1049 (2x max median across-seed SD (0.0524))
- rescues: rescued 1 ['task_11'], lost 1 ['task_12'] (threshold 0.25 on per-task min)

### evolved adapter vs seed adapter + best-of-k (k=11, oracle_best) (`best_of_k_oracle`)

- mean paired delta: **+0.0974**
- bootstrap: point +0.0974; **no CI** -- n=4 paired tasks is below the floor of 6; a percentile interval here reports which of a handful of tasks was drawn, not a sampling distribution
- permutation: p = 0.5000 (exact, 2/4 tasks moved) -- **underpowered**: the smallest p this design can produce is 0.500 > alpha 0.05
- effect size: r_rb = +1.000 (over 2 moved tasks); headroom captured = +12.6%; d_z = +0.68 (diagnostic only)
- win/loss/tie: 2W / 0L / 2T at noise band +-0.1049 (2x max median across-seed SD (0.0524))
- rescues: rescued 1 ['task_11'], lost 1 ['task_12'] (threshold 0.25 on per-task min)

### evolved adapter vs seed adapter + best-of-k (k=11, validator_best) (`best_of_k_validator`)

- mean paired delta: **+0.1113**
- bootstrap: point +0.1113; **no CI** -- n=4 paired tasks is below the floor of 6; a percentile interval here reports which of a handful of tasks was drawn, not a sampling distribution
- permutation: p = 0.2500 (exact, 3/4 tasks moved) -- **underpowered**: the smallest p this design can produce is 0.250 > alpha 0.05
- effect size: r_rb = +1.000 (over 3 moved tasks); headroom captured = +14.1%; d_z = +0.79 (diagnostic only)
- win/loss/tie: 3W / 0L / 1T at noise band +-0.1049 (2x max median across-seed SD (0.0524))
- rescues: rescued 1 ['task_11'], lost 1 ['task_12'] (threshold 0.25 on per-task min)

## Tail statistics

The claimed effect is a variance collapse driven by zero-score runs, so these are primary results. A mean is a lossy projection of them.

| arm | runs | zero rate | zero-rate 95% CI (task-clustered) | naive Wilson CI | runs < 0.25 | tasks with any catastrophe | mean per-task min | pooled across-seed SD |
|---|---:|---:|---|---|---:|---|---:|---:|
| evolved adapter | 12 | 0.083 | refused (4 task clusters is below the floor of 6; the interval would be an artifact of which tasks were drawn) | [+0.0149, +0.3539] | 3 | ['task_10', 'task_12'] | 0.228 | 0.1468 |
| seed adapter (control) | 12 | 0.000 | refused (4 task clusters is below the floor of 6; the interval would be an artifact of which tasks were drawn) | [+0.0000, +0.2425] | 6 | ['task_10', 'task_11'] | 0.197 | 0.0000 |
| seed adapter + best-of-k (k=11, oracle_best) | 12 | 0.000 | refused (4 task clusters is below the floor of 6; the interval would be an artifact of which tasks were drawn) | [+0.0000, +0.2425] | 6 | ['task_10', 'task_11'] | 0.197 | 0.0481 |
| seed adapter + best-of-k (k=11, validator_best) | 12 | 0.000 | refused (4 task clusters is below the floor of 6; the interval would be an artifact of which tasks were drawn) | [+0.0000, +0.2425] | 6 | ['task_10', 'task_11'] | 0.197 | 0.0481 |

### Does this survive a compute-matched comparison?

**Verdict: `fails`.** A compute-matched baseline matched or beat the evolved candidate, or the control was not beaten.

- (1) control: 3W / 0L / 1T at noise band +-0.1049 (2x max median across-seed SD (0.0524)), mean delta +0.1251 -> passes
- (1) control: tasks newly below the catastrophic threshold: ['task_12'] -> **fails**
- (3) baselines: no budget-matched task-level baseline was available -- the central question is untested
- (4) support: control point +0.1251; **no CI** -- n=4 paired tasks is below the floor of 6; a percentile interval here reports which of a handful of tasks was drawn, not a sampling distribution; p = 0.2500 (exact, 3/4 tasks moved) -- **underpowered**: the smallest p this design can produce is 0.250 > alpha 0.05 -> **not established**
- (4b) mechanism: rescued 1 ['task_11'], lost 1 ['task_12'] (threshold 0.25 on per-task min); zero-rate change +0.083 -> not visible

Arms whose budget was not matched in `rollouts`: ['best_of_k_oracle', 'best_of_k_validator']. Their comparisons are reported but carry no weight in this verdict.

## Caveats

- Synthetic world with a planted gradient. Says nothing about any real simulator.
- The proposer is a random-edit control drawing from a useful line pool, not a reasoning proposer.
- ARM MISSING: sequential refinement — cannot spend 11 refinement passes through the stop policy (stop_policy.retries out of range [0,6]: 10); the sequential baseline cannot be budget-matched at this k without changing the harness, which would unfreeze it

## Slice audit trail

Slices (`default`): anchor 6, probe 3, held-out 4; held-out released: yes

| when | slice | purpose | requester | tasks | note |
|---|---|---|---|---:|---|
| 2026-08-19T18:59:27.740393+00:00 | anchor | selection | search | 6 |  |
| 2026-08-19T18:59:27.740410+00:00 | probe | evidence | search | 3 |  |
| 2026-08-19T18:59:27.922282+00:00 | held_out | final_report | protocol dry run (cand_2bd84367be50) | 4 | final comparison, one candidate |
