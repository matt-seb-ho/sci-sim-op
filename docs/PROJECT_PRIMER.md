# Project primer — the north star

**Owner:** Matt Ho · **Written:** 2026-09-02 · **Supersedes nothing; contextualizes everything.**

This is the top-level statement of *what we are trying to do and what we are
constrained by*. Every other document in this repo describes a mechanism; this one
says why the mechanism exists. When a design decision and this document disagree,
this document wins and the decision needs revisiting.

Source material: [`2026-09-02_PROJECT_INTENT_raw.md`](2026-09-02_PROJECT_INTENT_raw.md)
(verbatim; the record of intent when this summary is ambiguous).

---

## 1. The goal, in one paragraph

**Make LLM agents genuinely useful for scientific research work, centered on
scientific simulation.** Today an agent can be handed a fully-specified problem and
asked to translate it into a simulator's input language. That is a narrow slice. The
target is the broader workflow around it — the busy work that currently consumes
researcher time — so that researcher time is reallocated to high-level planning and
thinking rather than low-level detail. The framing we prefer is not *replace
scientists*; it is **agents absorb the low-level work, and they do it in parallel and
without needing sleep, so scientific progress compounds faster.**

### The shape of the follow-up, as restated 2026-09-23

**Objective (the only one):** accelerate science by building tools that automate parts
of a scientist's work, so scientists can work at the level of ideas and direction.

**Three objectives for this follow-up paper:**

| | objective | meaning | status 2026-09-23 |
|---|---|---|---|
| 1 | **Depth** | own more of the pipeline. A scientist's workflow runs a → b → c; SIGA handled only *b* (a complete spec → deck → run). | **active.** The target is the *geological model* that precedes GEOS. See [`geomodel/`](geomodel/README.md). |
| 2 | **Breadth** | more domains and simulators than GEOS / LAMMPS / OpenFOAM | not started |
| 3 | **Methods** | understand, implement and test the latest self-evolution methods, then develop our own | started first. See §6 item 3. |

**Three method tenets:** a method should deliver all three.
1. **Domain adaptation**: a generic coding agent becomes competent in a niche
   scientific domain. This is T1, "studying".
2. **Continual learning**: the system gets better as it sees more tasks, sites and data.
   Sherman's "new data arrived, update the model" task is a natural instance.
3. **Harness self-evolution**: the system improves its own harness. This is T2 and T3.

SIGA's lightweight adapters **may** be part of the method but are not required.

**Domain expert:** Chris Sherman (LLNL, GEOS developer). Meetings every two weeks from
2026-09-11.

## 2. The three research threads

These are the intellectual content. Everything we build should advance at least one.

| # | Thread | The question |
|---|---|---|
| **T1** | **The open-book exam** — domain adaptation by *studying* | The simulator's documentation is good but does not fit in context, and stuffing it in is the wrong way to use it. What does an agent *study* such that it navigates the corpus better at test time? |
| **T2** | **Self-evolution / self-improving systems** | Can a system identify its own weaknesses, propose fixes, and measurably improve — and which ingredients of the 2026 methods actually carry the gain? |
| **T3** | **Harness / system optimization** | Given no training budget, how far does optimizing everything *around* a frozen model go? |

### T1 — the open-book exam, in detail

This is the oldest framing in the project and, in Matt's view, the most likely source
of a distinctive contribution.

> You have the textbook, so with enough time in the exam you can find any answer. What
> studying buys you is not memorization of the textbook — it is **understanding that
> lets you navigate it efficiently**. You know its structure, you know what you are
> looking for, you know what to search for.

Two extensions that make this ours rather than a restatement:

1. **Multi-source.** Not one documentation site. Depending on the task, the corpus is
   docs *plus* papers, books, blog posts, forum threads, example decks — and part of
   the skill is aggregating across them.
2. **Procedural, not just factual.** What gets internalized includes *know-how*: how to
   handle recurring situations, how to locate useful information efficiently, what to
   do when the validator says X.

**Related work:** arXiv:2605.19932 (queued for the literature sweep — see
[`LITERATURE_2026-08.md`](LITERATURE_2026-08.md) §11), and Jacob Li's "machine studying"
blog post. Matt arrived at this formulation independently, before that post published,
while scoping the SIGA follow-up. Note for writing-up purposes: **we should be able to
date our formulation**, and independent convergence is worth stating plainly rather
than hedging around.

## 3. Hard constraints

These are facts about our situation, not preferences. A plan that violates one is not
a plan.

1. **No meaningful GPU budget. Training is off the table.** This is *the* forcing
   constraint. It is why the work is harness optimization, which spends inference
   instead of gradient steps — an expense we can stomach.
2. **The frozen base harness is Claude Code, and that is a finding, not a default.**
   We wrote our own agent harness first and it underperformed Claude Code. Anthropic
   has better-resourced people working on that surface full time. So our contribution
   necessarily sits *on top* as an adapter. This landed well: it is exactly the
   right shape for "how do you domain-adapt a coding agent optimized for generic SWE
   work to extremely domain-specific scientific work?", which was the original question.
3. **Severely sample-starved.** ~17–20 search tasks, 2–3 seeds, ~12–25 min per
   task-run. A design that saves rollouts beats one that improves per-rollout quality.
4. **Grant stipulation: geoscience.** See §5.
5. **Usefulness to actual scientists is a requirement, not a bonus.** A method that
   wins on a benchmark nobody in the field wants is a failure by our own standard.

## 4. Method stance — what we are and are not attached to

**We are not attached to the adapter.** SIGA's adapter was born of resource scarcity
plus one small idea: if the space of modules is small, exhaustive search over
combinations is affordable. That was a reasonable place to start and it is not where
the field is going.

**Where the field is going, and where we should follow:** using an LLM as the driver —
to identify weaknesses, propose improvements, and implement them — rather than
enumerating a fixed module space. Our T2 work is the move in that direction.

**We have free rein on methods.** Nothing in the current codebase is load-bearing for
the research claim. `SimulatorSpec` / `RolloutRunner` / `Proposer` are contracts worth
keeping because they make experiments cheap; the search algorithm inside them is
replaceable and should be replaced when something better is demonstrated.

## 5. The geoscience situation — stated honestly

Funding comes through a UC collaboration helmed by **UC Irvine**, centered on
**Geoscience + AI**. Sibling subgroups work on PINNs and on multimodal-data model
training; **our team owns the LLM-agents piece.**

Two facts that pull in opposite directions, and the resolution:

- **We must work on geoscience applications.** Grant stipulation. Non-negotiable.
- **Matt's honest position: he is not personally interested in geoscience.** It is
  presumably important work; it does not hold his interest the way
  biology / medicine / physics / chemistry do. This is recorded because it is a real
  input to what the project should become, not because it changes what we owe the grant.

**Resolution — the standing strategy:**

> **Geoscience is the first and primary demonstration domain, because that is where we
> have expert access (UCI and LLNL geoscience researchers) and where the funding
> points. But the *methods* must be general.** We develop domain adaptation,
> self-improvement, and efficient study as general techniques, and we demonstrate
> efficacy across several domains. We do not tie the research identity to geoscience.

Practical consequence: whenever a design choice can be made simulator-agnostic at
reasonable cost, make it simulator-agnostic. The `SimulatorSpec` plugin boundary is
this principle in code, and it should stay honest — measured at a flat 150–300 lines
across four implementations, with the variable cost entirely in the scoring function.

## 6. The follow-up programme (from SIGA)

Three directions. Item 3 started first. **Item 1 is also active as of 2026-09-23.**

### Item 1 — Expand the *scope* of what the agent handles (depth)

SIGA assumes the user hands over a complete spec, just not in the simulator's DSL. That
makes it a translation task against a code book. We want the agent to own more.

- **Light version, already started:** mask the inferable parameters of a spec, so the
  input is a *partial* spec and the agent must infer the rest.
- **The right version:** talk to domain experts about what their workflows actually look
  like, then build benchmarks and methods around *those*. Guessing produces a benchmark
  nobody wants.
- **Status (2026-09-23): unblocked and active.** Sherman (2026-09-11 meeting) told us
  the geological model of a site takes 80–90% of the effort and the GEOS run is the easy
  rest. He confirmed that building it is a reasonable target for an LLM agent. Task:
  **site data → geological model**, starting with Utah FORGE, then a Gulf Coast site
  (easier) and San Emidio (hardest). The evaluation goes deep on fewer than 10 sites.
  See [`geomodel/README.md`](geomodel/README.md).
- ~~**Blocked on:** LLNL / UCI partner availability.~~ Resolved: Sherman, every two weeks.

### Item 2 — Expand the *breadth* of domains

Today: **GEOS** (geoscience), **OpenFOAM** (fluid dynamics), **LAMMPS** (molecular
dynamics). The portability claim is only as strong as the number of independent
simulators it survives.

- **Blocked on:** domain experts for new simulators — for ground truth, and for judging
  whether a generated configuration is *scientifically sensible*, which no metric we
  have can decide.
- **Cost shape:** adding a domain is mostly the cost of deciding what a good
  configuration is, which is exactly the part that needs the expert.

### Item 3 — Improve the self-evolution method ← **the active work**

Our SIGA effort here is, in Matt's words, *extremely rudimentary and broken in many
ways.* Specifically: the published loop never received a reward signal
(`round_mean_treesim: 0` in every round), so three rounds of "self-evolution" were three
unconditioned rewrites, and the paper's own held-out table shows the self-evolved cell
is within noise of the hand-designed one.

The field produced a lot here in the last few months. The plan is the obvious one:

1. **Figure out what exists** — done. [`LITERATURE_2026-08.md`](LITERATURE_2026-08.md),
   60 verified papers.
2. **Make a list of what to try** — done. Self-Harness (regression gate), AHE
   (component/experience/decision observability), GEPA (Pareto library outer loop),
   ACE (itemized delta updates under a token cap), plus SkillOpt and the newer
   RLMOpt / HarnessCompass / VaG lines.
3. **Implement** — largely done (`core/`, `evidence/`, `evolvers/`, `hygiene/`;
   579 tests passing as of 2026-09-02).
4. **Test them on our tasks, GEOS first** — **this is what is running now.**

**The deliverable of item 3 is intuition, not a leaderboard number:** *which ingredient
carries the gain, and is the answer the same on all three simulators?*

## 7. Standing methodological commitments

Non-negotiables that keep the work honest. Most were bought with a specific bad
experience; see [`WHY_V1_FAILED.md`](WHY_V1_FAILED.md).

- **The null result is a first-class outcome**, pre-registered as a kill criterion.
  Published evidence (arXiv:2607.12227) predicts a search in this regime returns its
  seed. Report it; do not tune until something looks positive.
- **Compute-matched baselines are mandatory, budgeted in from the start.** An unmatched
  win is not a win. The same paper finds harness evolution loses to plain parallel
  sampling at matched compute.
- **Clean three-way splits with error bars.** Of six methods surveyed, only one uses a
  three-way split; none of the three main comparison papers reports any dispersion
  statistic. In the predecessor codebase, **11 of 17 tasks its self-evolution loop
  optimized on sat inside its own designated test split.** Our defensible contribution
  is measuring whether this works *when the split is clean*.
- **Efficiency is an acceptance gate, not a metric.** An adapter that wins on score
  while inflating tool calls is the over-specification failure mode.
- **The dangerous bugs are the ones that produce a plausible number, not the ones that
  crash.** Four instances found in one night: a stop-policy knob nothing read, a banner
  regex that fed stack frames back as feedback, a harness exiting 0 with failed tasks,
  and a hygiene gate that blocked everything. Each was found by *running the thing and
  reading what it produced*, never by reading code. Prefer measuring to asserting.
- **Contamination hygiene is blocking and runs before any rollout is spent.**

## 8. Where things stand — 2026-09-02

| | |
|---|---|
| Tests | **579 passed, 7 skipped** (`uv run python -m pytest tests/ -q`) |
| Gates G1 (reward channel) / G2 (provider layer) / G3 (quarantine) | **all PASS** |
| Real GEOS rollouts | ~51 in the resume corpus; seed baseline mean **0.6547** over 6 tasks, zero-rate 0.000 |
| Search / baselines / ablations | **not yet run against GEOS** — this is the current job |
| Cost model | **$0.038/rollout** on `z-ai/glm-5.3-flash`; the full ~560-rollout programme is **≈$21** |
| Binding constraint | **wall-clock, not money** — ~28 h at 8-way parallelism |

**Environment fact that bites first:** the former `repo3` checkout now lives at
`/home/matt/projects/siga` after the 2026-09-02 home reorg. `find_repo3()` does not
search that path, so **`export REPO3_PATH=/home/matt/projects/siga`** is required or
preflight reports three spurious blockers. With it set, the only remaining blocker is
`GEOSX_EXECUTABLE`, which `scripts/_geos.py` sets automatically.

**Two open decisions from the overnight run**, both blocking the search from accepting
anything:

1. **Hygiene false positive.** `rare_token_overlap` flags *public GEOS API names*
   (`ExtendedDruckerPrager` appears 24 times in `schema.xsd`) that the agent can already
   read from its own mounted tools. A public-vocabulary allowlist is implemented but
   **off by default**, awaiting a human decision. Until resolved, acceptance is 0% by
   construction and any "null result" from the search is an artifact.
2. **`checks/` is not vendored into the plugin mount**, so `required_sections` and
   `constraints` cannot run in the container — and those are the instruments that detect
   the two binding constraints we actually measured.

## 9. Document map

| Read this | For |
|---|---|
| [`PROJECT_PRIMER.md`](PROJECT_PRIMER.md) | **← you are here.** Goals, constraints, strategy |
| [`geomodel/README.md`](geomodel/README.md) | **Item 1 (depth):** the geological-model task, FORGE data, papers |
| [`2026-09-02_PROJECT_INTENT_raw.md`](2026-09-02_PROJECT_INTENT_raw.md) | The verbatim source note |
| [`../README.md`](../README.md) | What the code is and how to run it |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | The three contracts, the loop, the gates |
| [`WHY_V1_FAILED.md`](WHY_V1_FAILED.md) | What each design decision is paying for |
| [`2026-08-26_followup-goals.md`](2026-08-26_followup-goals.md) | The three-goal programme in operational detail |
| [`2026-08-26_BUDGET_PLAN.md`](2026-08-26_BUDGET_PLAN.md) | Measured costs, rollout counts, MDE analysis |
| [`LITERATURE_2026-08.md`](LITERATURE_2026-08.md) | 60 verified papers; §10 is the unclaimed-territory list |
| [`NOTES_2607.12227.md`](NOTES_2607.12227.md) | The strongest published threat to our premise |
| [`INTEGRATION_REQUIREMENTS.md`](INTEGRATION_REQUIREMENTS.md) | What must hold before a run means anything |
| [`RUNBOOK.md`](RUNBOOK.md) | The sequence for a real run |
| [`../worklogs/`](../worklogs/) | How each decision was actually made |

## 10. Open questions worth holding

Not tasks — the things that, answered well, would change what this project is.

1. **What is the unit of "studying"?** T1 says an agent should study a corpus. We have
   not committed to what the studied artifact *is* — a primer, a set of retrieval
   policies, a procedural playbook, an index, or something we have not named. This is
   the highest-leverage undecided question in the project.
2. **Does studying beat retrieval?** Our own local result is that retrieval-gated memory
   was called **zero** times while verified functional, and arXiv:2608.14036 independently
   finds skills work as procedural anchors (65.7%) far more than as knowledge injection
   (4.5%), with retrieval precision collapsing 29.6% → 3.3% as the pool grows 5 → 100.
   That is suggestive, not settled, and it is directly testable here.
3. **Which component binds, per simulator?** Structural completeness binds on GEOS and
   OpenFOAM; value correctness on LAMMPS. Does the loop *discover* this, or must it be
   told? Nobody has done this, and we have a retrospective validation set.
4. **What does the expert actually do?** The object nobody in this literature has:
   paired expert and agent traces on the same tasks, *including browser history*. The
   derived quantity — what the expert looked up that the agent never did — is a
   principled, contamination-auditable generator for whatever the studied artifact
   turns out to be. Blocked on partner access; worth pushing for.
