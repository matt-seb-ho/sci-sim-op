# Qualification task for the prospective undergrad collaborator

**Written 2026-09-12.** Answers the four open questions, with the numbers they
turn on. The artifact is a separate repository:
[`../../geos-harness-qual/`](../../geos-harness-qual/) — starter kit, task
statement, seven tasks, container runner, scorer, budget guard.

Companions: [`2026-09-08_BUDGET_PLAN.md`](2026-09-08_BUDGET_PLAN.md) (unit
costs), [`SETUP_DELTA_vs_SIGA.md`](SETUP_DELTA_vs_SIGA.md) (why the research
setup is slow), [`STATUS.md`](STATUS.md).

---

## 1. How many hours to ask for

**15 hours of focused work, spread over ~3 weeks, with a hard stop at 18.**

The task is open-ended, so the cap is not an estimate — it is part of the
specification, and how someone behaves inside it is most of the signal. Fifteen
hours is deliberately *not enough* to do this comfortably; the student has to
decide what to drop, and that decision is assessable in a way that a completed
checklist is not.

| | hours |
|---|---:|
| read the kit, run the mock loop, choose a method, write the one-pager | 4 |
| implement the loop against the free mock runner | 6 |
| the real runs | 3 |
| write it up | 2 |

Getting from 20 to 15 meant cutting scope, not relabelling it. What came out:

- the report is **2–3 pages**, not 3–5;
- they get **one real search run, not two** — debugging happens on the free mock
  runner, which is stated as an instruction rather than left to discover;
- the search is sized at ~6 candidates rather than ~8, which also drops expected
  spend to ~$7.

`TASK.md` now carries an explicit **"if you are running out of time, cut in this
order"** section: fewer candidates first, then a shorter write-up (never a
skipped one), then report the train result with the test evaluation outstanding,
then — if the loop never worked — hand in the analysis of why. That last one is
genuinely acceptable and is labelled as such, because an undergrad who quietly
overruns to avoid submitting a failure is the failure mode a 15-hour cap
creates.

**The mandatory check-in at hour ~4** stays, and matters more at 15 hours than
at 20: it is after the one-pager and before any implementation. Two reasons, and
the second is the real one:

1. It stops a wrong plan from consuming the whole budget.
2. It is the cheapest assessment point we have. If the one-pager cannot say what
   the method assumes and whether those assumptions hold on a task with ~17
   training rollouts, a structural score and a 12-minute rollout, the rest of the
   work will not recover that — and we both learn it in week one rather than
   week three.

Three weeks of elapsed time for 15 hours of work is deliberate. A batch of eight
rollouts is ~35 minutes at three-way parallelism, so the work is inherently
bursty and a student with classes cannot compress it.

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

**$15, on a key with a hard per-key limit set to $15. Expect ~$7.**

This revises the $10 you suggested upward, and the reason is a measurement, not
caution. The smoke rollout billed **$0.134** — identical to the research
harness's figure despite halving wall-clock. At that price:

| | rollouts | cost |
|---|---:|---:|
| seed baseline, 4 train tasks × 2 seeds | 8 | $1.07 |
| search, ~6 candidates × 4 tasks × 1 seed | 24 | $3.22 |
| proposer LLM calls | — | ~$0.10 |
| re-running what breaks the first time | ~8 | $1.07 |
| champion + seed on 3 test tasks × 2 seeds | 12 | $1.61 |
| **total** | **~52** | **~$7.10** |

**Keep the ceiling at $15 even though the plan is ~$7.** The ceiling is a safety
limit, not a target, and the 15-hour version needs *more* slack per hour rather
than less: a student with three hours of run time has no room to absorb one
wasted afternoon. At $10 the margin is 29% and a single bad run eats it — and a
student who runs out mid-search loses the comparison entirely, because a
half-evaluated candidate cannot be compared with a fully evaluated one.

The levers if you do want to hold $10 are written into the task statement
anyway: evaluate candidates at one seed and re-run only finalists at two; kill a
candidate after two down tasks.

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

## 4. Repo or zip

**A private GitHub repo, and they submit a pull request.** The zip's only
advantage is saving them one `git clone`, and it costs four things that matter:

1. **The submission format is itself a signal.** A PR shows whether they commit
   incrementally or dump one 2,000-line blob at midnight, whether they can write
   a commit message, and whether they can keep their changes separable from the
   kit. None of that survives a zip, and all of it predicts what collaborating
   with them is like.
2. **You will patch the kit while they are working on it.** Something will be
   wrong — it always is. With a repo that is `git pull`; with a zip it is a
   second zip and a student silently working against a stale copy, which then
   contaminates their numbers in a way neither of you can see.
3. **The artifacts have to come back.** The ledger, the run log, the champion
   adapter, the write-up. A PR carries all of it with history attached; a
   returned zip carries a final state you cannot interrogate.
4. **It is the same workflow as actually contributing**, which is the thing the
   qualification task is trying to predict.

### Private is load-bearing, not caution

`tasks/` contains seven task specifications **paired with their reference
decks**. Publishing that publicly puts a benchmark's answer key on the open web,
where it gets scraped and lands in the next model's training data — and then the
benchmark measures recall rather than authoring, permanently, for us and for
anyone else using these tasks. The GEOS decks themselves are public (LGPL,
already on GitHub); it is the *pairing with the specifications and the split*
that must not be.

So: private repo, student added as a collaborator, they branch and open a PR
against it. If they would rather fork, the fork inherits the private visibility
— that is fine. Add a line to the invitation saying the contents are not to be
posted publicly, including in a portfolio.

### Concretely

```bash
gh repo create <org>/geos-harness-qual --private --source=. --push
gh api -X PUT repos/<org>/geos-harness-qual/collaborators/<student> -f permission=push
```

Then send them: the repo link, `TASK.md`, an OpenRouter key capped at $15, and
the date you want the one-pager by.

## What is still open

- **The student's key.** Create it with a $15 cap before sending the repo.
- **Where the repo lives.** See the section below — a **private** GitHub repo,
  and private is load-bearing.
- **Only `claude` is verified end to end.** The `acpx` harnesses have correct
  flags and a present binary but nobody has run one. The kit says so rather than
  implying otherwise; if a student picks one, budget an hour for auth.
- **The mock's gradient is vocabulary overlap.** It is documented as fake, but a
  student who optimises against it and never notices will produce a loop that
  does nothing on real rollouts. That is a deliberate trap and it is one of the
  more informative things the exercise can detect.
