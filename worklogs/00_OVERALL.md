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
