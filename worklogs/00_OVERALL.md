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
