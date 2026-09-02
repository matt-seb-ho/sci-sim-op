# Overnight worklog — GEOS self-evolution, initial numbers

**Brief:** [`docs/2026-09-02_KICKOFF_selfevo-benchmark.md`](../docs/2026-09-02_KICKOFF_selfevo-benchmark.md)
**Mode:** unattended, zero interaction, `deli-autoresearch` protocol.
**Deliverable:** initial honest numbers for the grant project sync, morning of 2026-09-03.
**Model:** `z-ai/glm-5.3-flash`. **Hard spend cap:** OpenRouter `data.usage` > $9.75 → stop.

Conventions follow [`2026-08-26_overnight.md`](2026-08-26_overnight.md): time-ordered,
absolute paths, corrections marked **in place** rather than silently edited, written for
someone picking it up cold. All times UTC.

State for the autonomous loop lives in `/home/matt/projects/sci-sim-op/.autoresearch/`
(`state/task_spec.md` has the success and kill criteria; `logs/*.jsonl` the event log).

---

## 0. Entry checks (10:13–10:22)

Read in the order the brief specifies: `docs/PROJECT_PRIMER.md`,
`docs/2026-08-26_followup-goals.md`, `worklogs/2026-08-26_overnight.md` (§13, §§16–18,
§§19–24), `docs/2026-08-26_BUDGET_PLAN.md`, `docs/2026-08-26_KICKOFF_free-window-campaign.md`.

Environment, with the brief's exports set:

```
REPO3_PATH=/home/matt/projects/siga        HARNESS_EVOLVE_MODEL=z-ai/glm-5.3-flash
REPO3_CONTAINER_BACKEND=enroot             PATH=$HOME/.local/bin:$PATH
```

| check | brief says | measured 2026-09-02 | verdict |
|---|---|---|---|
| `pytest tests/ -q` | 579 passed, 7 skipped | **584 passed, 2 skipped** | disagrees; trust the measurement |
| `evolve.py preflight` | R1 verified, 46-task corpus, only `GEOSX_EXECUTABLE` blocking | identical, hook `d65d0ee76aee` | agrees |
| `geosx` binary | `/home/brian/.geosx_docker_runtime/install/bin/geosx` | present, executable | agrees |
| enroot image `geos-eval` | present | present | agrees |
| scratch `/data/matt/tmp_geos` | present | present, 17T free | agrees |
| OpenRouter account | usage $1.271071093, limit $10, remaining $8.728928907 | **exactly those figures** | agrees |
| `Task`/`Agent`/`TaskCreate` blocked | required | `siga/src/runner/constants.py:87` — all three present | agrees |
| resume corpus | "51 rollouts already paid for … the seed evaluation is not re-bought" | **see §1 — this is wrong** | **disagrees** |

The test-count discrepancy (584/2 vs the brief's 579/7) is small and in the safe
direction. Noted, not chased.

---

## 1. F1 — the resume corpus would have fabricated the baseline (10:22–11:05)

**level=finding.** This is the first thing found and it invalidates a premise the
brief, the primer (§8) and the budget all rest on. It is also, exactly, this project's
signature defect: *not a crash, a plausible number.*

### 1.1 What the corpus actually contains

The brief: *"resume corpus `.evolve/geos_search/rollouts.jsonl` with **51 rollouts
already paid for** — stages 2–4 replay it, so the seed evaluation is not re-bought."*

```
$ wc -l /home/matt/projects/sci-sim-op/.evolve/geos_search/rollouts.jsonl
51
$ # by status
{'harness_error': 33, 'success': 17, 'parse_error': 1}
```

- **33 of the 51 are the 16:27 404 storm** of 2026-08-26 (§25.1 of the previous log) —
  the instant failures when `stealth/ox-alpha`'s free period ended mid-run. They carry
  no score and are excluded from every average, correctly.
- **The remaining 18 are the ox-alpha noise floor** (§24.2): 6 tasks × 3 seeds,
  mean 0.6127, zero rate 0.056.

So the corpus holds **18** usable rollouts, not 51. That alone is a budget correction.

### 1.2 The part that matters: the replay key does not include the model

```
$ grep -n "def key" -A 2 src/harness_evolve/runners/cached.py
135:    def key(self) -> CacheKey:
136:        return (self.candidate_id, self.task, self.seed)
```

`RolloutRecord` had **no model field at all** — not in the key, not in the record, not
on disk. `RecordingRunner.run()` replays on `(candidate_id, task, seed)`.

The seed candidate is `cand_78856ef8131e` in both campaigns. The task list and seeds in
the brief's §4 stage-2 command are the same six tasks and the same seeds. Therefore:

> Running `--stage baseline` tonight on `z-ai/glm-5.3-flash` would have **replayed all
> 18 `stealth/ox-alpha` rollouts**, reported them as glm-5.3-flash results, printed
> `18 rollout(s): 0 executed, 18 replayed from the corpus`, cost $0.00, and produced the
> seed baseline that every search and every compute-matched arm is measured against.

The previous session's own §25.2 states the rule this breaks: *"nothing measured on a
different model may be pooled with it"*, and §25.4: *"per-task sigma is a property of
model × task, not of the task."* The rule was written down; nothing enforced it, because
the corpus could not represent the distinction.

It would have looked entirely normal. The replay line is a *feature* of the harness and
prints on every resume; the numbers are real numbers from real rollouts; the seed mean
would have been 0.6127, which is the number the primer already quotes. Nothing in any
log, report or plot would have said "different model".

### 1.3 The fix

The inference model is now part of a rollout's identity, end to end.

| file | change |
|---|---|
| `src/harness_evolve/runners/cached.py` | `RolloutRecord.model: str \| None`; `CacheKey` is now `(cid, task, seed, model)`; `CachedRunner(model=...)`; `ANY_MODEL` sentinel for offline re-analysis of a single-model corpus, which raises `AmbiguousReplay` rather than choosing when a cell exists under two models |
| `src/harness_evolve/runners/recording.py` | `RecordingRunner(model=...)` stamps every written row and replays only matching rows; **reports the non-matching ones out loud** in `stats.notes` |
| `scripts/search_geos.py` | passes `model=MODEL` and prints the corpus notes before spending anything |
| `scripts/report_geos.py` | groups by *(candidate, model)*, `--model` filter, warns when several models are present, and refuses to pair arms across models |
| `scripts/_geos.py` | `MODEL` default `z-ai/glm-5.2:free` → **`z-ai/glm-5.3-flash`** (the old default is a dead slug: it 404s and every rollout returns `harness_error`, which reads as an outage rather than as a misconfiguration) |

Corpus migrated: all 51 rows tagged `"model": "stealth/ox-alpha"`, which is what
produced them (by attempt, for the 33). Backup at
`/home/matt/projects/sci-sim-op/.evolve/geos_search/rollouts.jsonl.pre-model-tag.bak`.

**Verification that the migration is faithful** — the report reproduces §24.2 exactly:

```
$ uv run python scripts/report_geos.py --out .evolve/geos_search
models in corpus: stealth/ox-alpha
== cand_78856ef8131e  model=stealth/ox-alpha  n=18
   mean 0.6127   zero rate 0.056   min 0.0000   max 1.0000
     AdvancedExampleDruckerPrager   0.9060 +/- 0.0815    ExampleDPWellbore    0.7121 +/- 0.3192
     ExampleIsothermalLeakyWell     0.9746 +/- 0.0054    ExampleMandel        0.2155 +/- 0.1870
     TutorialSneddon                0.0879 +/- 0.0105    buckleyLeverettProblem 0.7801 +/- 0.0035
```

Four tests pin the behaviour in four directions (`tests/test_recording.py`), the third
being the one that matters — the fix is a *narrowing*, and a narrowing that also broke
resume would be worse than the bug:

| test | asserts |
|---|---|
| `..._recorded_on_another_model_is_not_replayed` | the ox-alpha row is re-executed, not served |
| `..._recorded_on_the_same_model_is_still_replayed` | genuine resume still works, 0 executed |
| `the_unreplayable_rows_are_reported_not_silently_ignored` | the cost of *not* replaying is stated, not silent |
| `a_corpus_holding_two_models_refuses_to_guess` | mixed corpus raises `AmbiguousReplay` |

```
$ uv run python -m pytest tests/ -q
588 passed, 2 skipped        # 584 at session start
```

### 1.4 Consequence for tonight's budget — the seed baseline must be re-bought

This is the practical cost, and it changes §4 of the brief:

- the seed evaluation is **not** already paid for on the campaign model;
- the per-task σ used by `BUDGET_PLAN` §3.1 to choose which tasks to drop is an
  **ox-alpha** σ, so the task-pruning decision is being made on another model's noise.

Both are handled in §3 below rather than papered over. The 18 ox-alpha rollouts remain
a valid frozen dataset — for ox-alpha — and are reported as such.

---

## 2. F2 — the proposer was pointed at a dead model (11:05–11:20)

**level=finding.** Found while rewiring the budget enforcement, in the same file.

```
$ grep -n "backend=" scripts/search_geos.py        # before
284:        backend=free_window_backend(),
$ grep -n "def free_roster" src/harness_evolve/proposers/backends.py
339:def free_roster(models: Sequence[str] = (OX_ALPHA,)) -> list[Route]:
$ grep -n "^OX_ALPHA" src/harness_evolve/proposers/backends.py
67:OX_ALPHA = "stealth/ox-alpha"
```

`free_window_backend()` is called with no argument, so the proposer's roster is
`stealth/ox-alpha` — dead since 2026-08-26 16:27. **Every proposal call would have
404'd.** The search would have proposed nothing, evaluated nothing, and returned its
seed.

This is F1's twin, and the pairing is the point: F1 would have fabricated the
*baseline*, F2 would have fabricated the *null*. Both produce a search that completes,
prints plausible numbers, and reports the pre-registered result for the wrong reason —
which is precisely what §16.2 of the previous log warned about after it happened once
already (*"the prediction being right is exactly what made it dangerous"*).

**Fix:** `campaign_backend(models, ...)` — the paid-campaign backend, with **no default
model**. A backend that must be told which model it is running cannot go stale. The
free-window backend is kept, unchanged, for the campaign and tests it belongs to.

---

## 3. M0 — budget enforcement rewritten (11:05–11:40)

The brief's §2 was corrected mid-session (commit `cc2af8d`) and the correction matters:
the `$10` is a **per-key spending cap**, not the account balance. Confirmed both, live:

```
$ GET /api/v1/credits    total_credits 210, total_usage 168.323160449   -> $41.68 available
$ GET /api/v1/key        limit 10, usage 1.271071093, limit_remaining 8.728928907
```

So the authorized $20 is affordable to the account; only the key cap is in the way, and
the owner may raise it from the dashboard while this runs.

### 3.1 DECISION D0 — how the ceiling is computed

**level=decision.** The brief says: *"recompute your ceiling as `min(20.00,
limit_remaining)` of ADDITIONAL spend measured from the usage baseline $1.271071093"*,
and *"hard-stop when `usage - 1.271071093 >= min(20.00, limit_remaining)`"*.

Taken literally against a **live** reading, that rule halts at half the allowance.
`limit_remaining == limit - usage`, so as `usage` rises the left side grows and the
right side shrinks; they meet where `2·usage = limit + baseline`, i.e. at
`usage = $5.6355` — **$4.36 spent of an $8.73 allowance.**

The two forms agree at *t=0*, which is exactly what makes the wrong one easy to ship,
and it is the same shape as everything else in this log: a rule that looks right and
silently does something else.

**Settled as:** the intended quantity is the key's headroom *at the baseline*, which is
a fixed number that does not move as we spend and which rises the moment the owner
raises the cap:

```
ceiling_additional = min( AUTHORIZED $20.00 , key.limit − baseline − reserve $0.25 )
```

With `limit=10` this is **$8.479** additional → a hard stop at `usage = $9.75`, which is
the figure in the original instruction. If `limit` is raised to 30, the ceiling becomes
the full **$20.00** with no restart. The $0.25 reserve exists because crossing a
provider-side cap does not warn — it starts refusing calls mid-rollout, converting
paid-for work into `harness_error`s.

A second, independent stop remains from the brief and is *not* redundant with the first:
halt when live `limit_remaining` falls below the cost of one more batch.

Pinned by `tests/test_spend_guard.py::test_the_ceiling_does_not_shrink_as_we_spend`,
which asserts the guard has **not** tripped at the point the naive form would have.

### 3.2 What was built

`src/harness_evolve/spend.py` — named `spend`, not `budget`, because
`harness_evolve.evaluation.budget` already exists and means *compute* matching. (I
clobbered its test file before noticing; restored from git, and the module renamed so the
collision cannot recur.)

| piece | does |
|---|---|
| `read_openrouter_usage()` | `GET /api/v1/key` with a `User-Agent`. An unreadable counter **raises** — "probably fine" is how a cap becomes decorative |
| `read_account_credits()` | `GET /api/v1/credits`, checked once at start: if the *balance* is the binding limit, raising the key cap would not help and the run should not start |
| `BudgetGuard` | polls (rate-limited, forced at batch boundaries), logs **every** reading to `.evolve/provider_calls.jsonl`, trips at the ceiling, announces a cap change |
| `BudgetGuardedRunner` | refuses to **start** a rollout past the ceiling |
| `CostLedger` | policy changed from "cost must be zero" to `cap_usd`; docstring now says out loud that it sees **proposer calls only** |

**Placement is a design decision.** The guard sits *inside* the recording runner, so a
replayed rollout is never gated: when the money runs out, free re-analysis and resume are
the only work left, and that is the worst possible moment for them to start failing.
Tested (`test_a_replayed_rollout_is_not_gated`).

**Verified before the first run:** `Task`, `Agent`, `TaskCreate` are all present in
`/home/matt/projects/siga/src/runner/constants.py:87 NATIVE_CLAUDE_DISALLOWED_TOOLS`.
This is the fix for the 2026-08-26 §29.3 leak where a rollout nominally on one model was
85% billed to Claude Sonnet 5 — a validity problem before a cost one.

```
$ uv run python -m pytest tests/ -q
600 passed, 2 skipped
```

---

## 4. DECISION D1 — the hygiene question, settled (11:20–11:50)

**level=decision.** Brief §5.1. Recorded with the metric **both ways**, as instructed.

### 4.1 First, a correction to the brief and to `PROJECT_PRIMER.md` §8

Both say acceptance is currently 0% by construction. **Measured: it is not, and has not
been since `train_profile` landed.** The driver already defaults to
`--hygiene-profile train`, which demotes the statistical rules to warnings:

```
seed cand_78856ef8131e (as inherited), 46-task corpus:
  scope=all  profile=train   allowlist=OFF   blocked=False   0 errors, 7 warnings
```

The §17/§20 blocker was real when written and was superseded later the same session by
the profile switch, which the closing summary did not pick up. The brief's own hint —
*"check whether the knob you need already exists before writing code"* — is the right
instinct and it pays off here. **I did not need to weaken anything to unblock the
search.** What follows is therefore about making the artifact *actually* clean rather
than about relying on demotion.

### 4.2 The metric, both ways, before and after

Seed = `.evolve/seed`, corpus = 46 GEOS ground-truth tasks. `allowlist` = subtract the
2512 identifiers GEOS declares in its own `schema.xsd`.

**BEFORE** (`cand_78856ef8131e`):

| scope | profile | allowlist | blocked | errors |
|---|---|---|---|---|
| all | strict | OFF | **True** | `task_id`, `rare_token_overlap` |
| all | strict | ON | **True** | `task_id` |
| all | train | OFF | False | — (7 warnings) |
| all | train | ON | False | — (6 warnings) |
| pool | strict | OFF | **True** | `rare_token_overlap` |
| pool | strict | ON | False | — |
| pool | train | OFF/ON | False | — |

**AFTER** — allowlist enabled by default *and* the `kgdToughnessDominated` line removed
from the seed cheatsheet (`cand_fb93fe5d0f19`):

| scope | profile | allowlist | blocked | errors |
|---|---|---|---|---|
| all | strict | **OFF** | **True** | `rare_token_overlap` ← the false positive, deliberately still reproducible |
| all | strict | **ON** | **False** | — |
| all | train | OFF | False | — |
| all | train | ON | False | — |
| pool | strict | OFF | **True** | `rare_token_overlap` |
| pool | strict | ON | **False** | — |
| pool | train | OFF/ON | False | — |

**The seed now passes the strictest configuration in the codebase.** That is a stronger
position than the run needs, and it is the point: the search's acceptance rate is not
gated by a hygiene artifact under *any* setting, so a null cannot be blamed on the gate.

### 4.3 The reasoning

Two separate things were conflated in §17, and they get opposite answers.

1. **`task_id` naming `kgdToughnessDominated` — a genuine leak.** It is an evaluation
   task id in the 46-task set. Removed. The *lesson* in that cheatsheet line ("do not
   invent attribute names, verify via RAG") is kept; only the task id is dropped, so
   the adapter loses nothing it was entitled to.
2. **`rare_token_overlap` on public GEOS API names — a false positive.** The rule
   computes idf over the ground-truth deck corpus, so a constitutive-model name used by
   one physics type scores as rare. It never asks whether the token is *public*.
   `ExtendedDruckerPrager` occurs 24 times in `schema.xsd`; `geosx --validate-input`
   prints it; `/geos_lib` is mounted read-only into every rollout and the RAG MCP
   indexes it. **A cheatsheet naming it hands the agent nothing it could not obtain
   from the tools it already has.** A leak is information about *the answer*; this is
   information about *the API*.

Subtracting public vocabulary is therefore not a relaxation — it is the rule finally
measuring what it claims to. Weakening a contamination gate to make a search run would
be the move that makes every downstream number unbelievable, so the claim is tested
rather than argued:

### 4.4 The check that keeps it honest

**Does the exemption hide the real leak?** The quarantined v4 adapter — whose cheatsheet
is a task→ground-truth lookup table for all 17 val tasks — is the test case:

```
v4  profile=strict allowlist=OFF  blocked=True  errors=56
v4  profile=strict allowlist=ON   blocked=True  errors=54
v4  profile=train  allowlist=OFF  blocked=True  errors=30
v4  profile=train  allowlist=ON   blocked=True  errors=30   <- most permissive setting
```

**v4 blocks in all four**, with 30 errors under the most permissive configuration
(`blocklist`, `filename`, `filename_generic`, `lookup_table`, `task_id_table`). The
exemption removes 2 findings out of 56 and none of the load-bearing ones. The quarantine
holds.

### 4.5 What was changed, and how to re-litigate it

- `.evolve/seed/memory/cheatsheet.md` — the `kgdToughnessDominated` line rewritten to
  drop the task id, keeping the instruction.
- `scripts/_geos.py` — `GEOS_SCHEMA`, overridable via `GEOS_SCHEMA_XSD`.
- `scripts/search_geos.py` — `geos_public_vocabulary()`, cached to
  `/home/matt/projects/sci-sim-op/.evolve/geos_public_vocabulary.json` so the exact
  allowlist a run used is on disk and auditable; **on by default**, with
  **`--no-public-vocab`** to reproduce the 2026-08-26 false positive on demand.

**The seed's candidate id changed**: `cand_78856ef8131e` → `cand_fb93fe5d0f19`. Recorded
because the corpus is keyed on it; the ox-alpha rows belong to the old id and to a dead
model, and are now doubly non-replayable.

---

## 5. DECISION D2 — `checks/` vendored into the plugin mount (11:50–12:35)

**level=decision.** Brief §5.2. The previous session called this the highest-value change
available and then, in §21, **tested its own claim and found it false**. Both things are
true and the resolution is in §5.4 below.

### 5.1 Why it could not run, and the delivery mechanism

The hook executes *inside* the rollout container, where `harness_evolve` is not installed
and cannot be — the image is not ours to rebuild per candidate. So
`required_sections`, `constraints` and `cross_section_refs` were recorded as
`checks_unsupported` and skipped (§2.6).

The adapter directory *is* mounted into every rollout, read-only, at `/plugins/repo3`
(`siga/src/runner/docker_cmd.py:68`). So it is the delivery mechanism, and **no change to
`docker_cmd.py` was needed** — which matters, because its rendering is pinned
byte-for-byte by `tests/test_container_spec.py`.

`src/harness_evolve/vendoring.py` copies a **subtree, not the package**:
`__init__.py`, `types.py`, `checks/`, `simulators/`. That boundary is deliberate — a
check able to import the search loop, the proposers or the provider backends could reach
the ground-truth corpus and the network from inside a rollout, which is the boundary the
whole hygiene programme defends. The closure is asserted by a test that imports it in a
subprocess with nothing else on `sys.path`, so an import added later fails a test rather
than failing a rollout four hours into a run.

`SubprocessRunner.materialize()` calls it; the hook puts `<adapter>/vendor` on `sys.path`
and degrades to the native checks (recording *why*, in the event log) if the tree is
missing. An import failure must never crash every rollout, and must never be silent.

### 5.2 Proof that it fires — the hook, the real layout, a real deck

The brief asks for the check *firing*, not registering. A deck that **parses**, that
`geosx` would load, and that is missing `<ElementRegions>`:

```
$ echo '{"stop_hook_active": false}' | python3 <adapter>/hooks/verify_outputs.py
{"decision": "block", "reason": "Stop blocked by verify_outputs hook: the deck parses
 and loads, but failed required_sections:\n\n- [required_sections] artifact defines no
 <ElementRegions> section ()\n\nThese are completeness/consistency checks, not syntax
 checks. Fix the reported cause, then end your turn."}
```

and the hook's own event log, which is the artifact R1 taught us to trust:

```json
{"decision": "block", "reason_category": "vendored_check", "retries_so_far": 1,
 "checks": ["parse","required_sections","constraints","cross_section_refs"],
 "checks_source": "env",
 "checks_unsupported": [],                       <- was all three
 "checks_vendored_run": ["required_sections","constraints","cross_section_refs"],
 "checks_vendored_findings": [{"source":"required_sections","severity":"error",
   "message":"artifact defines no <ElementRegions> section","location":""}]}
```

The adapter was materialized through the real path, so the hook resolved `vendor/` from
the same relative layout it sees at `/plugins/repo3` in the container.

### 5.3 Enabled for the campaign, and why that is safe

The seed's stop policy now reads
`checks = ["parse","geosx_validate","required_sections","constraints","cross_section_refs"]`.

`checks` is **not in the search space** (§26 of the previous log: no proposer can edit a
`kind="config"` component), so this is a harness constant, identical across the search
arm, every baseline arm and every ablation arm. It therefore cannot bias the comparison
the campaign exists to make. What it buys is a **measurement**: §21 observed zero findings
on three decks; this turns that into a firing rate over the whole campaign.

Seed cid: `cand_fb93fe5d0f19` → **`cand_d1c0f1f0f516`**.

### 5.4 What this does *not* buy — §21 stands, and is the honest headline

Vendoring makes these checks *runnable*. It does not make them *able to see the failure we
measured*, and the report must say so:

- `required_sections` is a **section-presence** check. `TutorialSneddon` scored 0.0925 with
  **38 elements against a 252-element ground truth** and yet contains all 4 required
  sections and all 11 optional ones. A complete skeleton and an empty body. The check
  cannot see it.
- `constraints` is a **content** check and the seed ships `constraints: []`. It can only
  return nothing. (The hook now loads the candidate's `memory/constraints.yaml` explicitly,
  so "fired and found nothing" is distinguishable in the log from "could not fire".)

So the prediction on record, before the rollouts land: **these three checks will fire at a
rate near zero on real decks, and the gap is not which checks are wired up — it is that
no check in the registry measures completeness.** Writing one is real work and is
deliberately not attempted tonight, for the reason §21.4 gives: every cheap way to write it
(ground-truth element count, ground-truth element types) is a contamination leak through
the feedback channel, and the hygiene gate audits the adapter, not the hook's feedback.

Recording the prediction now is the point. If the firing rate comes back near zero, that is
a confirmed pre-registered result rather than a post-hoc excuse.

### 5.5 The R1 receipt caught the change, correctly

Launching the baseline immediately refused:

```
R1 is not verified, refusing to spend rollouts: the R1 receipt was written for a
different verify_outputs.py (receipt d65d0ee76aee, on disk 279dc7f8ee4a).
```

The receipt is SHA-pinned to the hook, and I changed the hook. **This is the gate working.**
Re-running `siga/scripts/verify_r1_feedback_channel.py` in the real container, which also
exercises the vendored tree across the container boundary — so the re-verification the
change forced is also the container-level proof the change needed.

---

## 6. DECISION D3 — the budget ceiling moved, and the plan with it (12:36)

**level=decision.** The owner raised the key cap mid-session, which is exactly the case
D0's formula was built for.

```
2026-09-02T10:36:43Z   /api/v1/key      limit 20.0, usage 1.283724018, remaining 18.716
                       /api/v1/credits  210 - 168.336 -> $41.66 available
measured through the guard: CEILING $18.7289 additional  -> ~491 rollouts
```

No restart, no code change: `ceiling = min($20 authorized, limit − baseline)` picked it up
from the poll. `on_limit_change` announces it and appends a `key_cap_changed` decision to
`.evolve/geos_search/decisions.jsonl`.

**One change made on instruction:** the $0.25 reserve I had added is removed
(`KEY_RESERVE_USD = 0.0`). The key cap *is* the stop; carrying a second number of our own
beside it is the thing to avoid. Headroom against being refused mid-batch now comes only
from `batch_cost_usd` — derived as `parallelism × measured $/rollout`, not hardcoded —
which is the brief's own second clause.

### 6.1 Re-plan: wall-clock is now the binding constraint, not money

$18.73 at $0.0381/rollout is ~491 rollouts. At 12.6 min and 8-way, 491 rollouts is
**~12.9 h**. It is 10:38 UTC and the sync is tomorrow morning, so the wall-clock fits —
but only if arms are finished **one at a time**. Four half-finished arms is not a result.

| # | arm | rollouts | $ | wall @8 | cumulative wall |
|---|---|---|---|---|---|
| 2 | `baseline` — noise floor **re-measured on glm-5.3-flash** | 18 | $0.69 | 0.5 h | 0.5 h |
| 3 | `search --budget 3` | ~90 | $3.43 | 2.4 h | 2.9 h |
| 4 | `baselines` — compute-matched | ~90 | $3.43 | 2.4 h | 5.3 h |
| 5a | first ablation | ~90 | $3.43 | 2.4 h | 7.7 h |
| 5b | second ablation | ~90 | $3.43 | 2.4 h | 10.1 h |
| 5c | third ablation | ~90 | $3.43 | 2.4 h | 12.5 h |
| | **total** | **468** | **$17.8** | | |

Items 2–4 stay first and in order: an unmatched win is not a win, and item 4 is never
optional. The ablations are now budgeted in rather than treated as a stretch, and **which
one runs first is chosen from the search's own evidence**, not picked now — which is what
the brief asked for and is only possible in this order.

**Kill rule for the night (K4, revised):** stop *launching* new arms at 2026-09-03T04:00Z.
Whatever is complete at that point is the report; a partial arm is reported as
not-run rather than as a number.

### 6.2 Baseline pool: 6 tasks, not the pruned 4 — and why

`BUDGET_PLAN` §3.1 says drop the two noisiest tasks, which improves the MDE from 0.144 to
0.047 for a third fewer rollouts. That is the right call **and its σ inputs are
ox-alpha's**, measured on a model that no longer exists. §25.4 of the previous log states
the rule directly: *"per-task sigma is a property of model × task, not of the task."*

Pruning tonight's pool using last week's model's noise would be the same error as F1 in a
different place. So the baseline re-measures all **6 tasks × 3 seeds = 18 rollouts**
($0.69, 0.5 h) on `z-ai/glm-5.3-flash`, and the pruned pool for the search is chosen from
*that* σ. It is the cheapest arm in the programme and it is the one every later number
depends on.

---

## 7. CORRECTION to §6.1 — the clock, not the budget, sets the plan (10:40)

**CORRECTION.** §6.1 above planned six arms over ~12.9 h on the assumption of an
overnight window. That assumption is wrong, and the owner corrected it at 10:38:

> *"it is 03:38 PT right now, and the deliverable deadline is 09:00 PT / 16:00 UTC today,
> which is 5.4 hours … the ablations are in budget but probably NOT in time."*

Brief §7 (commit `07a607b`) now sets hard gates. Converted to UTC, which is the clock
every timestamp in this log uses:

| UTC | gate |
|---|---|
| **15:00** | stop launching new rollouts; let in-flight work drain |
| **15:30** | final free `report_geos.py` recompute |
| **16:00** | `REPORT.md` final and committed |

**Capacity arithmetic, at 10:42.** 4.3 h of launching × 8-way ÷ 12.6 min/rollout =
**~164 rollouts**, against the ~491 the raised cap would buy. The six-arm plan in §6.1 is
withdrawn. The committed plan is:

| arm | rollouts | why it is non-negotiable |
|---|---|---|
| `baseline` 6 tasks × 3 seeds | 18 | every later number is read against this σ |
| `search --budget N` | ~60 | the experiment |
| `baselines` compute-matched | ~60 | **an unmatched win is not a win**; never ship the search without it |
| **one** ablation, if and only if it fits whole | ~60 | chosen from the search's own evidence |

18 + 60 + 60 = 138, leaving ~26 rollouts of slack against a 164-rollout capacity. **The
ablation is therefore planned as not-fitting**, and will be run only if the search and
matched arms come in under their wall-clock. A partial arm is uninterpretable, not weaker,
so nothing is started that cannot finish before 15:00.

The search arm is deliberately left as `~60` rather than sized now: the honest input is the
*measured* seconds-per-rollout at 8-way on this model, which the baseline produces in the
next 40 minutes. Sizing it from the 12.6 min figure would be sizing it from a measurement
taken on a different model at a different concurrency.

---

## 8. R1 re-verified against the modified hook (10:38–10:39)

The receipt refusal in §5.5 was resolved by re-running the container-boundary verification.
**All 11 assertions PASS**, including the control arm:

```
$ cd /home/matt/projects/siga && REPO3_CONTAINER_BACKEND=enroot \
    python3 scripts/verify_r1_feedback_channel.py \
      --out /home/matt/projects/sci-sim-op/.evolve/r1_verification

- [PASS] parse:    both arms blocked (86 vs 264 chars)
- [PASS] validate: feedback text differs across shapes (86 vs 3038 chars)
- [PASS] control (forwards stripped): shapes collapse to identical (151 vs 151 chars)
- [PASS] validate: real geosx output reached the agent
```

Receipt: `/home/matt/projects/sci-sim-op/.evolve/r1_verification/receipt.json`
Arms + raw hook events: `/home/matt/projects/sci-sim-op/.evolve/r1_verification/arms.json`
Human-readable: `/home/matt/projects/sci-sim-op/.evolve/r1_verification/REPORT.md`

```
hook_sha256 279dc7f8ee4a742d9cfbfc1c139f084303b0e6bdd7253f2d4868bb74ac843b43
verified 2026-09-02T10:39:00+0000
validate_minimal=86ch / validate_structured_errors=1212ch / validate_errors_plus_tables=3038ch
```

The control arm is the part that makes this a measurement rather than an assertion: with
the two `--env` forwards stripped from the rendered container command, both feedback shapes
collapse to **151 identical characters**. The reward channel is carried by the forwarding,
and that is now re-established for the hook this campaign actually runs.

---

## 9. Baseline launched (10:42) — and F1's fix firing in production

```bash
cd /home/matt/projects/sci-sim-op
export REPO3_PATH=/home/matt/projects/siga HARNESS_EVOLVE_MODEL=z-ai/glm-5.3-flash \
       REPO3_CONTAINER_BACKEND=enroot PATH="$HOME/.local/bin:$PATH"
uv run python scripts/search_geos.py --stage baseline \
  --parallel 8 --seeds 1,2,3 --timeout 2400 \
  --task-list AdvancedExampleDruckerPrager,buckleyLeverettProblem,ExampleDPWellbore,\
ExampleIsothermalLeakyWell,ExampleMandel,TutorialSneddon \
  --out /home/matt/projects/sci-sim-op/.evolve/geos_search
```
Console log: `/home/matt/projects/sci-sim-op/../../tmp/claude-1009/baseline.log`
(absolute: `/tmp/claude-1009/baseline.log`). Corpus:
`/home/matt/projects/sci-sim-op/.evolve/geos_search/rollouts.jsonl`.

**Timeout is 2400 s, not the 1800 s default.** §22.3 of the previous log: a timeout does
not merely lower a score, it **disables the stop policy for that rollout** — the agent
never ends its turn, the Stop hook never fires, and a defect the `parse` check would have
caught becomes a hard 0.0000. `ExampleMandel` timed out on two of three seeds at 2400 s
under ox-alpha. Holding the timeout fixed and generous across every arm is a
precondition for the arms being comparable at all.

### 9.1 The startup banner, which is F1's fix working

```
account: $41.66 available of $210.00 credits
key:     usage $1.2837, limit 20.0, remaining $18.7163
ceiling: $18.7289 additional spend (min of $20.00 authorized and the key cap), ~491 rollouts

corpus: resuming from 51 recorded rollout(s) in .../rollouts.jsonl
corpus: 0 row(s) match model 'z-ai/glm-5.3-flash' and are replayable; 51 row(s) were
        recorded under stealth/ox-alpha and will NOT be replayed -- a rollout is a
        property of (candidate, task, seed, model), not of the first three
```

**This is the finding from §1 stated by the running system rather than by me.** Before the
fix, this run would have printed `18 rollout(s): 0 executed, 18 replayed from the corpus`,
cost $0.00, and handed the campaign another model's baseline. The line now says what it is
declining to do and why it costs money to decline it.

**Cost poll, 10:42:40Z:** `usage 1.283724018`, `limit 20.0`, `limit_remaining 18.716275982`,
ceiling `18.728929`, spent-this-campaign `$0.0127`. (The $0.0127 is the aborted 300 s smoke
rollout in §3.2 — a partial rollout that was killed by my own `timeout`, not by the guard.)
Every reading is appended to `/home/matt/projects/sci-sim-op/.evolve/provider_calls.jsonl`.
