# Experiment plan — what we are testing, and which paper each piece comes from

**Status:** living document. Supersedes nothing; it consolidates the method
choices scattered across `2026-08-26_followup-goals.md` §1.2,
`siga/docs/2026-08-19_method-adoption-plan.md` §2, and
`LITERATURE_2026-08.md` §§8–10 into one place, and adds the newer candidates that
plan predates.

Read [`PROJECT_PRIMER.md`](PROJECT_PRIMER.md) first for why any of this matters.

---

## 1. The question this programme answers

Not *"can we make self-evolution work?"* but:

> **Does harness self-evolution produce a real, generalizing gain for scientific
> simulator configuration when the train/test split is clean, the baselines are
> compute-matched, and the error bars are reported — and if so, which ingredient
> carries it?**

That framing is chosen because it is defensible whichever way it comes out. The
one paper in this literature with a genuinely disjoint split (arXiv:2607.12227)
finds harness evolution gains +1.2/+0.0 held-out, scores *below* its own starting
harness without unit tests, and **loses to plain parallel sampling at matched
compute**. Of six methods surveyed, only one uses a three-way split; none of the
three main comparison papers reports any dispersion statistic. **A clean null,
with error bars nobody else publishes, is a result.**

## 2. The four adopted ingredients — the core ablation

Each was chosen because it answers a *measured* pathology in SIGA v1, not because
it is recent. These are the four arms `--ablate` switches off one at a time.

| # | Ingredient | Paper | What we take | Pathology it answers | Status |
|---|---|---|---|---|---|
| **A** | **Regression gate** | Self-Harness, arXiv:2606.09498 | minimal proposals + accept only on no-regression | unconditioned rewriting; 12× monotone adapter growth | implemented `core/acceptance.py`; `--ablate gate` |
| **B** | **Evidence richness / observability** | AHE, arXiv:2604.25850 | component / experience / **decision** observability | proposer saw almost no evidence; no audit trail | implemented `evidence/`, `core/decision.py`; `--ablate evidence` |
| **C** | **Pareto archive** | GEPA, arXiv:2507.19457 | outer loop as a *library*; Pareto over **per-task** scores | no archive, no selection, and we are sample-starved | implemented `core/archive.py`; `--ablate pareto` |
| **D** | **Delta updates under a token cap** | ACE, arXiv:2510.04618 | itemized deltas, hard budget | context inflation in an always-on 775-token artifact | implemented `proposers/edits.py`; `--ablate delta` |

**The deliverable is which of A–D carries the gain, and whether the answer is the
same on GEOS, OpenFOAM and LAMMPS.** Not a leaderboard number.

**Known before the search even runs** (2026-08-26, and it is an ablation result
obtained for zero rollouts): the stop policy is **inert** on this pool — zero hook
interventions across a 0.09–0.98 score range while demonstrably delivered and
read — and the **zero rate is already 0.000**, so the regression gate's central
clause cannot bind. Two of four instruments are measurably inert up front. See
`worklogs/2026-08-26_overnight.md` §22 for the partial reversal of the "inert"
claim after the noise floor was measured.

## 3. Evolver arms already implemented

`src/harness_evolve/evolvers/` — each is a pluggable strategy behind one interface.

| Arm | Module | Source | Role |
|---|---|---|---|
| Gated search | `search.py` | Self-Harness + GEPA | the main arm |
| AHE-style component cycling | `ahe.py` | arXiv:2604.25850 | component-wise optimization |
| SkillOpt | `skillopt.py` | arXiv:2605.23904 | bounded add/delete/replace on one skill doc, accept only on strict held-out improvement; zero extra inference-time calls; evaluated *inside Claude Code* |
| Random search control | `random_search.py` | — | the control that says whether search is search |
| Matched comparison | `compare.py` | arXiv:2607.12227 | refuses unmatched budgets by construction |

## 4. Candidates from the newer literature — not yet implemented

From `LITERATURE_2026-08.md`. Ordered by expected value for our regime, with the
specific reason each is a fit. **These are the "new ideas" to try after the core
four are measured.**

| Paper | The component to take | Why it fits us |
|---|---|---|
| **PEEK**, arXiv:2605.19932 | **Orientation cache**: a constant-sized "context map" of what the corpus contains and how it is organized, maintained by Distiller → Cartographer → priority **Evictor** under a fixed token budget | The nearest published instance of our open-book-exam thesis (T1). **1.7–5.8× lower cost than ACE** at fixed budget, 93–145 fewer iterations. Its Evictor is a better fit than ACE's delta updates for an always-on artifact. **Replaces ingredient D.** |
| **RLMOpt**, arXiv:2608.10471 | **No-regression floor** + the headroom finding | Never produced a prompt below its seed (GEPA did twice); prompts 27–79% of GEPA's size. States gains are set by **seed headroom, not search budget** — directly tests our Q6 bitter-lesson question. |
| **SkillZip**, arXiv:2608.11079 | **Evaluation-free compression** by MDL under a hard per-trigger coverage constraint | The only budget-enforcement mechanism found that costs **zero rollouts** and provably preserves rare negative constraints. Pairs with our efficiency-as-a-gate stance. |
| **VaG**, arXiv:2608.05810 | **Pre-commit gating** with three critics (structural / behavioural / semantic) | Argues acceptance must be pre-commit because skill contamination is *structurally irreversible*. Our validator is a ready-made structural critic. |
| **HarnessCompass**, arXiv:2608.01918 | **Global constraints** restricting edits to task-agnostic changes; component-wise optimize-then-consolidate | Supersedes AHE on generalization — the exact overfitting failure 2607.12227 warns about. |
| **Catastrophic remembering**, arXiv:2608.11095 | **Rationale comments** attached to each instruction | Names and fixes our exact v1 pathology (12× monotone growth). Removed 99.3% of excess instructions in verifiable worlds. |
| **Phantom Guardrails**, arXiv:2607.13083 | Their **fabrication audit**, run on our loop | We have a *real* byte-exact oracle and a proposer whose brief is literally "add negative constraints". First deployment of that audit outside its own paper. |
| **StateM**, arXiv:2608.15089 | Learned control as an **enforced precondition**, not prose | Our constraints-as-checks idea, demonstrated at our price point. |

**Explicitly declined** (reasoning in the method-adoption plan §8.3 and
`LITERATURE_2026-08.md` §9): DGM/Hyperagents-style open-ended archives (too
rollout-hungry for ~17 tasks); DarwinX's population + recombination loop (same);
any reintroduction of **retrieval-gated memory** (`memory_lookup` was called
**zero** times across every test-set run while verified functional, and
arXiv:2608.14036 independently finds retrieval precision collapses 29.6% → 3.3%
as the pool grows 5 → 100).

## 5. Arms to run

Order matters: 1–3 are the commitment, 4–6 are the science.

| # | Arm | What it establishes | Non-negotiable? |
|---|---|---|---|
| 1 | **Baseline / noise floor** — seed adapter, per-task σ | without it no comparison is interpretable | yes |
| 2 | **Search** — all four ingredients on | the experiment | yes |
| 3 | **Compute-matched baseline** — best-of-k at the k the ledger says the search spent | **an unmatched win is not a win** (2607.12227) | **yes — never ship 2 without 3** |
| 4 | **Ablations** — A/B/C/D individually | *the actual deliverable*: which ingredient carries the gain | the point of the programme |
| 5 | **E0-scratch** — evolve from an empty adapter instead of the SIGA seed | tests the bitter-lesson objection (Q6): is our prior load-bearing or a ceiling? | new; see below |
| 6 | **Cross-model panel** | measured gain depends on the inference model (arXiv:2605.30621); Self-Harness's first stage is *model-specific* weakness mining | budget permitting |

### 5.1 Arm E0-scratch — evolve from both starting points

Added 2026-09-02 from Matt's bitter-lesson question ([`2026-09-02_QA_LOG.md`](2026-09-02_QA_LOG.md) Q6).

Run the identical loop from two seeds: **the SIGA handcrafted adapter** and **an
empty/minimal adapter**. Same budget, same tasks, same gate. Three outcomes, all
publishable:

- **scratch converges toward the handcrafted adapter** → strong positive result
  about the loop; it rediscovers what humans derived.
- **scratch plateaus below** → the prior is earning its place; quantifies how much.
- **scratch overtakes** → the handcrafted prior is a *ceiling*. Most interesting,
  and invisible without this arm.

Budget honestly: from-scratch needs more rounds precisely because it starts with
less. RLMOpt's "gains are set by seed headroom" predicts the scratch arm shows
the larger delta and the worse endpoint — which is itself the measurement.

## 6. Evaluation discipline — non-negotiable

From `PROJECT_PRIMER.md` §7, restated because this is where the literature is weak.

1. **Three-way split, clean.** In the predecessor codebase **11 of the 17 tasks
   its self-evolution loop optimized on sat inside its own designated test split.**
2. **Paired, per-task statistics.** Never a bare mean. Per-task σ ranges
   **0.0035 to 0.32**; a mean over that without dispersion is not a result.
3. **The tail is the objective.** Zero rate and per-task minimum are first-class;
   in-distribution mean is conceded as saturated.
4. **Compute-matched baselines budgeted in from the start**, never added after.
5. **Efficiency is an acceptance gate, not a metric.**
6. **Hygiene is blocking and runs before any rollout is spent.**
7. **The null is pre-registered.** Do not tune until something looks positive.

## 7. Task-scope decisions

- **GEOS is used for validation, never for solving.** `xmllint` for XML
  well-formedness *and* `geosx --validate-input` for schema/semantic validity —
  the two are subtly different and both are wanted. A converged simulation adds
  nothing to a structural score and consumed the entire wall-clock budget on
  2026-09-02. See [`2026-09-02_QA_LOG.md`](2026-09-02_QA_LOG.md) Q3.
- **Turn cap.** Runaway rollouts are the dominant cost term (timeouts: 199 mean
  turns vs 84 for completions). Cap ~100.
- **Record `nproc` and load average at the start of every arm.** The box is
  shared and has been observed at 119.98/128 from other users; wall-clock numbers
  are not interpretable without it.

## 8. Open threads

1. **What is the unit of "studying"?** (`PROJECT_PRIMER.md` §10.1) PEEK's context
   map is the closest published answer and the first thing to try.
2. **Which component binds, per simulator?** Structure on GEOS/OpenFOAM, values
   on LAMMPS. Does the loop *discover* it or must it be told? Nobody has done
   this and we have a retrospective validation set.
3. **Partial-spec tasks** — mask the inferable parameters, so the agent infers
   rather than translates (`PROJECT_PRIMER.md` §6 item 1).
4. **Expert traces with browser history** — what the expert looked up that the
   agent never did. Blocked on partner access; the most distinctive object
   available to us.
