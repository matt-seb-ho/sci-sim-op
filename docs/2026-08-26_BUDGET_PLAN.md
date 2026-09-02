# Compute budget plan — GEOS harness-evolution follow-up

**Date:** 2026-08-26 · **Author:** prepared for advisor review
**Status:** costs measured on real rollouts, not estimated from a rate card.

---

## 1. One-paragraph summary

We need to run a self-evolution loop over an LLM agent "harness" and measure
whether it generalizes. One unit of measurement is a **rollout**: one containerized
coding-agent session that authors a GEOS simulator input deck for one task, scored
against a reference deck. The full programme is **~560 rollouts**. Measured cost is
**$0.038 per rollout** on the model we recommend, so the **compute bill is ≈$21**,
with a realistic ceiling of **≈$50** including re-runs. **Money is not the binding
constraint; wall-clock is** — 560 rollouts is ~28 hours at 8-way parallelism.
The ask is therefore modest: **$100 of API credit** covers the programme with 2x
contingency.

---

## 2. Measured per-rollout cost

Two candidate models, two real GEOS rollouts each, costs attributed **per
generation** via OpenRouter's `/api/v1/generation` endpoint (exact billed amounts,
not token estimates).

| model | $/rollout | wall-clock/rollout | tool calls/rollout | scores obtained |
|---|---|---|---|---|
| **`z-ai/glm-5.3-flash`** | **$0.0381** | 12.6 min | 39 | 0.757 / 0.077 |
| `openai/gpt-5.6-luna` | $0.5324 *(see §2.1)* | 3.4 min | 77 | 0.727 / 0.091 |
| `openai/gpt-5.6-luna` (corrected) | **$0.0507** | 3.4 min | 77 | — |

List prices for reference: glm-5.3-flash **$0.075/M in, $0.25/M out**;
gpt-5.6-luna **$0.20/M in, $1.20/M out**.

**Both models produce near-identical scores** on the two probe tasks
(0.757/0.077 vs 0.727/0.091), which is the relevant comparison — a cheaper model
that scores the same is strictly better for this purpose.

### 2.1 A cost leak found while pricing, worth reporting on its own

The raw luna figure is **10x too high**, and the reason is not the model:

| model actually billed | cost | calls | share |
|---|---|---|---|
| `anthropic/claude-sonnet-5` | **$0.9020** | 40 | **85%** |
| `openai/gpt-5.6-luna` | $0.1014 | 64 | 10% |
| `anthropic/claude-4.5-haiku` | $0.0614 | 15 | 6% |

The agent **spawned a subagent that ran on Claude Sonnet 5 for 31 turns**. The
harness blocked `Skill` and `AskUserQuestion` but not `Task`/`Agent`.

This is a **validity problem before it is a cost problem**: a rollout nominally
"on gpt-5.6-luna" was partly executed by a different and stronger model, so any
cross-model comparison built on it would be measuring an uncontrolled mixture.
Fixed by adding `Task`, `Agent`, `TaskCreate` to the disallowed-tool list. The
corrected luna cost is **$0.0507/rollout**.

**Recommendation: `z-ai/glm-5.3-flash`.** Cheapest measured, equal scores, and
the only one of the two that produced no side-model spend. Keep `gpt-5.6-luna`
as the cross-model panel member (§5).

---

## 3. Programme and rollout counts

| phase | what it establishes | rollouts | cost @ $0.038 | wall @ 8-way |
|---|---|---|---|---|
| **P0** baseline / noise floor, 20 train tasks x 3 seeds | per-task variance; without it no comparison is interpretable | 60 | $2.28 | ~3.0 h |
| **P1** search, 12 candidates x 8 anchor tasks x 3 seeds | the actual experiment | 288 | $10.94 | ~14.4 h |
| **P2** champion checkpoints, 3 x 12 probe tasks x 2 seeds | early stopping / selection without touching test | 72 | $2.74 | ~3.6 h |
| **P3** final held-out, 2 arms x 14 tasks x 5 seeds | the reported result | 140 | $5.32 | ~7.0 h |
| **TOTAL** | | **560** | **$21.28** | **~28 h** |

Contingency: re-runs, a second model panel, and the reliability sub-study
(§5) put a realistic ceiling at **$50–$60**. **Requested: $100.**

### 3.1 Why 560 and not fewer

Per-task score noise was measured (18 rollouts, 6 tasks x 3 seeds) and is
**wildly heterogeneous — σ from 0.0035 to 0.32**. The minimum detectable effect
follows directly:

| slice | tasks | seeds | rollouts/arm | MDE |
|---|---|---|---|---|
| all 6 measured tasks | 6 | 3 | 18 | 0.144 |
| **drop the 2 noisiest** | **4** | **3** | **12** | **0.047** |
| 3 quietest only | 3 | 3 | 9 | 0.009 |

**Dropping the two noisiest tasks costs a third fewer rollouts and improves
sensitivity 3x.** One task (`ExampleDPWellbore`, σ=0.32) would need **41 seeds**
to detect a 0.2 effect; it is excluded from the mean and reported separately.

---

## 4. Why this is worth funding: the published result it tests

The one paper in this literature that used a genuinely disjoint train/test split
(arXiv:2607.12227, AI2/UW) reports that harness evolution:

- gains **+1.2** and **+0.0** on held-out tasks for two frontier models;
- scores **below its own starting harness** without unit tests (67.4 vs 68.2);
- **loses to plain parallel sampling** at matched compute (67.4 vs 72.3);
- and its edits *"encode task-specific shortcuts rather than genuinely better
  harness design principles… prone to severe overfitting to the training tasks."*

Of six methods surveyed, **only one uses a three-way split**. One has no split at
all; another adapts on the test stream. **None of the three main comparison
papers reports any dispersion statistic or significance test** — every published
delta is a point estimate over ≤2 repeats.

We additionally found, in the predecessor codebase, that **11 of the 17 tasks its
self-evolution loop optimized on sit inside its own designated test split.**

So the honest framing is not *"make self-evolution work"* — it is **"measure
whether it works when the split is clean, with error bars nobody in this
literature currently reports."** That is a cheaper and more defensible
contribution, and a null is publishable.

---

## 5. Optional extensions, costed separately

| extension | rollouts | cost | why |
|---|---|---|---|
| Cross-model panel (repeat P3 on `gpt-5.6-luna`) | 140 | $7.10 | measured gain depends on the inference model (arXiv:2605.30621) |
| Reliability sub-study (zero-rate CI, 140/arm) | +140 | $5.32 | the central SIGA claim is about catastrophic-failure rate; at 70/arm the intervals overlap and the claim is unresolvable |
| Ablations (4 arms x P1) | +1152 | $43.78 | which of the four adopted ingredients carries any gain |

---

## 6. Risks

1. **Free-tier volatility is why this plan exists.** Five model free-periods
   ended during a single working session on 2026-08-26, including one mid-run
   that failed 33 rollouts instantly. Paid credit removes a dependency that
   proved unmanageable.
2. **Wall-clock, not money, is the schedule risk.** 28 h at 8-way. Parallelism
   above ~8-16 hits provider rate limits.
3. **Side-model spend** (§2.1) is now blocked, but any future harness change that
   re-enables subagents would silently multiply the bill ~10x and invalidate
   model comparisons. Per-generation cost attribution should stay in the loop.
4. **Half the task pool is too noisy to measure.** Handled by pruning to a
   detectable subset and reporting the rest as rates rather than means.

