# Qualification task for the prospective undergrad collaborator

**Written 2026-09-12.** Answers the three open questions, with the numbers they
turn on. The artifact is a separate repository:
[`../../geos-harness-qual/`](../../geos-harness-qual/) — starter kit, task
statement, seven tasks, container runner, scorer, budget guard.

Companions: [`2026-09-08_BUDGET_PLAN.md`](2026-09-08_BUDGET_PLAN.md) (unit
costs), [`SETUP_DELTA_vs_SIGA.md`](SETUP_DELTA_vs_SIGA.md) (why the research
setup is slow), [`STATUS.md`](STATUS.md).

---

## 1. How many hours to ask for

**20 hours of focused work, spread over ~3 weeks, with a hard stop at 25.**

The task is open-ended, so the cap is not an estimate — it is part of the
specification, and how someone behaves inside it is most of the signal. A
submission that does 20 hours of well-scoped work and says clearly what it did
not get to is better evidence than 60 hours of sprawl, and the task statement
says so in those words.

The 20 divides roughly:

| | hours |
|---|---:|
| read the kit, run the mock loop, understand the scoring | 3 |
| choose a technique and write the one-page justification | 3 |
| implement the loop against the free mock runner | 8 |
| seed baseline + first real run + one debugging cycle | 4 |
| held-out evaluation and the write-up | 4* |

\* over-subscribed on purpose; the write-up is where people run out of time, and
they should be allowed to spend the slack there.

**There is a mandatory check-in at hour ~4**, after the one-pager and before any
implementation. Two reasons, and the second is the real one:

1. It stops a wrong plan from consuming the whole budget.
2. It is the cheapest assessment point we have. If the one-pager cannot say what
   the method assumes and whether those assumptions hold on a task with ~17
   training rollouts, a structural score, and a 12-minute rollout, the rest of
   the work will not recover that, and we both learn it in week one instead of
   week three.

Three weeks of elapsed time for 20 hours of work is deliberate. Rollouts are
slow (a batch of eight is ~35 minutes at three-way parallelism), so the work is
inherently bursty, and a student with classes cannot compress it.

## 2. Which simulator, and what the starter repo contains

### GEOS. Not close.

| | GEOS | OpenFOAM | LAMMPS |
|---|---|---|---|
| scoring | TreeSim against a reference deck, 0–1, deterministic, free | file-coverage only — `openfoam.py` is 268 lines and **declines to score contents** | **`score()` raises.** There is no cheap defensible metric; the agent already emits runnable scripts and what it gets wrong is *values* |
| tasks with ground truth | 46 | — | — |
| measured per-task difficulty | yes — 40-task screen, 80 rollouts, 2026-09-11 | no | no |
| a student could get a number in week one | yes | no | no |

The deciding fact is the middle row, and it is not a matter of polish: on LAMMPS
the honest metrics are behavioural, which means running `lmp`, which is the one
thing we have decided not to pay for. A qualification task whose first
requirement is inventing a metric is a different and much harder task.

### The snags you named are real, and the starter repo drops them rather than inheriting them

The post-SIGA problems in this repo — divergence from SIGA's setup, slow
evaluation — come from things the *research* programme needs and a qualification
task does not: a 4,462-file corpus, a RAG server, an xmllint MCP, a five-check
stop hook, a validation-gated GEOS binary. The starter kit keeps none of them.
What that bought, measured on the smoke rollout that validated the kit:

| | research harness | starter kit |
|---|---|---|
| corpus | 4,462 files / 435 MB | **842 files / 4.0 MB** (decks + docs + schema) |
| wall-clock per rollout | 1,453 s | **687 s** |
| tool calls per rollout | 59.7 | **64** (unchanged) |
| billed per rollout | $0.134 | **$0.134** (unchanged) |
| GEOS binary | mounted, validation-gated | **not mounted** |
| RAG / MCP / stop hook | all three | none |

Halving wall-clock did not move the bill — worth knowing, and it is why §3
below revises the money answer upward rather than down.

**Execution is out of the loop entirely**, which also restores parity with
SIGA's published arm. That is the setting our own measurements argue for: when
the simulator was reachable agents ran 7.3 solves per rollout for output nothing
scores, and gating it made things *worse* (attempts doubled, cost +59%, because
a refusal invites another variation). Not mounting it is the only version that
has ever been cheap.

### The base policy is a choice, not a constant

At your request the harness is a registry rather than a hardcoded `claude -p`.
`qual harnesses` probes the image and reports what it can run: Claude Code's own
CLI (verified), and `codex` / `pi` / `openclaw` / `claude` behind `acpx`, which
is already installed. One rule enforced in the docs: **pick one and keep it
fixed** — the harness is not a searchable component, and two candidates on
different harnesses are not comparable. Whether an adapter transfers across
harnesses is H6/H7 of the research programme and is flagged as a separate
experiment if they have budget left.

### Which tasks, and why seven

From the 40-task screen (80 rollouts, 2026-09-11):

- twelve tasks score a flat **1.000 at both seeds** — no headroom, so no
  candidate can beat the seed on them;
- `faultVerification` times out at both seeds; `TutorialHydraulicFractureWithAdvancedXML`
  sits at 0.016;
- six more produce a deck at one seed and nothing at the other.

The seven shipped are the ones with measured headroom *and* reproducible scores,
split by physics family so a family lives entirely in one split:

| split | family | task | screen |
|---|---|---|---|
| train | wellbore | ExampleVerticalPoroElastoPlasticWellbore | 0.53 / 0.52 |
| train | wellbore | AdvancedExamplePureThermalDiffusionWellbore | 0.34 / 0.35 |
| train | poroelastic | TutorialPoroelasticity | 0.49 / 0.42 |
| train | poroelastic | ExampleThermoporoelasticConsolidation | 0.87 / 0.61 |
| test | fracture | ExamplesingleFracCompression | 0.78 / 0.82 |
| test | fracture | kgdToughnessDominated | 0.86 / 0.87 |
| test | driver | triaxialDriverExample | 0.90 / 0.86 |

The kit re-measures the seed on its own configuration; the screen column is
shipped as a prior and labelled as one. (Sanity check: the smoke rollout scored
**0.526** on `TutorialPoroelasticity` against the screen's 0.49/0.42 — same band,
slightly better, consistent with the curated corpus.)

### What is in the repo

```
tasks/          7 specifications + their reference decks (never mounted)
adapter/seed/   the 5-line primer they must beat
src/qualkit/    tasks, adapter, agents, corpus, rollout, scoring,
                evaluate, ledger, mock, llm, cli    (~2,000 lines)
evolve/loop.py  THE STUB. The only file that is theirs.
tests/          53 tests, offline, a few seconds
TASK.md         the task statement
docs/CONTAMINATION.md
```

Three things in it are worth more than the code:

- **a free mock runner.** A deterministic offline fake agent with a learnable
  gradient, so the entire loop is built and debugged at zero cost and in
  seconds. It is documented as a toy — it rewards vocabulary overlap, which the
  real task does not — and noticing that gap is itself something we can assess.
- **the evaluation rules are enforced, not suggested.** Paired per-task
  comparison with a bootstrap interval; `compare()` refuses evaluations that do
  not cover the same cells; failures are zeros and stay in; harness errors are
  excluded *and counted*; the budget guard prices from the account, never the
  transcript; the ledger replays so a crash does not re-buy rollouts.
- **contamination is a mount-level property.** The corpus is built per task with
  that task's decks, their variant siblings (`_base` → `_smoke`, `_benchmark`)
  and the doc page the spec was mined from removed, by hardlink so nothing can be
  followed out. `qual audit` checks it.

**One thing found while building this, worth acting on in the research repo:**
the research harness leaves `WebSearch`/`WebFetch` enabled. Every GEOS example
deck is on GitHub, and the container has network — so the corpus filtering is
defeasible by an agent that thinks to fetch a URL. The starter kit disallows
both and pins it with a test. Whether any past rollout actually did this is
checkable from the transcripts and probably should be checked.

## 3. How much API spend to authorise

**$15, on a key with a hard per-key limit set to $15. Expect ~$8.**

This revises the $10 you suggested upward, and the reason is a measurement, not
caution. The smoke rollout billed **$0.134** — identical to the research
harness's figure despite halving wall-clock. At that price:

| | rollouts | cost |
|---|---:|---:|
| seed baseline, 4 train tasks × 2 seeds | 8 | $1.07 |
| search, ~8 candidates × 4 tasks × 1 seed | 32 | $4.29 |
| proposer LLM calls | — | ~$0.10 |
| re-running what breaks the first time | ~10 | $1.34 |
| champion + seed on 3 test tasks × 2 seeds | 12 | $1.61 |
| **total** | **~62** | **~$8.40** |

$10 would leave 16% headroom, which is not headroom — it is a budget that fails
on the first bad afternoon, and a student who runs out mid-search loses the
comparison entirely (a half-evaluated candidate cannot be compared with a fully
evaluated one). $15 leaves ~45%, and the task statement tells them that
approaching the ceiling means the loop is wrong rather than the budget.

Cheaper is available if you want to hold the line at $10: evaluate candidates at
one seed and only re-run finalists at two; kill a candidate after two down
tasks. Both are written into the task statement as the levers to reach for.

**Do not hand over a key with the research budget behind it.** OpenRouter
supports a per-key spend limit; set it. The kit's own guard is a second layer
that reads `/api/v1/credits` and refuses to start a rollout past the ceiling, but
the enforceable boundary should be at the key.

### The train/test sizing question you raised

Small train/test is not a budget compromise here — it is the right design. The
binding constraint is the *task pool*, not the money: only ~7 tasks have both
headroom and reproducibility, and they are 4 physics families. Four train tasks
at two seeds is eight rollouts per comparison, which is what makes a search of
eight candidates affordable at all. The honest consequence, stated in the task
statement: a paired interval at n=4 will usually span zero, and reporting that
plainly is the expected outcome rather than a failure.

### The cost lesson the kit teaches by accident

One rollout, priced three ways:

| source | says | |
|---|---:|---|
| token arithmetic over the transcript | $0.028 | 4.7× too low |
| the CLI's own `result.total_cost_usd` | $3.974 | 30× too high |
| **account balance, before and after** | **$0.134** | the bill |

Both wrong numbers have causes and neither is patchable — the token math cannot
see the resent conversation (this provider reported no cache-read tokens at
all), and the CLI prices at the list price of a model it only assumes it is
talking to. This is the same wall the August campaign hit from the other
direction, and it is now a documented constant in the kit with the guard reading
the account instead. Worth making the student meet it early; it is one of the
few things in this project that is genuinely counter-intuitive.

## What is still open

- **The student's key.** Create it with a $15 cap before sending the repo.
- **Where the repo lives.** It is a local git repo with one commit; it needs a
  remote they can be given access to.
- **Only `claude` is verified end to end.** The `acpx` harnesses have correct
  flags and a present binary but nobody has run one. The kit says so rather than
  implying otherwise; if a student picks one, budget an hour for auth.
- **The mock's gradient is vocabulary overlap.** It is documented as fake, but a
  student who optimises against it and never notices will produce a loop that
  does nothing on real rollouts. That is a deliberate trap and it is one of the
  more informative things the exercise can detect.
