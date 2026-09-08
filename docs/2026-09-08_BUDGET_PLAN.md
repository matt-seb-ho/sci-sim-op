# Budget plan — measured 2026-09-08

**Supersedes** [`2026-08-26_BUDGET_PLAN.md`](2026-08-26_BUDGET_PLAN.md), whose
**$0.0381/rollout is wrong by ~4×** and whose "$21 for 560 rollouts" should never be
quoted again. Costs here are measured against **billed account deltas**, not token
arithmetic — §2 explains why that distinction is load-bearing.

Companion: [`RESEARCH_PROGRAM.md`](RESEARCH_PROGRAM.md) (what the money buys).

---

## 1. Headline

| | value | source |
|---|---|---|
| **$/rollout, prose constraint** | **$0.134** | billed account delta, n=6, 2026-09-08 |
| $/rollout, before (self-directed solves) | $0.194 | 2026-09-02 campaign accounting |
| $/rollout, mount-enforced | *pending* | arm in flight |
| **wall-clock/rollout** | **1888 s** (median 1964) | transcript span, n=6 |
| **turns/rollout** | **102.5** (median 75) | transcript, n=6 |
| **tool calls/rollout** | **54.8** (median 37.5) | transcript, n=6 |
| account credit available | **$25.61** | `/api/v1/credits`, 2026-09-08 |
| key spending cap | **removed** (`limit: null`) | `/api/v1/key` |

## 2. Why cost is measured from account deltas, not tokens

The obvious method — count tokens in the agent transcript, multiply by list price
($0.075/M in, $0.250/M out) — **over-predicts by 2.25×**, and not by a constant:

```
actual billed    $0.1343/rollout   ($0.806 / 6 rollouts)
token estimate   $0.3016/rollout   -> 2.25x too high
fresh input alone ($0.2805) already exceeds the true total,
which forces a NEGATIVE implied cache-read price. The model is not just
mis-scaled; its structure is wrong.
```

The transcript records Anthropic-format `usage` blocks; OpenRouter bills on its own
accounting, and `cache_creation_input_tokens` in particular does not map to a billed
fresh-input token. **Do not price an arm from its transcript.**

> **Rule: bracket every arm with an `/api/v1/credits` read and divide.** That is the only
> number that has ever been right. Transcripts remain the right source for turns, tool
> calls, tool mix and wall-clock — all of which they measure directly.

This also explains the original $0.0381 error: it was an n=2 probe on easy tasks, before
three extra stop-policy checks and before the agent started running solves.

## 3. What removing solves bought

Prose constraint in the seed primer ("validate, never solve"), n=6 vs the 58-rollout
2026-09-02 corpus:

| metric | before | after (prose) | change |
|---|---|---|---|
| turns / rollout | 173.3 | **102.5** | **−41%** |
| tool calls / rollout | 89.2 | **54.8** | **−39%** |
| wall-clock / rollout | 3186 s | **1888 s** | **−41%** |
| non-validate `geosx` calls / rollout | 7.34 | **2.83** | **−61%** |
| **$ / rollout** | $0.194 | **$0.134** | **−31%** |
| timeout rate | 50% | 5/6 | *not improved* |

**Two honest caveats.**

1. **The constraint leaked.** 17 non-validate `geosx` invocations still occurred across 6
   rollouts. A prose instruction is not enforcement — which is exactly what
   `memory/constraints.yaml` says in its own header comment. Hence the mount-level
   wrapper (§4).
2. **Timeouts did not improve** (5 of 6). Wall-clock fell 41% but the 2400 s cap is still
   being hit, so something other than solves is also consuming turns. **A turn cap is
   still needed**, and it is not yet implemented — `claude -p` supports `--max-turns` but
   adding it touches `docker_cmd.py`, which is byte-pinned by `tests/test_container_spec.py`.

## 4. The enforcement layer

`/data/matt/geosx_validate_only/` mirrors the real install by symlink, replacing
`bin/geosx` and `bin/geos` with a wrapper that `exec`s the real binary **only** when
`--validate-input` is present, and otherwise exits 64 with an explanation of why a solve
cannot raise the score. `siga/src/runner/constants.py:DEFAULT_GEOSX_INSTALL_DIR` points at
it; `GEOSX_ALLOW_SOLVE=1` restores the real tree. repo3's 66 tests stay green.

**It is a guardrail, not a sandbox.** The real binary sits beside the wrapper as
`.geosx-real`; an agent that goes looking can call it. Making it a true boundary requires
mounting the real install somewhere the container cannot reach, which is a mount change.

## 5. Programme cost, at measured rates

Using **$0.134/rollout** (prose; update when the enforced arm lands) and 1888 s at 6-way
parallelism ≈ **11.4 rollouts/hour**.

| phase | what | rollouts | cost | wall-clock |
|---|---|---|---|---|
| **P-1** | cost/latency baselines | 12 | $1.6 | 1.0 h |
| **P0** | screen ~40 tasks × 2 seeds | 80 | $10.7 | 7.0 h |
| **P0.5** | seal test, pre-register | 0 | $0 | — |
| **P1** | H1 search vs seed, 36 cells | 72 | $9.6 | 6.3 h |
| **P2** | H2 compute-matched baseline | 72 | $9.6 | 6.3 h |
| **P3** | H3 four ablations | 144 | $19.3 | 12.6 h |
| **P4** | H5 from-scratch arm | 72 | $9.6 | 6.3 h |
| **P5** | H4 test, once | 24 | $3.2 | 2.1 h |
| **P6** | H6/H7 harness transfer, PEEK | 48 | $6.4 | 4.2 h |
| | **total** | **524** | **$70** | **~46 h** |

With a turn cap and mount enforcement plausibly halving turns again, the realistic range is
**$40–70**. **Contingency 1.5× → ask for $100.**

### 5.1 What $25.61 buys today

**P-1 + P0 + P0.5 = ~$12**, leaving ~$13 for **P1 + part of P2**. That is: the pool
screened, the study set chosen on measured criteria, the splits sealed and pre-registered,
and the first paired comparison with its compute-matched baseline started. **Enough to
de-risk; not enough to finish.**

Priority if funds run short: **P0 > P0.5 > P1+P2 together > P3.** Never P1 without P2 — an
unmatched win is not a win.

## 6. Wall-clock is still the binding constraint

At 6-way, the programme is ~46 h. Two things make that worse and are not in our control:

- **The box is shared and heavily contended.** Observed load average **119.98** on
  2026-09-02 and **789** later that day, on 128 cores, mostly other users' `SimWorld`
  processes. Record `nproc` and `/proc/loadavg` at the start and end of every arm; a
  wall-clock number without them is uninterpretable.
- **Provider concurrency.** Past ~8–16 concurrent, throughput converts to 429s.

## 7. Standing rules

1. **Bracket every arm with `/api/v1/credits`.** Never price from tokens (§2).
2. **`scripts/search_geos.py` refuses to start** when the account balance is below the
   ceiling — keep that gate; it caught a real case on 2026-09-02.
3. **Watch for side-model spend.** A rollout nominally on one model was once **85% billed
   to `claude-sonnet-5`** through a spawned subagent. `Task`/`Agent`/`TaskCreate` stay in
   the disallowed list; re-verify before each campaign.
4. **Quote the current number.** The old plan's $21 figure is wrong by ~4× and is in a
   document an advisor may already have seen. If a prior number is cited, correct it.
