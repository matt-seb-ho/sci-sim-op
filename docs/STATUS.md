# Status — where the project is, 2026-09-09

One page. What was done, what was learned, what happens next.
Detail lives in [`RESEARCH_PROGRAM.md`](RESEARCH_PROGRAM.md),
[`2026-09-08_BUDGET_PLAN.md`](2026-09-08_BUDGET_PLAN.md),
[`2026-09-09_FUNDING_CASE.md`](2026-09-09_FUNDING_CASE.md),
[`2026-09-02_QA_LOG.md`](2026-09-02_QA_LOG.md).

---

## What was done

**Made the measurement trustworthy.** Eight defects found, six of them sitting
between a rollout and its reported score. All fixed, with tests (609 in the search
repo, 67 in the evaluation harness).

**Ran the first real GEOS numbers.** 109 rollouts. Seed baseline over 6 tasks:
mean 0.655, zero rate 0.000. Paired champion vs seed **+0.116, 95% CI
[−0.083, +0.314]** — spans zero, and the one cell carrying 89% of the point
estimate **failed to replicate**.

**Priced the pipeline properly.** $0.134/rollout measured against billing deltas,
replacing an estimate that was wrong by ~4×.

**Designed the real experiment.** Task-set size derived from measured variance,
family-grouped splits, a mount-level seal for the test split, seven pre-registered
hypotheses.

**Built what the design needs.** Turn cap, `harness_evolve.splits` with the seal,
`scripts/measure_rollouts.py`, `scripts/screen_report.py`, re-baselined spend guard.

**In flight:** the 40-task screen that selects the study set.

## What was learned

**1. In this loop the dangerous bugs do not crash — they return a plausible number.**
The through-line of all eight defects. A stop-policy knob no consumer read; a replay
key that ignored the model; timed-out rollouts scored before their workspace finished
copying, producing fabricated zeros that then nominated their own tasks as search
anchors; infrastructure failures averaged into candidate scores, which would have
**manufactured a positive result in a campaign pre-registered to expect a null**. Every
one was found by running the pipeline and reading its output. None by reading code.

**2. Capability granted at the mount level is invisible.** The geosx binary was mounted
in July so `--validate-input` could run. Nothing distinguished validation from a solve,
so it also handed the agent a full simulator. It sat unused for five weeks, then a model
chose to use it and it became the largest cost driver in the campaign. **The 2026-09-02
arm therefore is not comparing like with like against SIGA's table 1** — its agent had a
capability SIGA's did not.

**3. Blocking a behaviour without explaining it costs more than explaining it without
blocking.** Measured, same six cells: instruction only $0.134/rollout; block only
$0.213 with solve *attempts doubling* (2.83 → 5.67). The block works — 34 attempts, 0
executed — but a refusal invites another variation rather than ending the attempt. Both
are now in place, with the refusal message made terminal.

**4. The scope rule belongs in the task prompt, not the adapter.** In the adapter it is a
searchable component the loop can delete, so arms would silently differ in *what task
they were solving* — and our seed would stop matching SIGA's.

**5. We cannot afford to power our own headline metric.** Separating a 6% catastrophic-
failure rate from 2% needs **376 rollouts per arm**. The primary endpoint moves to the
paired continuous score; the failure rate is reported descriptively. Better to say this
than publish an underpowered tail statistic.

**6. The task pool is ~5 physics families, not 46 independent tasks.** A random
task-level split lets an adapter learn Drucker-Prager from one sibling and score on the
others without generalizing. Splits are family-grouped, and a classification bug that
would have put a wellbore in the poroelastic split was caught by an assertion.

**7. Two of six known tasks are unusable and one is at ceiling** (mean 0.958, 4%
headroom). This is why n=5 comparisons were uninterpretable, and why the screen is the
highest-value purchase available.

**8. Cost cannot be priced from tokens.** Transcript-based estimates over-predict 2.25×
and structurally — fresh input alone exceeds the true total. Every arm is now bracketed
with a billing-API read.

## Open question being measured now

**Our rollouts take 1888 s; SIGA's Claude Code arm took ~500 s on byte-identical task
specs** (33 turns vs 103). The specs are ruled out. Remaining candidates: the model
(`glm-5.3-flash` vs `deepseek-v4-flash`), the agent configuration (SIGA's table-1 arm ran
**no stop hook, no RAG, no xmllint MCP**; ours runs all three plus five stop-policy
checks), and machine contention. A deepseek probe on our exact configuration is queued —
it isolates the model, and prior is that configuration explains most of it.

## What is next

| | | needs |
|---|---|---|
| **now** | 40-task screen → study set, splits, achievable MDE | in flight, ~$10 |
| **then** | seal test, pre-register endpoint/MDE/stopping rule | free |
| | deepseek probe: is the latency gap the model or the config? | ~$1 |
| **blocked on funding** | H1 search vs seed, **with** H2 compute-matched baseline | $20 |
| | H3 which of four ingredients carries any gain | $19 |
| | H5 evolve from scratch vs our handcrafted prior | $10 |
| | H4 transfer to a held-out physics family (test, once) | $3 |
| | H6/H7 transfer across models and harnesses; PEEK vs ACE | $6 |

**Ask: $400** — core programme $70, two more simulators $140, cross-model panel and
replication $100, contingency $90. Roughly two days of one cloud GPU; the project has no
training budget by design, which is why it is this cheap.

**The honest framing for the funding conversation:** the money spent so far bought a
calibrated instrument and a pre-registered design whose unit cost is known to ±$0.01.
What it has not yet bought is the answer. That is the ask.
