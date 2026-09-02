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
