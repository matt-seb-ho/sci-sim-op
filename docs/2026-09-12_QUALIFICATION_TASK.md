# Qualification task for the prospective undergrad collaborator

**Written 2026-09-12.** Answers the four open questions, with the numbers they
turn on. The artifact is a separate repository —
[`matt-seb-ho/geos-harness-qual`](https://github.com/matt-seb-ho/geos-harness-qual),
checked out at [`../../geos-harness-qual/`](../../geos-harness-qual/) — holding
the starter kit, the task statement, seven tasks, the container runner, the
scorer and the budget guard.

Companions: [`2026-09-08_BUDGET_PLAN.md`](2026-09-08_BUDGET_PLAN.md) (unit
costs), [`SETUP_DELTA_vs_SIGA.md`](SETUP_DELTA_vs_SIGA.md) (why the research
setup is slow), [`STATUS.md`](STATUS.md).

> **Read [`2026-09-12_CONTAMINATION_git-history.md`](2026-09-12_CONTAMINATION_git-history.md)
> first if you read nothing else here.** Building this kit turned up a
> benchmark-invalidating leak in the research harness: `/geos_lib` is a copy of a
> git checkout, `.git` included, so every deliberately-removed deck is one
> `git show` away. 59 of 80 screen rollouts ran git against the mount; 29 of 40
> tasks got their own blocked deck back. It is very likely why twelve tasks
> "scored 1.000 at both seeds".

---

## 1. How many hours to ask for

**15 hours of work, spread over ~3 weeks, with a hard stop at 18.**

The task is open-ended, so the cap is not an estimate — it is part of the
specification, and how someone behaves inside it is most of the signal. Fifteen
hours is deliberately *not enough* to do this comfortably; the student has to
decide what to drop, and that decision is assessable in a way that a completed
checklist is not.

**No per-step hour estimates are given.** An earlier draft budgeted each phase
and that was a mistake: it converts an open-ended research task into a schedule,
which both rewards the wrong behaviour (working to the estimate) and is wrong
anyway, since where the time goes depends entirely on which method they pick.
What `TASK.md` gives instead is a total, an ordering, and an explicit **"if you
are running out of time, cut in this order"**: fewer candidates first, then a
shorter note (never a skipped one), then report the train result with the test
evaluation openly outstanding, then — if the loop never worked — hand in the
analysis of why. That last one is acceptable and is labelled as such, because a
student who quietly overruns rather than submit a failure is the failure mode a
tight cap creates.

**The mandatory check-in after the one-pager** stays, and matters more at 15
hours than at 20: it is after the method justification and before any
implementation. Two reasons, and the second is the real one:

1. It stops a wrong plan from consuming the whole budget.
2. It is the cheapest assessment point we have. If the one-pager cannot say what
   the method assumes and whether those assumptions hold on a task with ~17
   training rollouts, a structural score and a 12-minute rollout, the rest of the
   work will not recover that — and we both learn it in week one rather than
   week three.

**The write-up is deliberately de-emphasised.** It is about a page, bullet
points are fine, and the assessment ordering in `TASK.md` puts it fifth of six —
below judgement about what to measure, honesty of the numbers, the reasoning in
the one-pager, and code quality. The artifacts that matter are produced by the
kit anyway: the ledger, the decision log, the champion configuration. The note
exists to say which direction they were optimising and what they believe, not to
be a paper.

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

### Masking: SIGA's policy exactly, plus a measurement it never had

The GEOS benchmark is built *from* the example collection the agent is allowed
to read, so masking is load-bearing. The kit now runs SIGA's rule, via the
vendored `treesim.variant_stem_keys`:

- lowercase the stem and strip nine variant suffixes **transitively to a
  fixpoint** — `_base_iterative`, `_base_direct`, `_iterative_base`,
  `_direct_base`, `_iterative`, `_direct`, `_benchmark`, `_smoke`, `_base`;
- drop keys under **10 characters** or in `{base, benchmark, input, inputs,
  problem, model, smoke}`, without which `base.xml` blanks the corpus;
- block every file in the tree whose keys intersect the blocked set;
- block the documentation page the spec was mined from, via `example_pairs.jsonl`
  and SIGA's own label regex.

Two widenings, both already in the research repo rather than inventions: `.geos`
dependency files count as leaky alongside `.xml`, and the variant scan covers
the whole source tree rather than `inputFiles/` alone. The effect is visible —
`TutorialPoroelasticity` now also blocks `_base_iterative`, and
`triaxialDriverExample` its three `.geos` tables.

**This matters more than it sounds: several specifications name their own
reference files.** `TutorialPoroelasticity` ends by pointing at
`inputFiles/poromechanics/PoroElastic_Terzaghi_base_direct.xml`. It is gone, and
so is `_base_iterative`, which the spec never mentions and which is not in the
ground-truth directory either.

### The part a filename rule cannot settle, and the task it cost us

Name masking removes the answer and its variants. It does not remove a
*different* example that shares a skeleton — and it must not, because reading a
comparable example is the intended workflow. So where that line falls is now
measured rather than argued. `qual audit --deep` scores every deck still
readable in a task's corpus against that task's reference:

| task | copy ceiling | seed agent |
|---|---:|---|
| ExampleSPE11b | 0.432 | 0.51 / 0.51 |
| TutorialPoroelasticity | 0.509 | 0.49 / 0.42 |
| AdvancedExamplePureThermalDiffusionWellbore | 0.580 | 0.34 / 0.35 |
| ExamplesingleFracCompression | 0.591 | 0.78 / 0.82 |
| kgdToughnessDominated | 0.591 | 0.86 / 0.87 |
| ExampleVerticalPoroElastoPlasticWellbore | 0.615 | 0.53 / 0.52 |
| triaxialDriverExample | 0.776 | 0.90 / 0.86 |
| ~~ExampleThermoporoelasticConsolidation~~ | **0.856** | 0.87 / 0.61 |

**One task failed this and is gone.** `ExampleThermoporoelasticConsolidation`
had a copy ceiling of 0.856 via `ThermoPoroPlastic_consolidation_base.xml` — a
*plastic* variant of the same problem, which no suffix rule reduces to the
answer's stem. Copying it scored as well as doing the task, so a loop could have
won on it by learning to plagiarise. Replaced by `ExampleSPE11b`: ceiling 0.432,
seed 0.51/0.51, and the flow family, which keeps test structurally distant from
train. Threshold for "degenerate" is 0.80, sitting between the task that failed
(0.856) and the highest survivor (0.776).

**The finding worth carrying back to the research repo:** on three of the four
training tasks the copy ceiling is *above* what the seed harness scores.
Retrieval alone beats our seed agent. That is not a contamination failure —
nothing here is close to 1.0, so authoring still does most of the work — but it
does mean a chunk of what we have been calling agent performance is reachable by
finding the nearest example, and we have never measured that on the full
46-task pool. It is roughly an afternoon of free compute to do so, and it would
change how the seed baseline should be read.

### Which tasks, and why seven

From the 40-task screen (80 rollouts, 2026-09-11) plus the ceiling test:

- twelve tasks score a flat **1.000 at both seeds** — no headroom, so no
  candidate can beat the seed on them;
- `faultVerification` times out at both seeds; `TutorialHydraulicFractureWithAdvancedXML`
  sits at 0.016;
- six more produce a deck at one seed and nothing at the other;
- one more is degenerate on the copy ceiling (above).

The seven shipped have measured headroom, reproducible scores, and a ceiling low
enough that the headroom has to be earned. Split by family, so a family lives
entirely in one split:

| split | family | task | screen | ceiling |
|---|---|---|---|---|
| train | wellbore | ExampleVerticalPoroElastoPlasticWellbore | 0.53 / 0.52 | 0.62 |
| train | wellbore | AdvancedExamplePureThermalDiffusionWellbore | 0.34 / 0.35 | 0.58 |
| train | poroelastic | TutorialPoroelasticity | 0.49 / 0.42 | 0.51 |
| train | flow | ExampleSPE11b | 0.51 / 0.51 | 0.43 |
| test | fracture | ExamplesingleFracCompression | 0.78 / 0.82 | 0.59 |
| test | fracture | kgdToughnessDominated | 0.86 / 0.87 | 0.59 |
| test | driver | triaxialDriverExample | 0.90 / 0.86 | 0.78 |

The kit re-measures the seed on its own configuration; the screen column ships
as a prior and is labelled as one. (Sanity check: two real rollouts scored
**0.526** and **0.410** on `TutorialPoroelasticity` against the screen's
0.49/0.42 — same band.)

### The search space is the harness, not an "adapter"

The first version of the kit handed the student a four-field `Adapter` (primer,
cheatsheet, constraints, stop policy) with token budgets on each. That was
wrong, and it is now a `HarnessConfig` covering **everything about the harness
except the model**:

| | |
|---|---|
| `system_prompt` | appended to the agent's system prompt |
| `tools` / `disallowed_tools` | which tools exist, which are withheld |
| `files` | anything, mounted read-only at `/harness` — hook scripts, MCP servers, a cheatsheet read on demand, notes the loop accumulates |
| `workspace_files` | files in `/workspace` before the run: `CLAUDE.md`, a checklist |
| `settings` | the harness's settings JSON. **Hooks live here** |
| `mcp_servers` | new tools |
| `max_turns`, `env`, `extra_argv` | context budget, environment, any CLI flag |
| `retry` | host-side shell checks against the finished workspace, plus what the agent is told on failure |

**The token budgets are gone entirely.** They were the wrong instinct: a
configuration that wins on score while tripling cost is not obviously worse than
one that does neither — it depends what is being optimised. So the kit measures
what a budget was protecting instead. `EvalResult` now reports **three outcomes
side by side** and `compare()` gives the delta on all three:

```
cfg_1ecba84903ef  score 0.7312  zero-rate 0.00  687s and 64 tool calls per rollout  n=8

cfg_1ecba… vs cfg_13c3…: paired score +0.2197, 95% CI [+0.1295, +0.3019], n=4 tasks
    reliability  zero-rate +0.000
    efficiency   +0s and +13.0 tool calls per rollout
```

`TASK.md` asks them to name which direction they are optimising *before* they
run, then report what actually moved. Performance, reliability and efficiency
are all legitimate targets and the task says so.

Five things remain fixed, and they are framed as validity constraints rather
than design taste: the model; no subagent tools (a rollout nominally on one
model once spawned a subagent on a stronger one that took 85% of the bill); no
web tools; the task prompt; the scorer. `HarnessConfig.validate()` enforces the
first three and raises before anything is spent.

### What the container actually provides

You asked specifically. Answers, all verified in the image today:

| | |
|---|---|
| **GEOS example decks** | yes — ~743 `.xml` under `/geos_lib/inputFiles/` |
| **GEOS documentation** | yes — ~98 `.rst` under `/geos_lib/docs/` (user guide, tutorials, basic and advanced examples) |
| **GEOS XML schema** | yes — `/geos_lib/schema/schema.xsd` |
| **GEOS C++ source** | no. Curated out; it is 1,539 files the agent can spend turns reading |
| **`xmllint` binary** | yes, in the image |
| **`xmllint` MCP wrapper** | no. The binary is there, the tool wrapper is not |
| **RAG / vector DB** | no. The corpus is 4 MB, so `Grep`/`Glob` reach all of it |
| **`geosx` binary** | no, deliberately — see above |
| **ground truth** | never mounted |

The load-bearing one: **schema validation works today and nothing uses it.**

```
$ xmllint --noout --schema /geos_lib/schema/schema.xsd bad.xml
bad.xml:2: element NotARealSolver: Schemas validity error : Element
'NotARealSolver': This element is not expected. Expected is one of (
AcousticDG, AcousticElasticSEM, AcousticFirstOrderSEM, AcousticSEM,
AcousticVTISEM, CompositionalMultiphaseFVM, ... )
```

That is the "correct action space at the point of failure" signal
`evidence/directives.py` exists to mine in the research repo — free, in the
container, and unwired. Whether the student finds it, and what they do with it
(prompt instruction? `Stop` hook? MCP tool? retry check?), is one of the more
informative things the exercise can surface.

### What is in the repo

```
tasks/          7 specifications + their reference decks (never mounted)
harness/seed/   the starting configuration: a 5-line prompt, default tools,
                one attempt, no hooks, no extra tools
src/qualkit/    tasks, config, agents, corpus, rollout, scoring, evaluate,
                ledger, mock, llm, cli      (~3,500 lines, 840 of them the
                vendored scorer)
evolve/loop.py  THE STUB. The only file that is theirs.
tests/          64 tests, offline, a few seconds
TASK.md         the task statement
docs/CONTAMINATION.md
```

Three things in it are worth more than the code:

- **a free mock runner.** A deterministic offline fake agent with a learnable
  gradient, so the loop is built and debugged at zero cost and in seconds. It is
  documented as a toy — it rewards vocabulary overlap and retries, and is
  **blind to tools, hooks, MCP and turn caps**. That last point is now stated
  loudly: a student whose method works through one of those gets nothing from
  the mock, and noticing that is itself assessable.
- **the evaluation rules are enforced, not suggested.** Paired per-task
  comparison with a bootstrap interval; `compare()` refuses evaluations that do
  not cover the same cells; failures are zeros and stay in; infrastructure
  errors are excluded *and counted*; the budget guard prices from the account,
  never the transcript; the ledger replays so a crash does not re-buy rollouts.
- **contamination is a mount-level property.** The corpus is built per task with
  that task's decks, their variant siblings (`_base` → `_smoke`, `_benchmark`)
  and the doc page the spec was mined from removed, by hardlink so nothing can
  be followed out. `qual audit` checks it.

**Two things found while building this, both worth acting on in the research
repo.**

*The corpus mount carries git history* — the big one, written up separately in
[`2026-09-12_CONTAMINATION_git-history.md`](2026-09-12_CONTAMINATION_git-history.md).
This kit was immune by construction because it assembles its corpus from an
include list rather than filtering a checkout; that is now stated as the design
rule and pinned by a test.

*`WebSearch`/`WebFetch` are enabled in the research harness.* Every GEOS example
deck is on GitHub and the container has network, so the corpus filtering is
defeasible by an agent that thinks to fetch a URL. The kit forbids both at the
validity floor. Whether any past rollout did it is checkable from the
transcripts — and now easy to check, with `qual inspect`.

## 3. How much API spend to ask for

**A couple of dollars, on their key, and say explicitly that spending more is
not a better submission.**

This has moved twice. It started at your $10, went to $15 on a cost
measurement, and has now come back down because the constraint changed: the
money is the student's, and — your steer, and it is the right one — what we
actually want to see is how they think and test, not how much compute they can
burn. Depth on a small set is the better shape anyway.

A rollout is **$0.11–0.13** billed and 11–13 minutes, measured against account
deltas on this kit. Two shapes are written into `TASK.md`, both labelled as
complete submissions:

| shape | rollouts | cost |
|---|---:|---:|
| **frugal**: 2 train tasks × 1 seed, 4 candidates, 2 test tasks | ~14 | **~$1.80** |
| standard: 4 train × 1 seed, 6 candidates, 3 test × 2 seeds | ~44 | ~$5.70 |

The default `--budget` ceiling is now $5. The kit's `BudgetGuard` still refuses
to start a rollout past the ceiling and still prices from the account rather
than the transcript, but the enforceable boundary is the per-key limit on their
own OpenRouter key, and `TASK.md` tells them to set one.

### What the task now optimises for

Following your steer, `TASK.md` leads with **"What we are actually looking
for"** before it says anything about method or budget, and the assessment order
is:

1. **How you find things out** — did you read the transcripts, the decks, the
   logs; are your decisions traceable to something you observed;
2. judgement about what to measure;
3. honesty of the numbers;
4. the reasoning in the one-pager;
5. code quality;
6. the write-up as a vehicle for the above;
7. whether the number went up — least important.

It also says plainly that four rollouts read line by line teach more than forty
skimmed, and the first thing to cut under pressure is tasks and candidates, not
reading.

To make that reachable rather than exhortation, the kit gained **`qual inspect
<workspace>`**: tool mix, the call-by-call trace with the salient argument of
each call, which parts of the corpus were actually opened, and the deck produced
with its weakest sections named. It is described in `TASK.md` as the most useful
command in the kit, and it was built and verified against real transcripts from
the 2026-09-11 screen.

### The train/test sizing question you raised

Small train/test is not a budget compromise — it is the right design. The
binding constraint is the *task pool*: only seven tasks have headroom,
reproducibility and a low enough copy ceiling, and they are five physics
families. The honest consequence, stated in the task statement: a paired
interval at n=2–4 will usually span zero, and reporting that plainly is the
expected outcome rather than a failure.

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
talking to. Same wall the August campaign hit from the other direction. It is
now a documented constant in the kit, with the guard reading the account
instead.

## 4. Repo, and who pays

**A public GitHub repo at
[`matt-seb-ho/geos-harness-qual`](https://github.com/matt-seb-ho/geos-harness-qual),
student submits a pull request.** Not a zip: the PR is itself assessable
(incremental commits versus a midnight blob, whether they can keep their changes
separable), you will patch the kit mid-task and `git pull` beats a second zip,
and the artifacts have to come back with history attached.

Public is your call and the reasoning holds — the GEOS decks and the
documentation the specifications were mined from are already on GitHub. What is
newly public is the *pairing*: spec ↔ reference deck ↔ split assignment, in one
place, in a form a scraper can use. The practical consequence is a shelf life
rather than a leak: a model trained after this repo is indexed may have seen the
pairing, at which point these seven tasks stop measuring authoring for that
model. Worth a line in the paper when the time comes, and worth re-checking the
copy ceiling against any newer model we evaluate. Nothing to do now.

### The key: bring your own

Per your advisor, no keys to people outside the group. So the kit is BYOK and
`TASK.md` says so directly, along with the thing that matters more: **we are
asking a student to spend their own money, so the ask should be small and a
bigger bill must not read as a better submission.**

| shape | rollouts | cost |
|---|---:|---:|
| frugal: 2 train tasks × 1 seed, 4 candidates, 2 test tasks | ~14 | **~$1.80** |
| standard: 4 train × 1 seed, 6 candidates, 3 test × 2 seeds | ~44 | ~$5.70 |

Both are labelled complete submissions. The default `--budget` ceiling dropped
from $15 to $5, and they are told to set a hard per-key limit on OpenRouter and
to say up front if cost is a blocker rather than quietly cutting the work.

**One thing to decide:** whether you want to offer reimbursement. $2–6 is not
much, but it is not nothing to an undergraduate, and "bring your own key *and*
your own money" is a slightly different ask from "bring your own key". If
reimbursement is possible, saying so in the invitation removes a reason for
someone good to decline.

## What is still open

- **Fix the git leak before the next rollout.** One line in
  `create_filtered_geos_copy`'s `_ignore`; the re-run of the screen is the
  expensive part.
- **Decide on reimbursement.** BYOK is settled, but $2–6 of a student's own
  money is a slightly different ask from a key, and offering to cover it removes
  a reason for someone good to decline.
- **Only `claude` is verified end to end.** The two `acpx` harnesses have
  correct flags and a present binary but nobody has run one. `qual harnesses`
  says so, and `Harness.unsupported(config)` reports what a given agent will
  silently ignore (ACP has no settings-file hooks).
- **The mock cannot see most of the search space.** It rewards vocabulary
  overlap and retries; tools, hooks, MCP and turn caps are invisible to it.
  Documented in three places, and still a trap worth watching for.
- **Nobody has measured hook-vs-retry**, and the kit says so. If a student
  answers it, that is a result we want.
- **The copy ceiling has never been measured on the full 46-task pool.** It took
  minutes on seven. On three of our four training tasks it sits *above* the seed
  agent's score, which would change how every seed baseline here should be read.
  Worth doing at the same time as the screen re-run.
