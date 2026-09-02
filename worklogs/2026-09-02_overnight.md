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

---

## 10. **CORRECTION to §2 — the F2 fix had not actually landed** (10:45)

While sizing the search I read `scripts/search_geos.py:405` and found:

```
405:        backend=free_window_backend(),
```

**§2 above reports F2 as fixed. It was not.** The import of `campaign_backend` had
landed; the *call site* had not — my edit's anchor text contained a `§` that did not match
the file byte-for-byte, the replacement silently did nothing, and I checked the import with
`grep` rather than the call. Committed in `0581b58` in that state.

The irony is exact and worth recording rather than tidying away: **I asserted a fix instead
of measuring it**, in a log whose §2 is about a bug that would have made the search report
a plausible null. Had this shipped, the search would have run tonight on a dead proposer
model and returned its seed — the precise failure F2 describes — while this worklog said
it could not.

Fixed for real, and this time verified by *running it*, live, against the paid model:

```
$ campaign_backend(('z-ai/glm-5.3-flash',))(...)
routes: ['openrouter/z-ai/glm-5.3-flash']
reply:  'alive'
stats:  {'calls': 1, 'total_cost': 7.05e-06, 'unknown_cost_calls': 0}
```

Two things are established by that one call, neither of which a grep could have shown:

1. **The proposer reaches the campaign model.** F2 is closed.
2. **The budget policy change works.** Under the old rule — `usage.cost` must be zero —
   a `total_cost` of `7.05e-06` would have raised `BilledCallError` and permanently
   disabled the route on the first call. It did not.

### 10.1 A second hole closed while looking: the Nous failover

The roster built two routes, `openrouter/…` and `nous/…`. Spend is enforced against **this
OpenRouter account's** counter, so a failover onto Nous would bill a meter the guard cannot
see: the cap would hold on paper while money left by another door. `campaign_backend` is
now OpenRouter-only. It is also a validity point rather than only a cost one — one
provider is one independent variable.

**Standing lesson, again:** every defect in this campaign that mattered was found by
running something and reading what came out. Three of them now — R1, F1/F2, and this — and
the one I got wrong was the one I checked by reading.

---

## 11. PLAN for the remaining arms, written before running them (10:52)

Sizing arithmetic, so the choices below can be checked rather than taken on trust.

**The search is sequential in candidates.** Within a candidate, `run_many` fans out over
the thread pool; across candidates it cannot — each proposal depends on the previous
round's evidence. So the search's wall-clock is
`budget × (screen_wave + ceil(anchor×seeds / 8) waves) × ~13 min`, and 8-way parallelism
buys much less here than it does on a flat baseline batch. This is the constraint that
decides the configuration, and it is not money.

| config | rollouts | wall-clock | verdict |
|---|---|---|---|
| budget 4, anchor 4, seeds 1,2,3 | ~58 | ~2.6 h | too slow; would push the matched arm past 15:00 |
| budget 4, anchor 3, seeds 1,2 | ~32 | ~1.7 h | fits, but leaves no room for an ablation |
| **budget 3, anchor 3, seeds 1,2** | **~24** | **~1.3 h** | **chosen** — and it is the brief's own `--budget 3` |

**Committed sequence, with the clock:**

| # | arm | rollouts | expected window (UTC) |
|---|---|---|---|
| 1 | `baseline`, 6 tasks × 3 seeds | 18 | 10:42 → ~11:20 |
| 2 | re-cut slices on the pruned pool — **$0, replayed** | 0 | ~11:20 |
| 3 | `search --budget 3 --seeds 1,2` | ~24 | ~11:25 → ~12:45 |
| 4 | `baselines` compute-matched, k from the search ledger | ~24 | ~12:45 → ~13:25 |
| 5 | **one** ablation, chosen from the search's evidence | ~24 | ~13:30 → ~14:50 |
| — | stop launching | | **15:00** |
| — | final free recompute + report | | 15:30 → 16:00 |

Total ~90 rollouts ≈ **$3.43** against an $18.73 ceiling. **Money is not close to binding;
the 15:00 launch gate is.** Arm 5 is genuinely in reach at this sizing, which is why the
sequence is built around finishing arms rather than around spending the budget.

### 11.1 DECISION D5 — prune the pool by σ, but by *tonight's* σ

**level=decision.** `BUDGET_PLAN` §3.1 says drop the two noisiest tasks: a third fewer
rollouts and a 3× better MDE (0.144 → 0.047). That method is adopted unchanged. What is
*not* adopted is its inputs — those σ were measured on `stealth/ox-alpha`, and §25.4 of the
previous log states the rule: *per-task σ is a property of model × task*. Pruning tonight's
pool with last week's model's noise would be F1 again in a different place.

So the pruning waits for the 18-rollout baseline, and is then applied to **tonight's**
measured σ.

**How, with no code change and no cost:** re-run `--stage baseline` with the pruned
`--task-list`. Every rollout in it is already in the corpus, so it replays at **$0.00** and
rewrites `/home/matt/projects/sci-sim-op/.evolve/geos_search/slices.json` over the pruned
pool. The resume machinery earning its keep for the third time.

### 11.2 DECISION D6 — anchor 3 / probe 1, and why not the default heuristic's answer

**level=decision.** §24.3 of the previous log flagged that `build_slices` ranks candidate
anchor tasks by `in_play`, which *adds* across-seed spread as a positive term:

```python
return intermittent + self.spread + 0.5 * max(headroom, 0.0)
```

so it selects the **noisiest** tasks as "boundary" anchors — and those are exactly the
tasks where nothing a search does is detectable at n=3. The previous author called this
"directly at odds with detectability" and left two options: raise seeds substantially, or
weight slice selection by σ.

I am taking **neither** as a code change tonight, deliberately. Raising seeds does not fit
the clock; re-deriving `in_play` is a change to a core selection heuristic made under
deadline, with no time to test it properly, and the campaign already has enough novel
machinery in flight. Pruning the pool by σ *before* `build_slices` sees it achieves the
same end through the already-blessed `BUDGET_PLAN` §3.1 method: the noisy tasks are simply
not in the pool, so the heuristic cannot choose them.

Recorded as a limitation rather than solved: **`in_play` still rewards variance, and on a
pool that had not been pre-pruned it would still pick undetectable anchors.** That is a
real defect in the slice machinery and it is left standing, visibly, for someone with more
than four hours.

### 11.3 Pre-registered predictions for the arms about to run

Written now so they cannot be adjusted afterwards. (`docs/PROJECT_PRIMER.md` §7.)

| # | prediction |
|---|---|
| **P1** | The search returns its seed, or a candidate whose paired CI against the seed spans zero. (arXiv:2607.12227: harness evolution scores *below* its own seed, 67.4 vs 68.2.) |
| **P2** | Compute-matched best-of-k ≥ the search at matched budget. (Same paper: 72.3 vs 67.4.) |
| **P3** | The three vendored checks fire at a rate near zero on real decks; `required_sections` never fires on an under-generated deck, because it is a section-presence check and the sections are present. |
| **P4** | The zero rate on `glm-5.3-flash` is non-zero but small (ox-alpha: 0.056, n=18), and `ExampleMandel` supplies most of it via timeout. |
| **P5** | Per-task σ on `glm-5.3-flash` is heterogeneous by at least an order of magnitude, as it was on ox-alpha (0.0035 → 0.32). |

A confirmed P1+P2 is the pre-registered null, and it is a first-class result, not a
failure to find one.

---

## 12. D2 proven at the container boundary (10:50)

§5.2 proved the vendored checks fire through the hook *on the host*. The boundary is the
part that has burned this project before — R1 was precisely a policy that reached the host
and died at the container edge — so it is measured rather than assumed:

```bash
$ A=/home/matt/projects/sci-sim-op/.evolve/geos_search/rollouts/adapters/\
evolve-cand_d1c0f1f0f516-s1-TutorialSneddon
$ enroot start --mount "$A:/plugins/repo3" geos-eval python3 -c "
    import sys; sys.path.insert(0,'/plugins/repo3/vendor')
    from harness_evolve.checks import BUILTIN_CHECKS, run_checks
    from harness_evolve.simulators.base import SimulatorRegistry
    ..."

IN-CONTAINER import OK, python 3.12.3
checks: ['constraints', 'cross_section_refs', 'geosx_validate', 'parse', 'required_sections']
geos spec: ('Constitutive', 'ElementRegions', 'Events', 'Mesh')
```

That is the **real image**, the **real mount point** (`/plugins/repo3`), and an adapter
materialized by **this run's** runner — not a reconstruction. All five checks resolve and
the GEOS spec loads.

The live adapter also carries the policy that turns them on:

```
$ cat $A/stop_policy.env
GEOS_EVOLVE_CHECKS=parse,geosx_validate,required_sections,constraints,cross_section_refs
GEOS_EVOLVE_FEEDBACK_SHAPE=structured_errors
GEOS_HOOK_MAX_RETRIES=2
GEOS_HOOK_XMLLINT=1
$ ls $A/vendor/harness_evolve
checks  __init__.py  simulators  types.py
```

So the chain is complete and each link is measured: policy → forwarded env (R1 receipt) →
hook reads it → hook imports the vendored registry from the mount → checks run → findings
block. What remains unmeasured is only the *firing rate on real decks*, which is what the
campaign rollouts are for, and which P3 predicts will be near zero.

---

## 13. **CORRECTION to P3 — a vendored check fired on a real deck, and it is not the one anybody nominated** (11:00)

**level=finding.** First rollout of the campaign lands, and it falsifies my own
pre-registered prediction. Recording it immediately, before the rest of the wave, because
the prediction was written 8 minutes earlier and the temptation to soften it later is
exactly what §8 of the brief exists to prevent.

```
AdvancedExampleDruckerPrager   seed 2   0.9611   success
```
Artifacts: `/home/matt/projects/sci-sim-op/.evolve/geos_search/rollouts/claude_code_repo3_plugin_xmllint_all/evolve-cand_d1c0f1f0f516-s2-AdvancedExampleDruckerPrager/AdvancedExampleDruckerPrager/`

**P3 said:** *"the three vendored checks fire at a rate near zero on real decks;
`required_sections` never fires on an under-generated deck."* The second clause is
untested so far. **The first is wrong on the very first rollout.**

### 13.1 What actually happened, from the hook's own event log

Two stop-hook events, in order:

```json
{"timestamp": "2026-09-02T10:59:43.717Z", "decision": "block",
 "reason_category": "vendored_check", "retries_so_far": 1,
 "checks_unsupported": [],
 "checks_vendored_run": ["required_sections", "constraints", "cross_section_refs"],
 "checks_vendored_findings": [{
   "source": "cross_section_refs", "severity": "error", "location": "<tree>:dummy",
   "message": "materialList names 'dummy', which is not a <Constitutive> child.
               Defined: ['DruckerPrager', 'ExtendedDruckerPrager', 'ModifiedCamClay',
               'ViscoDruckerPrager', 'ViscoExtendedDruckerPrager', 'ViscoModifiedCamClay']"}]}

{"timestamp": "2026-09-02T11:00:16.548Z", "decision": "allow",
 "reason_category": "xml_clean", "checks_vendored_findings": []}
```

**33 seconds between them.** The agent had written `materialList="{ dummy }"` — a
placeholder it never went back and filled in. The check named the offending value, named
the six legal alternatives, and blocked the turn. The agent fixed it and the deck came
back clean.

**That is the closed loop working, end to end, on a real task**: static gate → structured
feedback → agent repair → clean exit. It is the first time in this project that a
sci-sim-op check has done that inside a container.

### 13.2 Why this matters more than "a check fired"

**`geosx --validate-input` did not catch it.** `geosx_validate` was in the active check
list and ran first; the deck passed it. The hook's own feedback text says why, and it was
written before anyone had seen this happen:

> *"this catches everything resolved while GEOS loads the deck (including unknown
> tags/attributes and most cross-references), but **NOT** a name reference a solver only
> resolves during an actual solve step … those can still slip through."*

`materialList` is exactly that: a name resolved at solve time, not at load time. So
`cross_section_refs` is not redundant with the simulator's own validator — **it covers a
gap in it**, and the gap is a class of defect (dangling name references) that produces a
deck which loads fine and computes the wrong thing.

### 13.3 A correction to the previous session's correction

The 2026-08-26 log went back and forth on this and both of its positions were wrong in the
same direction — both were about `required_sections`:

| | claim | status |
|---|---|---|
| §14.5, §16.3, §17 | *vendor `checks/`, because `required_sections` detects TutorialSneddon's 221 missing elements* | falsified by that author in §21 — it is a section-*presence* check and all 11 sections are present |
| §21 | *therefore vendoring is **not** the top follow-up; it would fix nothing measured* | **falsified here** — vendoring fixed something measured, on the first rollout |

Both sessions, mine included, argued about the wrong check. §21's falsification was correct
about `required_sections` and then **generalized from one check to the whole registry**,
which is the step that did not hold. `cross_section_refs` was in `BUILTIN_CHECKS` the whole
time and neither analysis examined it.

**The recurring shape, now at three levels:** a plausible claim about a mechanism that
nobody ran. R1 was a knob nothing read; §21 was a fix nobody had run; §13 here is a check
nobody had tried. The instrument that mattered was the one not being discussed.

### 13.4 What is *not* established by this

- **n=1.** One rollout, one task, one seed. The firing *rate* is unknown until the arm
  finishes; P3's quantitative claim is not yet settled either way, only its "near zero"
  framing is in trouble.
- **No causal claim about the score.** 0.9611 vs ox-alpha's 0.9060 mean on this task is
  across models and across n; it is not evidence the check raised the score.
- **`required_sections` and `constraints` still fired nothing here**, consistent with the
  rest of P3.
- Whether this changes anything the *search* can do is a separate question: `checks` is
  **not in the search space** (§26 of the previous log), so this is a better constant, not
  a better search.

---

## 14. Baseline in flight — two things worth recording as they land (11:13)

```
AdvancedExampleDruckerPrager  seed 1   0.9611  success
AdvancedExampleDruckerPrager  seed 2   0.9611  success
TutorialSneddon               seed 1   0.0772  success
ExampleMandel                 seed 2   0.0000  harness_error
```

### 14.1 A provider-side failure, correctly not counted as a model failure

```
$ .../evolve-cand_d1c0f1f0f516-s2-ExampleMandel/ExampleMandel/status.json
elapsed 360.6   exit 1
latest_agent_response: "API Error: Upstream idle timeout exceeded"
inputs/  empty     outputs/  empty
```

**This is OpenRouter, not the harness and not the vendoring.** The rollout produced no
deck at all, and the corpus records it as `harness_error` with value 0.0000 — which
`report_geos.py` excludes from every average. That is the §5.3/§8.3/§25.1 machinery from
the previous session doing exactly its job: without it this enters the corpus as a 0.0 and
drags `ExampleMandel`'s mean down by a third, on the task that already carries the pool's
only catastrophic failures.

Watching the rate rather than reacting to n=1. At 1-in-4 it would cost real capacity; the
arm will say. **It also costs 6 minutes of wall-clock for nothing**, which under a 15:00
launch gate is the more expensive half.

### 14.2 An identical score on two different seeds

`AdvancedExampleDruckerPrager` returned **0.9611 on both seed 1 and seed 2** — two
separately executed rollouts (both printed as they landed, both written to the corpus as
`executed`, distinct `artifacts_dir`). Not a replay: F1's fix is exactly what would have
made this suspicious, and it is not that.

The scorer is a structural tree similarity against the reference deck, so two runs that
converge on the same deck structure score identically. Recorded now because **σ = 0.0000
for this task so far, against ox-alpha's σ = 0.0815** — if that holds through seed 3 it is
a real difference between the models in run-to-run stability, and it is the kind of thing
that would otherwise be noticed only after being used.

---

## 15. BASELINE COMPLETE — and two more fabricated-number defects it exposed (12:20–12:35)

```bash
$ uv run python scripts/search_geos.py --stage baseline --parallel 8 --seeds 1,2,3 \
    --timeout 2400 --task-list <the 6> \
    --out /home/matt/projects/sci-sim-op/.evolve/geos_search
18 rollout(s): 18 executed        elapsed 10:42 -> 12:20 (98 min)
```

### 15.1 F7 — a timed-out rollout is scored before its workspace has finished copying

Two of the eighteen came back `empty_workspace`, value **0.0000**. Both had timed out.
Neither workspace was empty:

```
$ ls .../evolve-cand_d1c0f1f0f516-s3-buckleyLeverettProblem/buckleyLeverettProblem/inputs
buckleyLeverett_base.xml   buckleyLeverett_benchmark.xml   inputFiles/
saturationHistory.hdf5     src/   vtkOutput/   vtkOutput.pvd          <- 14 files
$ .../s3-AdvancedExampleDruckerPrager/.../status.json
elapsed 2366.3   88 assistant turns   "Let me measure the slopes directly from ..."
```

Re-scored offline from the **same directory**, minutes later:

```
AdvancedExampleDruckerPrager  seed 3   empty_workspace 0.0000  ->  success 0.8250   CHANGED
buckleyLeverettProblem        seed 3   empty_workspace 0.0000  ->  empty_workspace  unchanged
```

**The harness copies the agent's workspace out of the container when the run ends, and
killing a run on timeout catches that copy in progress.** So the score is computed against
a directory that is still filling. A 0.8250 was recorded as a 0.0000.

This is the worst shape available: not a crash, a *plausible number*, landing on the
**zero rate** — the single tail quantity the whole reliability argument of this project is
about. And it does not stop at the number: `build_slices` reads spread and zero-rate to
choose anchors, so the first slice plan came back with

```
buckleyLeverettProblem       [boundary] in play: mean 0.59, spread 0.42, zero rate 33%
AdvancedExampleDruckerPrager [boundary] in play: mean 0.64, spread 0.45, zero rate 33%
```

— i.e. **the two fabricated zeros nominated their own tasks as the search's anchors.**

**Fixed** in `SubprocessRunner`: `settle_and_score()` re-checks an empty workspace for up
to `settle_timeout_s` (45 s, configurable, 0 disables) — but *only after a timeout kill*,
since a launcher that exited on its own has finished writing. Three tests: a late arrival
is picked up, a genuinely empty workspace still scores zero, and a clean exit is never
waited on.

**Corrected the corpus** rather than only the code, with `scripts/rescore_corpus.py`
(re-scoring from artifacts is free and is exactly what the recording corpus exists for).
Originals are preserved: the corrected row carries `rescored_from`, and
`/home/matt/projects/sci-sim-op/.evolve/geos_search/rollouts.jsonl.pre-rescore.bak` holds
the file as recorded.

### 15.2 F7b — and `empty_workspace` is the wrong name for the other one

`buckleyLeverettProblem` seed 3 still scores 0.0000 with 14 files present, and the cause is
different and genuine:

```
FileNotFoundError: .../inputs/inputFiles/compositionalMultiphaseFlow/benchmarks/
                   buckleyLeverettProblem/buckleyLeverett_base.xml
GEN xml at top level: ['buckleyLeverett_base.xml', 'buckleyLeverett_benchmark.xml']
```

The agent wrote a complete deck to `inputs/` — which is literally what its PRIMER tells it
to do — while the scorer requires the deck at the **ground-truth-relative** subpath. The
other two seeds of the same task got it right, so this is a real and recurring model
failure. But **the status says the workspace was empty, and it was not**: a reader takes
`empty_workspace` to mean the agent produced nothing, when it produced a complete deck in
the wrong place. Left as-is rather than renamed — changing the scorer mid-campaign changes
the dependent variable — and reported.

### 15.3 F8 — infrastructure failure *is* counted as model failure, inside selection

Found by reading the search's own first output, which replayed the seed's anchor:

```
ExampleMandel                0.3414 success
ExampleMandel                0.0000 harness_error   [HARNESS ERROR]
```

`report_geos.py` has excluded `harness_error` from reported means since 2026-08-26.
**`Search._evaluate` did not.** It averaged `r.score.value` over every rollout, and a
harness error carries a placeholder `0.0`:

```python
by_task.setdefault(r.task, []).append(r.score.value)   # every rollout, no filter
```

So the seed's `ExampleMandel` score was **0.1707 instead of 0.3414** — halved by an
OpenRouter timeout. Every child would then be compared against an artificially weakened
seed. **That manufactures an improvement in a campaign pre-registered to expect a null**,
which is the most expensive direction for an error here to point.

The previous session fixed the *reporting* path and left the *selection* path; the two
looked like one thing. Fixed: harness errors are excluded from selection, the exclusions
are reported in the run's own summary, and an evaluation where *everything* failed now
raises rather than recording a candidate worth 0.0 — an outage is not a bad candidate.
Three tests.

**The search was killed and relaunched with the fix**, at 12:32. It had run for four
minutes and executed no new rollouts (the seed's anchor was replayed), so this cost
nothing but the time.

### 15.4 The corrected baseline

```bash
$ uv run python scripts/report_geos.py --out .../geos_search --model z-ai/glm-5.3-flash
18 rollouts (17 scored, 1 harness error excluded)

== cand_d1c0f1f0f516  model=z-ai/glm-5.3-flash  n=17
   mean 0.5919   zero rate 0.059   min 0.0000   max 0.9799
     ExampleIsothermalLeakyWell    0.9477 +/- 0.0524   n=3
     AdvancedExampleDruckerPrager  0.9157 +/- 0.0786   n=3
     buckleyLeverettProblem        0.5855 +/- 0.5170   n=3
     ExampleDPWellbore             0.5017 +/- 0.3603   n=3
     ExampleMandel                 0.3355 +/- 0.0084   n=2
     TutorialSneddon               0.1798 +/- 0.1649   n=3
   statuses: {'success': 16, 'empty_workspace': 1}
```

### 15.5 D5 vindicated: pruning on last week's model's σ would have picked the worst task

```
                              ox-alpha σ      glm-5.3-flash σ
buckleyLeverettProblem          0.0035    ->     0.5170      quietest -> NOISIEST
ExampleIsothermalLeakyWell      0.0054    ->     0.0524
TutorialSneddon                 0.0105    ->     0.1649
AdvancedExampleDruckerPrager    0.0815    ->     0.0786
ExampleMandel                   0.1870    ->     0.0084  (n=2)
ExampleDPWellbore               0.3192    ->     0.3603
```

**`buckleyLeverettProblem` goes from the quietest task in the pool to the noisiest.** Had
the pool been pruned using `BUDGET_PLAN` §3.1's stored σ — as the brief's §4 stage 2
literally instructs — the single noisiest task on tonight's model would have been retained
as an anchor, and the two dropped would have been the wrong two. That is F1's error in a
different place, and it is why D5 waited for the measurement.

**Minimum detectable effect, tonight's model, 3 seeds:**

| pool | one arm | arm vs arm |
|---|---|---|
| all 6 tasks | 0.1241 | 0.1756 |
| drop 1 noisiest | 0.0922 | 0.1304 |
| **drop 2 noisiest (the pool used)** | **0.0538** | **0.0761** |

For comparison the same computation on ox-alpha gave **0.0330** arm-vs-arm. **This model
is roughly 2.3× noisier on the same tasks**, so tonight's search has to clear a much higher
bar to say anything — and that is a fact about the measurement, established before the
search ran, not an excuse produced afterwards.

Pruned pool (`/home/matt/projects/sci-sim-op/.evolve/geos_search/pool.json`):
`ExampleMandel, ExampleIsothermalLeakyWell, AdvancedExampleDruckerPrager, TutorialSneddon`.
Slices re-cut over it for **$0.00** — `12 rollout(s): 0 executed, 12 replayed from the
corpus`. Anchor: `ExampleMandel`, `ExampleIsothermalLeakyWell`,
`AdvancedExampleDruckerPrager`. Probe: `TutorialSneddon`.

### 15.6 Cost: the budget plan's $/rollout is a large underestimate

| reading (UTC) | key usage | spent this campaign |
|---|---|---|
| 10:42 baseline launch | $1.2837 | $0.0127 |
| 12:20 baseline end | $2.2805 | $1.0094 |
| 12:28 search launch | **$4.7682** | **$3.4971** |

The 18-rollout baseline cost **~$3.50, i.e. ~$0.194/rollout — 5× the $0.0381** in
`docs/2026-08-26_BUDGET_PLAN.md` §2. (Usage settles with a lag, so the 12:20 figure was
still landing at 12:28.) The plan's figure came from a two-task cost probe; these tasks run
to the 2400 s timeout with far more turns. **The programme estimate of $21 for 560 rollouts
should be read as ≈$109.** Money still is not tonight's binding constraint — $15.23 remains,
~78 rollouts at the measured rate — but the number in the funding document is wrong by 5×
and that matters more than tonight's arithmetic.
