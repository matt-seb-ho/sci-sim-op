# Overall work log — harness-evolve (repo4)

One entry per session. Per-workstream logs are `worklogs/W*_*.md`.

---

## 2026-08-19 — session 1: rebuild decision, scaffold, fan-out

### Context

Subgoal (3) of the SIGA follow-up: pick and adopt a harness-evolution method.
The decision document is `repo3/docs/2026-08-19_method-adoption-plan.md`; the
first implementation pass landed on `repo3` branch `feat/siga-evolve-v2`
(commit 9183110, 42 tests). User then asked for a fresh repo — repo3 has
accumulated a lot of one-off scripts — so the work moves here and repo3's
branch stays as the record of the audit plus the quarantine of a contaminated
artifact.

### Methods adopted (the answer to "which method do we reimplement")

| Method | What we take | Why this task specifically |
|---|---|---|
| **Self-Harness** arXiv:2606.09498 | weakness mining → *minimal* proposal → regression-gated validation | supplies the selection operator v1 had none of; minimality suits a 775-token always-on artifact under a hard efficiency constraint |
| **AHE** arXiv:2604.25850 | component / experience / decision observability | evidence layer is the acute deficiency; its ablation (structure > prose) is the argument for widening the search space past prose |
| **GEPA** arXiv:2507.19457 | Pareto archive, acceptance hook, budget — **as a library** | sample efficiency is the binding constraint; Pareto over per-task scores is right when the whole effect is two tail rescues |
| **ACE** arXiv:2510.04618 | itemized delta updates incl. *delete*, for the memory component only | names the exact pathologies we measured (brevity bias, context collapse); its playbook scale is rejected on efficiency grounds |

Claimed as novel rather than imported: **binding-constraint discovery** (probe an
unseen simulator, infer whether the completeness gate or knowledge injection
binds, allocate search budget accordingly) and **EFC as a search objective**
(dense per-trajectory signal where task score gives one sparse scalar per
expensive rollout).

Rejected: DGM/Hyperagents-style open-ended archive over whole harness programs
(needs cheap plentiful evals; requires unfreezing the base harness); any
retrieval-gated memory module (the local zero-call result on an equivalent MCP
tool is decisive — import update mechanisms, deliver content always-on).

### Decisions this session

- **D1. Fresh repo `~/repo4`, package `harness_evolve`.** Matches the
  repo1→repo2→repo3 generational convention. repo3 is not modified further.
- **D2. Simulator is a plugin (`SimulatorSpec`), not a hardcoding.** Follows
  directly from the interface-dependence finding, and it is what makes
  subgoal (1) — breadth across simulators — an implementation rather than a
  fork.
- **D3. Three runner implementations, one protocol.** Real / cached-replay /
  mock. The mock runner exists so the search loop is testable end-to-end; not
  being testable end-to-end is a large part of why v1's missing reward signal
  went unnoticed.
- **D4. Run-and-score is one call, never two.** v1's scoring step was a separate
  shell invocation that was simply never made.
- **D5. Anchor / probe / held-out slice discipline** baked into the loop rather
  than left to launcher scripts.

### Progress

- [x] repo scaffolded, `pyproject.toml`, package layout
- [x] `types.py` — Score (failures-as-zero explicit), Cost, Rollout, Finding
- [x] three protocols: `SimulatorSpec`, `RolloutRunner`, `Proposer`
- [x] `core/manifest.py`, `core/candidate.py` ported from the repo3 branch
- [x] `docs/ARCHITECTURE.md`
- [ ] workstreams W1–W6 (fanned out below)

### Fan-out

| WS | Scope | Owns |
|---|---|---|
| W1 | archive, acceptance, decision log, search loop | `core/` |
| W2 | GEOS + mock simulators | `simulators/` |
| W3 | evidence corpus, diagnostics, EFC | `evidence/` |
| W4 | hygiene / contamination gate | `hygiene/` |
| W5 | evaluation protocol: baselines, paired stats, reports | `evaluation/` |
| W6 | runners (mock/cached/real) + check plugins | `runners/`, `checks/` |

Disjoint directories by construction, so parallel work cannot collide. Shared
contracts (`types.py`, the three `base.py` files, `core/manifest.py`,
`core/candidate.py`) are frozen for the duration of the fan-out; changes to
them go through this log.

---

## 2026-08-19 — session 1, revision 1: the shortlist was stale

### What prompted it

User pushback: *"ACE is quite old. In my mental model ACE has been supplanted by
AutoMem and works in that line."* Correct, and checking it turned up more than
one stale pick. I had anchored on the two lit-review files from an earlier
session, which are strong through ~June 2026 and thin after it. There is a
July–August 2026 wave of harness-evolution work that neither review covers.

### Verified since (all fetched from arxiv.org/abs and abstract-checked)

| ID | Title | Date | Why it matters here |
|---|---|---|---|
| 2607.08124 | **TTHE: Test-Time Harness Evolution** | 2026-07-09 | Evolves the harness *during evaluation* from **unlabeled execution traces**; judge commits from **execution-derived proxy signals**; population of candidates; solver/proposer/judge are roles around the same frozen LLM. No weight updates, no gold labels. |
| 2605.24539 | **DemoEvolve** | 2026-05-23 | Finds self-rollout harness evolution **works when episodes are short and failures attributable, and fails under sparse high-variance reward** where it is "misled by sparse feedback and candidate-selection noise". Bootstraps with expert demonstrations instead. |
| 2607.13683 | **HarnessBank** | 2026-07-15 | Harness Gene Bank of high-performing harnesses at different semantic coordinates + **Gated Harness Screening** to cheaply filter offspring before full evaluation. 5.1–15.4% over 7 benchmarks. Cross-model results say gains are model-specific, not a universal harness. |
| 2607.01224 | **AutoMem** | 2026-07-01 | Memory as a trainable *skill*; loop 1 = a strong LLM reads whole trajectories and revises the **memory structure** (prompts, file schemas, action vocabulary), not just its contents. ~2–4x on long-horizon games from memory alone. |
| 2606.31121 | **Janus** ("The Past Is Prologue") | 2026-06-30 | Method-agnostic **accept/reject controller for memory updates**, with a Memory Momentum Trigger and a *compact hybrid evaluation set of coverage / boundary / fresh tasks* instead of replaying history. +2.7–4.6 pts over base updaters. |
| 2605.13941 | EvolveMem | 2026-05-13 | Retrieval config as a structured action space; **revert-on-regression + explore-on-stagnation** safeguards. |
| 2606.17546 | SEAGym | 2026-06-16 | Evaluation environment for self-evolution; benchmarks ACE / TF-GRPO / AHE under one protocol. Finds frequent updates often fail to improve held-out, and good intermediate snapshots later collapse. |
| 2605.20086 | What Do Evolutionary Coding Agents Evolve? | 2026-05-19 | ~30% of lines added during evolutionary search are **byte-identical re-introductions of previously deleted lines**; most gains come from a small subset of edit types. |
| 2608.04968 | EvolveNet | 2026-08-05 | Collaborative harness evolution across data-local deployments; scope-typed, evidence-guided program aggregation. |
| 2602.02474 | MemSkill | 2026-02-02 | Memory *operations* as learnable, evolvable skills (controller / executor / designer). |
| 2606.04536 | TMEM | 2026-06-03 | Parametric memory via online LoRA. **Out of scope** — violates the frozen-model constraint. |

A dedicated verified sweep is running (W7) to close the June–August gap
properly; `docs/LITERATURE_2026-08.md` will hold the result.

### Revised adoption decision

**Dropped: ACE as the memory method.** Superseded. Its *named failure modes*
(brevity bias, context collapse) remain the right vocabulary for what we
measured, and it stays as a citation, but it is no longer what we build.

**Replacements and additions:**

| Slot | Was | Now | Reason |
|---|---|---|---|
| memory update mechanism | ACE 2510.04618 | **AutoMem 2607.01224 (loop 1 only)** | evolves memory *structure*, not only contents; loop 2 trains the model and is out of scope for us |
| memory update gate | — (none) | **Janus 2606.31121** | exactly the accept/reject-a-memory-update controller we lacked; its coverage/boundary/fresh eval-set construction is a principled replacement for my hand-picked anchor slice |
| harness search | Self-Harness 2606.09498 | **TTHE 2607.08124** primary, Self-Harness retained for its minimality bias | TTHE is newer, keeps model *and* base harness frozen, and commits on **execution-derived proxy signals** — which suits us unusually well because the simulator is itself a strong verifier |
| offspring screening | — | **HarnessBank 2607.13683** gated screening | direct answer to sample-starvation: filter offspring cheaply before spending rollouts |
| **regime check** | — | **DemoEvolve 2605.24539** | the most important paper for us; see below |
| optimizer | GEPA 2507.19457 | **unchanged** | ICLR 2026 oral, no successor found; still the sample-efficiency answer |
| observability | AHE 2604.25850 | **unchanged**, now benchmarked by SEAGym | |

### The uncomfortable finding, and what it changes

DemoEvolve's result is a direct challenge to this whole program. It reports that
self-rollout harness evolution **fails** precisely in the regime we are in —
sparse, high-variance reward where failures are hard to attribute — and that
under a fixed budget, demonstration-bootstrapped evolution beats it. Our regime
is worse than their failing case on every axis: fewer tasks, near-ceiling
in-distribution reward, and an effect concentrated in 2 of 10 tasks.

Two design consequences, both now first-class rather than optional:

1. **Demonstration bootstrapping.** We have something most of this literature
   does not: hand-validated ground-truth decks, and two human domain experts who
   authored decks under observation with browser histories recorded. Those are
   expert trajectories. The proposer should be able to condition on them.
   `Proposer.propose()` gets an optional demonstrations channel.
2. **Verifier-grounded proxy reward.** Following TTHE, the loop should not
   depend solely on the expensive gold-label score. `geosx --validate-input`
   gives a dense, cheap, execution-derived signal on every rollout, and the
   evidence layer already surfaces it verbatim. This pairs with the EFC work in
   W3: both are attempts to get a dense signal where the task metric gives one
   sparse scalar per 25-minute rollout.

Neither requires an architecture change — the three contracts absorb both — but
they move from "possible extension" to "the reason the design might work at
all". Recorded here so the reasoning survives even if the result does not.

Also stealing, cheaply: EvolveMem's **explore-on-stagnation** (we had
revert-on-regression but no stagnation escape) and EvoTrace's **edit-type
taxonomy** as a diagnostic — its finding that ~30% of evolutionary edits are
byte-identical re-introductions of deleted lines is a concrete pathology our
decision log can detect for free.

---

## 2026-08-19 — session 1, integration pass 1 (W2, W3 landed)

**Suite: 283 passed, 2 skipped** (the 2 skips need a real `geosx` / `lmp` binary).

### Contract changes made in response to workstream feedback

Both were flagged by W2 as gaps it had coded around rather than edited — the
right call, and both were genuinely mine to fix.

**`leak_pattern` could only express extensions.** OpenFOAM names artifacts by
bare name (`controlDict`, `fvSchemes`) and LAMMPS by type prefix (`in.melt`).
No extension list can capture either, so both simulators were overriding the
method. `SimulatorSpec` now composes the pattern from `leaky_extensions`,
`leaky_names`, and `leaky_prefixes`. A leak surface that silently omits a
simulator's most common filenames is worse than no gate, because it reads as
coverage.

**`preflight()` was doing double duty.** "The binary is missing" and "this
simulator has no scorer" are different facts with different responses: one is
fixable by installing something, the other means a search cannot run at all.
Split into `capabilities()` (a `SimulatorCapabilities` with a `searchable`
property) and `preflight()` (environment), with `blockers()` returning both.
Conflating them produces callers that degrade gracefully past a capability that
is never coming back.

**Slice discipline is now a type-level property**, from W3's observation that
`RoundEvidence` could not distinguish anchor from probe rollouts. `Rollout` grew
a `slice` field and a `selectable` property; `Search._evaluate` refuses to
aggregate a non-anchor rollout; `Search._probe` returns rollouts and *no scores
dict*, so there is nothing to accidentally hand the gate; and overlapping anchor
and probe slices raises. The failure this prevents — selecting on data that was
also shown to the proposer as evidence — looks exactly like progress and is
invisible to every downstream metric.

Writing the test for it immediately found a real bug: the probe cadence check
was `n % every == 1`, which is never true when `every == 1`. Probing would have
been silently disabled at its most aggressive setting. Fixed to
`(n - 1) % every == 0`.

### Notable findings from the workstreams

- **W3:** repo3's bottleneck extractor mined *actions only* and never a single
  tool result. That is the mechanical root of "the proposer never saw an error"
  — it was not a truncation problem, the observations were never collected.
  Also: `_flatten` raised on any detail blob missing a `tag`, i.e. exactly the
  malformed ones worth diagnosing.
- **W3:** EFC terminal feedback scores zero by construction (feedback arriving
  after the final action cannot have been retained). Deliberate — it makes
  "move validation inline" worth more than "improve the terminal report", which
  is the right incentive. Requires inline validator runs to pass a step index.
- **W3, unclosed:** EFC *validity* is measured as agent belief, not correctness.
  A hook naming whatever file the agent just touched scores 1.0. Needs a
  per-step oracle we do not have. Documented as a gaming hole rather than
  papered over. **Consequence: EFC is a search signal only — acceptance stays
  gated on score, cliffs, and cost. EFC rising while score is flat should read
  as suspected gaming first.**
- **W2:** repo3's variant-sibling contamination expansion globbed `*.xml` only —
  the same `.geos` blind spot as the hygiene regex, in a second place.
- **W2:** LAMMPS `score`/`diagnose` deliberately *raise* rather than returning a
  placeholder. Correct: every cheap proxy there measures the wrong thing, and a
  number that looks like a score will get optimised.

### Open coordination items

1. W6's mock runner must call `MockSimulator.simulate(...)`; W2 offered to
   change the signature rather than have the runner reach into internals.
   Resolve when W6 lands.
2. Screening margin and subset size are still guesses; they need real score
   variance to tune.
3. Anchor slice still hand-picked pending W7's read on Janus's
   coverage/boundary/fresh construction.

---

## 2026-08-19 — session 1, revision 2: the sweep, and a contribution worth claiming

W7's verified sweep landed: **61 arXiv IDs fetched and abstract-checked, zero
failures to resolve, zero mismatches** (`docs/LITERATURE_2026-08.md`, 60-row
table). It changed the shortlist again, found published counterparts for two of
our local negative results, and — most usefully — identified a gap nobody has
filled that we are unusually well placed to.

### Shortlist, revision 2

| Slot | Was (rev 1) | Now | Why |
|---|---|---|---|
| memory artifact | AutoMem 2607.01224 | **SkillOpt 2605.23904** | optimizes exactly our object — one skill document as the external state of a *frozen* agent — via bounded add/delete/replace accepted only on strict held-out improvement, with **zero inference-time model calls**, and was evaluated **inside Claude Code**, which is our harness. 2608.09629 finds it beats open-ended delegation when the optimizer is only medium-strength, i.e. our cheap-proposer regime. AutoMem's structure loop stays as a secondary reference. |
| budget enforcement | (token cap) | **SkillZip 2608.11079** | an MDL objective with a **hard coverage constraint per obligation**, so rare negative constraints provably survive compression — and it is **evaluation-free**, one extraction call, no rollouts. The only kind of budget mechanism affordable at ~$0.07/task-run. |
| acceptance | Self-Harness / Janus | **+ RLMOpt 2608.10471 no-regression floor**, **+ SEA 2607.00871 anytime-valid gate** | RLMOpt returns the *seed* rather than accept a noisy lower-scoring candidate (GEPA fell below its seed in 2 of 11 matched runs — unaffordable at n=2–3). SEA admits each edit through an anytime-valid gate emitting an auditable certificate against a fixed error budget, i.e. you may peek after every seed, which is what a 2–3 seed budget actually needs. |
| contamination | our gate | **+ VaG 2608.05810** | skill contamination is **structurally irreversible** — post-hoc rollback recovers little — so admission must be pre-commit, and three heterogeneous critics (structural / behavioural / semantic) are non-substitutable. Our free-gates-before-paid-gates ordering already matches; the irreversibility result is why it must stay that way. |
| retirement signal | — | **2607.07436 as a constraint** | a false-pass-biased judge does not merely add noise; past a threshold it **switches contribution-based retirement off entirely**, invisibly in aggregate metrics. Only verifier-like graders are spared. Direct argument for the simulator, never an LLM judge, as the retirement signal. |

**Mandatory evaluation tier gains two:** 2608.18066 (multiple runs *and shuffled
task order* — default orderings are a hidden curriculum, which directly indicts
v1's per-round task slices) and 2608.02636 (only 55/388 candidates produced a
byte-distinct validation best; runs the compute-matched controls we require).

### Two of our local negative results are now published phenomena

- 2608.14036 measures retrieval **actual-use precision collapsing 29.6% → 3.3%**
  as the pool grows 5 → 100. That is our zero-call `memory_lookup` result with a
  mechanism attached.
- 2608.11095 documents **+226% lifetime growth of agentic instruction files**
  with a formal reason deletion never happens — our 12× monotone primer growth —
  and a cheap fix (rationale comments) that removed 99.3% of excess instructions.
  Worth adopting directly: every derived constraint already carries provenance.

### The bad news, pre-registered as a kill criterion

**RLMOpt and MAGE (2607.11944) jointly predict our search returns its seed.**
MAGE finds that at N_train=30 a well-designed fixed prompt beat *every*
reflective optimizer ("scaffold choice dominates optimizer choice"), and that
its variance-amplification effect is **headroom-dependent** — at high base
accuracy you get the variance without the gain. We are at N=17 with a
hand-designed seed at 0.86–0.92.

Recorded as a pre-registered kill criterion rather than discovered later: **if
the search returns its seed under the no-regression floor, that is the predicted
outcome, it is a publishable null given 2607.12227, and we stop rather than
loosening the gate until something passes.**

Also flagged: 2608.02639 (Instruction Stacking Collapse) measures
instruction-following degrading non-linearly from ~96% to as low as 20% as
verifier-checked instructions stack 1→20, driven by pairwise conflicts. Our
primer + cheatsheet + negative constraints **is** a stacked-instruction prompt.
This is a real cost on every constraint we add and it is capability-graded, so
it interacts with the cross-model panel. The token budget was already a gate;
this says the count matters independently of the tokens.

### Prior art we did not know about

- **MOOSEnger 2608.15881** — a harness for the MOOSE multiphysics framework that
  validates and diagnoses input **through the simulation executable** and
  extracts lessons into persistent memory. 90% vs 5% for the bare model. The
  closest published system to our GEOS setting; a baseline, not a competitor.
- **PACE-Bench 2608.14441** — 144 simulator-grounded adaptation pairs across six
  physics domains, ten self-evolving methods compared. Headline finding:
  simulator-grounded reflection is more reliable than unverified self-revision,
  **while memory anchors agents to early designs**. An external benchmark whose
  thesis is ours, and a plausible transfer target for subgoal (1).
- **JutulGPT 2603.00214** — nearest neighbour to our problem, and it names a
  threat we inherit: choices resolved tacitly through *simulator defaults* are
  invisible to the assumption log.

### The gap, and what I built for it

Every verifier-grounded method the sweep found — DarwinX, VaG, SkillRevise,
TTHE, 2607.17352 — consumes a **pass/fail** verifier. That is all most verifiers
offer.

`geosx --validate-input` offers more. On an unknown attribute it prints the
**full table of valid attributes**; on a hallucinated tag, the ~50 legal solver
types; on a dangling reference, the set of names actually defined. It does not
report that the deck is wrong — **it names the correct action space at the point
of failure.**

Nobody has an evolution loop whose evidence channel carries that. The
consequence is concrete: a negative constraint can be **derived** from what the
simulator already said, rather than proposed by a model and then paid for with a
full evaluation round. Built today as `evidence/directives.py` (17 tests):

- parses the three observed GEOS directive shapes into
  `(offender, legal alternatives, context)`;
- distinguishes **near-misses from misconceptions** by edit distance, because a
  typo wants a correction and a misconception wants the legal set enumerated;
- derives constraints only at `min_support >= 2` — one slip is one agent's slip,
  and encoding one-offs is the over-specification failure again;
- emits each as **prose for the cheatsheet and a machine entry for the hook**,
  from one source, with provenance attached.

Two properties worth stating plainly. It costs **zero rollouts** to discover a
constraint this way — only to confirm one, which matters when a rollout is 25
minutes. And it carries **no contamination risk of the usual kind**: the
constraint comes from the checker's own schema, not from a ground-truth deck.
The agent could have obtained it by asking the validator. Constraints mined from
ground truth would be leakage; constraints mined from the interface contract are
what an adapter is *for*.

This displaces EFC-as-objective as the headline contribution. EFC stays as a
search signal (W3 built it, with its gaming holes documented), but it is a proxy
we would have to defend, and this is a mechanism we can demonstrate.

---

## 2026-08-19 — session 1, integration pass 2: all six workstreams in

**Suite: 384 passed, 2 skipped.** Every workstream integrated, plus the LLM
proposer and a full end-to-end integration suite.

### The integration test earned its keep immediately

`tests/test_integration.py` assembles the real parts — mock simulator, mock
runner, evidence corpus, hygiene gate, regression gate, archive, decision log,
budget ledger — and runs an actual search. It failed on first run, and the
failure was a real design bug in the gate, not a fixture problem:

**The "no new failures-as-zero" clause rejected nearly every candidate,
including genuine improvements.** Zero-score terminations are stochastic — that
is the phenomenon the adapters exist to suppress. So every candidate acquires a
fresh zero *somewhere* by chance. Judged on seed means, that reads as a
catastrophic per-task regression, and the gate rejects the improvement while
keeping whichever candidate happened to get lucky. The trace was unambiguous:

```
seed         mean=0.1411  accepted=True
candidate 1  mean=0.2125  REJECTED: per-task regression on task_4: -0.383
candidate 2  mean=0.2701  REJECTED: per-task regression on task_3: -0.392
```

Both rejected candidates were substantially better. This is my own open question
#3 from `W1_core.md` arriving as a concrete failure, which is the honest way for
it to arrive.

**The fix separates the two questions the effect actually decomposes into.**

- *Is the adapter better when it works?* — the aggregate clause now compares
  **best-of-seeds** per task when per-seed data is available.
- *Does it fail more often?* — the zero-rate clause compares **rates**, not
  incidences: a zero at one seed of several, on a task the parent also sometimes
  zeroed, is the base rate; a zero at every seed on a task the parent never
  zeroed is a regression.
- The per-task cliff test tolerates a drop that does not survive a best-case to
  best-case comparison, recorded as `tolerated_as_noise` rather than silently.

Averaging quality and reliability into one number and gating on it was always
wrong here, given that the entire published finding is that those two move
independently. With no per-seed data, or one seed, the gate stays conservative
and treats a drop as real — "cannot tell" must read as "assume real" for a gate
whose job is preventing catastrophic regressions.

`Search` now threads per-task per-seed scores through to the gate.

### Also found by integration

The directive parser could not handle two validator errors with no blank line
between them: the first error's alternatives list swallowed the second error
entirely. Terminator now stops at the next diagnostic line. Real GEOS output
does not promise blank-line separation.

### Contract fixes from W6

- **`KNOWN_CHECKS` was a snapshot of a registry.** A stop policy naming
  `cross_section_refs` — a real shipped check — failed validation, silently
  truncating the search space to four hardcoded names. Now resolves from the
  live registry.
- **`docs/INTEGRATION_REQUIREMENTS.md` R1 (blocking, repo3-side):**
  `docker_cmd.py` forwards a fixed `GEOS_HOOK_*` allowlist and drops both
  `GEOS_EVOLVE_*` variables at the container boundary. The search would vary
  feedback shape while the hook saw a constant — the same failure class as the
  dead reward channel, equally invisible in logs. The doc gives the test that
  settles it.

### State

| Module | Tests | Notes |
|---|---|---|
| `core/` (manifest, candidate, archive, acceptance, decision, search) | 20 | seed-aware gate |
| `simulators/` (mock, geos, openfoam, lammps) | 85 | TreeSim parity verified against repo3 |
| `evidence/` (corpus, diagnostics, efc, directives) | 60 | includes the directive contribution |
| `hygiene/` (corpus, gate, audit) | 60 | 11 rules; blocks both real leaked artifacts |
| `evaluation/` (stats, baselines, protocol, report) | 40 | four verdict outcomes incl. `mechanism_only` |
| `runners/` + `checks/` | 83 | subprocess runner unexecuted here by necessity |
| `proposers/` (edits, llm, scripted, demonstrations) | 42 | bounded add/delete/replace |
| integration | 6 | the test the predecessor did not have |

### Next

1. Wire derived constraints into the live loop (mined per round, fed forward).
2. Adopt Janus's coverage/boundary/fresh anchor construction over my hand-picked
   slice.
3. Run `RandomEditProposer` as a real arm, not a fixture — "does an LLM proposer
   beat random edits under the same gate" is a result either way.
4. Calibrate hygiene thresholds against the real ground-truth tree (R4).

---

## 2026-08-19 — session 1, pass 3: constraints in the loop, and a real anchor

**Suite: 401 passed, 2 skipped.**

### Derived constraints are now live

`ConstraintLedger` accumulates repair directives across rounds and publishes the
derived constraints to the proposer before each call. Two design points:

**Support accumulates across rounds, not within one.** A validator complaint seen
once is one agent's slip; the same complaint on three different candidates in
three different rounds is a property of how this model reads this interface —
which is the thing an always-on adapter should carry, and the thing a per-round
view structurally cannot see.

**It reports `actionable_fraction`** — what share of validator output actually
named a legal action space. This is the number that says whether the mechanism
does anything on a given simulator, and it is worth measuring rather than
assuming: a verifier that only emits verdicts sits at 0%, and the honest response
is to stop claiming the mechanism applies to it. There is a test asserting that
degradation is visible rather than silent.

The marginal cost of a constraint found this way is zero — directives arrive as a
by-product of rollouts already paid for.

### The anchor slice is no longer hand-picked

`evaluation/slices.py`, following Janus (arXiv:2606.31121)'s coverage / boundary
/ fresh construction.

My original 8-task anchor was *coverage-only*: spread across physics families so
nothing could be won narrowly. That is necessary and insufficient, and getting it
wrong is expensive here. The measured effect is concentrated in catastrophic-
failure rescues; where the bare harness already has a usable template, adapters
operate inside run-to-run noise. **An anchor chosen for coverage alone is mostly
tasks where nothing can happen**, and a search scored on it reads noise for most
of its budget — which, at a budget this small, is most of the run.

The `in_play` score ranks a task by how much is actually at stake:

- an **intermittent** zero rate — the task sometimes catastrophically fails and
  sometimes does not, which is exactly what adapters are known to fix, and the
  single most informative signal available. Peaks at a 50% zero rate and falls to
  zero at either extreme;
- across-seed spread — the outcome is not determined;
- a mid-range mean — neither saturated nor hopeless.

A task that always scores 0.98 and a task that always scores 0.0 both rank near
zero, for the same reason: nothing a candidate does will move either.

`boundary_fraction` defaults to 0.5 of the anchor. That is a bet, stated as one —
it is currently reasoning, not evidence, and it is the first parameter to revisit
once real baseline statistics exist.

Two honesty properties, both tested:

- **Cold start refuses to guess.** With no baseline statistics the boundary role
  cannot be identified, so the anchor is coverage-only and says so. Guessing
  would produce an anchor that looks principled and is arbitrary.
- **Lost coverage is reported.** Weighting toward tasks in play necessarily costs
  group coverage; which groups it cost is a decision the reader should see, not
  one buried in a ranking.

### Remaining

1. Run `RandomEditProposer` as a real arm against `LLMProposer` under the same
   gate. Given harness-updating capability is reported flat across model tiers,
   this is a result either way — and it is the cheapest meaningful experiment we
   can run before any real infrastructure exists.
2. Calibrate hygiene thresholds against the real ground-truth tree (R4).
3. Resolve R1 in repo3 before any real run: the container drops both
   `GEOS_EVOLVE_*` variables, so the stop policy would be searched over a knob
   nothing reads.

---

## 2026-08-19 — session 1, pass 4: CLI, README, and what building the entry point found

**Suite: 404 passed, 2 skipped.** `scripts/evolve.py` with `demo`, `preflight`,
`slices`, `audit`. README written.

Building the entry point surfaced two real bugs within one run, which is the
whole argument for building it rather than leaving the library to be assembled
by whoever comes next.

### Bug 1 — emptying a component destroyed it

`RandomEditProposer` deleted the last line of the primer. `with_edits` treated an
empty string as "remove the file", so the next `validate()` failed on a component
whose manifest entry pointed at nothing. "This cheatsheet has no lessons yet" is
a legitimate state and deleting the last line is the obvious way to reach it.
Declared components now keep their file when emptied; only files no component
claims are removed.

### Bug 2 — per-step gating does not bound where a lineage ends up

The first demo run produced a winner whose zero rate was **four times the seed's**
— while every accepted candidate had passed its parent comparison cleanly. A
sequence of individually acceptable steps walked reliability steadily downhill,
because each was only ever compared to the step before it.

This is a classic and it is worth stating in general terms: **no per-step
regression does not imply no cumulative regression.** The gate now also bounds
drift against the *seed*, with `max_extra_zeros_vs_root = 0` — suppressing
zero-score terminations is the entire purpose of the adapter, so a lineage
ending with more of them than it started with has lost the plot regardless of
what its mean did. The root bound is looser than the per-step bound, because some
drift is the point of searching; it is not absent.

### The residue the gate cannot reach, named rather than hidden

After the fix, the demo *still* shows a gap between the winner's score at the
search seeds and at fresh seeds. That is not cumulative drift and no gate can
bound it: selection ran at seeds (1, 2) and the re-score runs at (7, 8, 9), so
nothing the gate measured contains the information. It is seed overfitting, it is
exactly what a held-out re-score exists to reveal, and with 2 search seeds and a
stochastic zero rate some of it is unavoidable. More search seeds is the only fix
that addresses the cause rather than the symptom — and that is a budget decision,
not a code decision.

The demo now prints this explicitly, so it reads as a property of the setup
rather than a bug in the loop.

### `preflight` as a first-class command

The expensive failure mode in this kind of system is not a crash — it is a run
that completes and means nothing. So every known way for that to happen is
checked before anything starts, and `preflight` currently *refuses*:

```
BLOCKER: ground-truth directory not found; the content, numeric and structural
         hygiene rules would be inert
BLOCKER: UNVERIFIED: the runner must forward GEOS_EVOLVE_FEEDBACK_SHAPE and
         GEOS_EVOLVE_CHECKS into the container, and the hook must read them
2 blocker(s). A run started now would complete and mean less than it appears to.
```

That last line is the one this whole project exists because of.

---

## 2026-08-19 — session 1, pass 5: the protocol, dry-run end to end

`scripts/experiment_protocol_dryrun.py` runs search → compute-matched baselines
→ slice discipline → paired and tail statistics → budget ledger → verdict, on
the mock. Full write-up in `docs/EXPERIMENT_02_protocol_dryrun.md`; the rendered
document is committed at `docs/protocol_dryrun_report.md`.

### It refused a run that looks like a win

Naive reading of the same numbers: mean paired delta **+0.1251**, **3W / 0L /
1T**, beat best-of-k under both selectors.

Verdict: **`fails`**, for four independently sufficient reasons —

- one task was newly pushed **below the catastrophic threshold**, so the control
  clause fails despite the mean rising;
- **no baseline was actually budget-matched**, so the central question is
  untested;
- the design was **underpowered by construction**: minimum achievable p = 0.250
  against α = 0.05, which the report states rather than letting p = 0.25 read as
  weak evidence of no effect;
- the **mechanism moved the wrong way** — zero rate up 0.083, one rescue against
  one loss.

That is the write-up the predecessor produced. Having the machinery refuse it on
a synthetic run, before any budget is attached, is the point of building it.

### A planning constraint we did not know about

Budget matching failed structurally, not incidentally. The search spent 126
rollouts on a 6-task anchor; matching that against a **4-task** held-out slice at
3 seeds needs `k = ceil(126/12) = 11`, costing **2.10×** the search, while the
control spends **0.19×**. Neither is inside tolerance, so neither can carry the
verdict.

**A held-out slice much smaller than the search slice cannot host a
budget-matched parallel baseline.** The arms are matchable only when

```
search_rollouts  ≈  |held_out| × n_seeds × k     for small integer k
```

For the real experiment: 10 held-out tasks × 5 seeds and a ~150-rollout search
gives k=3 and lands close to matched; a ~500-rollout search would need k=10 and
overshoot. **The search budget and the held-out slice have to be planned
together.** This is not obvious and is exactly the kind of thing discovered too
late.

### An arm that could not be constructed

Sequential refinement runs through the harness's own stop policy, because that
*is* this system's refinement mechanism. At k=11 it exceeds the retry cap, and
matching it would mean changing the harness — unfreezing the thing the claim
holds fixed. Reported as **missing, with the reason**, rather than dropped:
"we could not construct a comparable sequential baseline at this budget" is a
finding about the comparison, not a detail of it.

### Also confirmed working

Slice discipline held with a timestamped audit trail (anchor→selection,
probe→evidence, held-out released once to one named candidate). Small-n guard
rails fired — the bootstrap refused an interval at n=4 rather than producing a
confident-looking one. Both best-of-k selectors reported, since the oracle alone
flatters the baseline and the validator alone flatters us. Every arm labelled by
model × harness configuration rather than by a system name.

### Running total

404 tests, 16 commits. Two experiments, both $0, both producing findings rather
than just exercising code.

---

## 2026-08-19 — session 1, pass 6: the budget planner and the runbook

**Suite: 415 passed, 2 skipped.** 18 commits.

### The dry run's failure became a tool

Experiment 02's budget-matching failure was structural, so it is now a planning
step rather than a warning in a document. `evaluation/budget.py` +
`evolve.py plan`.

The relation: parallel scaling spends `k` draws per cell, so a baseline can only
be matched at **multiples of `|held_out| × n_seeds`**. A budget chosen for any
other reason lands between the reachable points, and the mismatch cannot be
repaired afterwards — by the time it is visible the rollouts are spent.

For the expected shape (10 held-out, 5 final seeds, 8-task anchor, 2 search
seeds) the planner produces a hard ceiling nobody had computed:

| search rollouts | k | candidates | ≈USD | ≈wall |
|---:|---:|---:|---:|---:|
| 150 | 3 | 9 | $10 | 16 h |
| **350** | **7** | **21** | **$23** | **37 h** |

**21 candidates is the ceiling**, because past k=7 the sequential arm runs
through the stop policy's retry cap and cannot be constructed without changing
the harness — unfreezing the thing the claim holds fixed. That is a real
constraint on the experiment design, and it was invisible until the protocol was
actually executed.

Recommendation recorded: **150 rollouts, ~9 candidates.** Small enough to rerun
after a mistake, large enough that a null result is informative rather than a
non-attempt.

One design detail worth noting: `nearest()` prefers budgets where *every* arm can
be built, not merely where the ratio works out. A `k` the sequential arm cannot
express leaves the comparison short an arm, which is the same problem relocated.

### `docs/RUNBOOK.md`

Ordered so each step either removes a way for the result to be meaningless or is
cheap enough that doing it out of order wastes money. Steps 1–4 cost nothing and
gate step 5:

1. plan the budget **against the held-out slice**, before anything else
2. clear preflight — including the R1 test that settles whether the stop policy
   reaches the hook (run one task at each feedback shape, diff the hook log; do
   not skip because the config looks right, that is the exact failure mode)
3. verify the validator actually emits repair directives, not just verdicts —
   if `actionable_fraction` reads 0%, the derived-constraint mechanism does not
   apply to this build and should not be claimed
4. recalibrate the hygiene gate against the real tree, with both conditions
   holding: leaky artifacts still block, the legitimate adapter produces no
   errors. If the second fails, raise thresholds rather than disabling a rule —
   a gate people route around is worse than no gate
5. baseline, freeze the slices, then search
6. final evaluation, once, verdict read before the numbers

It closes with the pre-registered kill criterion, stated as a commitment rather
than a caveat: **if the search returns its seed under the no-regression floor,
that is the predicted outcome — report it and stop.** A gate tuned until it
admits a winner is not a gate, and the number it produced would be exactly the
kind this project exists to stop producing.

### Where things stand

Everything buildable without the real environment is built. The remaining work is
gated on things this machine does not have: the ground-truth tree, a Docker
daemon, the GEOS container, and an API key. The runbook is the handoff for when
they exist.

---

## 2026-08-19 — session 1, pass 7: making a long run survivable

**Suite: 427 passed, 2 skipped.** 19 commits.

`runners/recording.py` — a `RecordingRunner` that wraps any runner, appends every
rollout durably as it completes, and replays what it already has on a restart.

### Why this and not something else

Everything still buildable without the real environment is now built, so the
question was which remaining gap actually costs something. This one does. The
budget planner puts a credible search at 16–37 hours of wall-clock against a
container, an external API, and a machine that may reboot. A crash at hour twelve
that forces a restart from zero does not merely cost twelve hours — it makes the
experiment something nobody wants to attempt twice, and that is how protocols get
quietly relaxed. "We did not re-run it" and "we lowered the bar" are the same
decision under pressure.

The same mechanism answers a second problem. The statistics, baselines, verdict
criterion and tail measures are all cheap; the **rollouts** are the expensive
part. With them on disk the entire evaluation can be recomputed for nothing —
against a different noise band, an added baseline, a corrected bug. Without it,
every question asked after a run costs another run, and the honest prediction is
that it does not get asked.

### Design points worth keeping

- **Append, flush, fsync per rollout.** Buffering would lose precisely the work a
  crash makes expensive. A few milliseconds against a rollout measured in minutes
  is not a tradeoff worth reasoning about.
- **A truncated final line is expected, not exceptional.** It is what an
  interrupted write looks like — the exact situation this class exists for — so
  it is skipped, counted, and reported, never fatal.
- **A failed write keeps the rollout.** Losing the *record* of a completed
  rollout is bad; discarding the rollout itself is worse. The default keeps the
  result and counts the failure loudly; `strict_writes` inverts that for when
  resumability matters more than the current run.
- **Validator events survive the round trip.** Stop-hook decisions are the
  evidence half the stop-policy search rests on; a corpus that dropped them could
  not support an offline re-analysis of it.

### Verified through the CLI

```
first run:   138 rollout(s): 116 executed, 22 replayed from the corpus
second run:  138 rollout(s):   0 executed, 138 replayed
```

The 22 replays in the *first* run are within-run deduplication — the same
candidate scored twice across screening and full evaluation — which is a real
saving on top of the resume property, not an artifact.

### Remaining work is genuinely gated on infrastructure

- hygiene threshold recalibration — needs the ground-truth tree
- R1 (the container dropping the stop-policy environment) — needs a repo3 change
  and a container to test it against
- `LLMProposer` versus the random control as a real arm — needs an API key
- everything downstream of those — needs Docker and the GEOS image

`docs/RUNBOOK.md` is the handoff for when they exist.
