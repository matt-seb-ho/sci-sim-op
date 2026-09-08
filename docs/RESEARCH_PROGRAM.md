# Research program — task set, splits, and hypotheses

**Written:** 2026-09-08 · **Supersedes:** [`EXPERIMENT_PLAN.md`](EXPERIMENT_PLAN.md) §5
(arms) and §7 (task scope). The method-to-paper mapping in that file still stands.

Answers, in order: **how big must the task set be**, **which tasks**, **how the splits are
divided and mechanically enforced**, **what we test**, and **which harness**.

---

## 0. The three decisions, up front

1. **12 tasks, family-disjoint, 3 seeds — 36 cells per arm.** Sized from measured σ,
   not chosen for roundness (§2).
2. **3-way split (train / dev / test), grouped by physics family, test sealed at the
   filesystem level and opened exactly once.** Not by convention — by mount (§4).
3. **Claude Code stays the primary harness.** A second harness enters as a *transfer
   test*, not a replacement (§6).

And one uncomfortable finding that reshapes the programme:

> **The zero rate cannot be the primary endpoint at any budget we will have.**
> Distinguishing our observed 0.06 zero rate from 0.02 needs **376 rollouts per arm**
> (80% power, α=.05). Even the flattering 0.20→0.05 contrast needs 76/arm. The primary
> endpoint must be the **paired continuous score**, with the zero rate reported as a
> descriptive secondary. `PROJECT_PRIMER.md` §7 says the tail is the objective; the power
> analysis says we cannot afford to measure it directly. Say so in the paper rather than
> reporting an underpowered tail statistic as though it settled something.

---

## 1. What the existing data says

109 rollouts, 6 tasks, `z-ai/glm-5.3-flash`. Per-task, pooled across candidates:

| task | n | mean | sd | headroom | verdict |
|---|---|---|---|---|---|
| `ExampleIsothermalLeakyWell` | 18 | 0.958 | 0.038 | 0.042 | **at ceiling — drop** |
| `AdvancedExampleDruckerPrager` | 18 | 0.865 | 0.226 | 0.135 | usable |
| `buckleyLeverettProblem` | 6 | 0.683 | 0.344 | 0.317 | very noisy |
| `ExampleDPWellbore` | 6 | 0.607 | 0.326 | 0.393 | very noisy |
| `ExampleMandel` | 20 | 0.317 | 0.167 | 0.683 | usable |
| `TutorialSneddon` | 6 | 0.134 | 0.116 | 0.866 | usable |

**The large σ values are driven by catastrophic zeros, not by continuous noise.** That is
the project's own thesis showing up in its measurement problem: the thing we care about is
exactly the thing that makes the metric unstable.

**Two tasks are unusable as they stand.** `ExampleIsothermalLeakyWell` has 4% headroom —
no intervention can show an effect there. `buckleyLeverettProblem` and `ExampleDPWellbore`
carry σ ≈ 0.33, which needs ~97 cells for MDE 0.05.

## 2. Target size — derived, not chosen

### 2.1 Continuous endpoint

Paired design, MDE = 1.96 · σ_d / √n, where σ_d is the **paired-difference** sd (lower
than raw σ because arms share the task):

| σ_d | MDE @ n=12 | MDE @ n=24 | **MDE @ n=36** | MDE @ n=48 | n for MDE=0.05 |
|---|---|---|---|---|---|
| 0.08 | 0.045 | 0.032 | **0.026** | 0.023 | 10 |
| 0.12 | 0.068 | 0.048 | **0.039** | 0.034 | 23 |
| 0.17 | 0.096 | 0.068 | **0.055** | 0.048 | 45 |
| 0.25 | 0.142 | 0.100 | **0.082** | 0.071 | 97 |

**Decision: 12 tasks × 3 seeds = 36 cells per arm.** On a σ-pruned pool (σ_d ≈ 0.12–0.17)
that buys **MDE ≈ 0.04–0.06**, which is the scale of effect this literature reports. Below
24 cells we cannot distinguish a real effect from the 2026-09-02 artefact where 89% of a
+0.1159 point estimate came from one cell.

### 2.2 Why not smaller, why not larger

- **Smaller (6–8 tasks)** is what we have been running and it is the reason the 2026-09-02
  result is uninterpretable: n=5 cells, CI [−0.08, +0.31]. A referee will not accept it,
  and they will be right.
- **Larger (20+ tasks)** does not pay for itself. Going 36 → 60 cells improves MDE from
  0.039 to 0.030 for 67% more money. Spend the marginal rollout on **more arms**, not
  tighter CIs on one arm — we are testing many hypotheses, not one.
- **3 seeds, not 2.** Two seeds cannot separate a bimodal rescue from a shift, which is
  precisely the ambiguity that made the `ExampleMandel` +0.5176 cell unresolvable.

### 2.3 Cost

| | per rollout | 36-cell arm | comment |
|---|---|---|---|
| 2026-09-02 as configured | $0.194 | $7.0 | with self-directed solves |
| **projected, solves removed** | **~$0.06** | **~$2.2** | needs measurement (§7 P0) |

**A 10-arm programme is ~$25–35 with solves removed, versus ~$70 with them.** Removing
simulation execution is not hygiene, it is what makes the programme affordable.

## 3. Which tasks — selection protocol

**Do not hand-pick.** Selection is a screening measurement, pre-registered before any
comparison is run.

### 3.1 Screening (arm P0)

Run the **seed adapter** on the whole eligible pool at **2 seeds**, recording score, σ,
zero rate, turns and cost per task. ~40 tasks × 2 = 80 rollouts, ≈$5 with solves removed.
This is the single highest-value purchase in the programme: every later decision, and
every power calculation, is conditioned on it.

### 3.2 Inclusion criteria — applied mechanically to the screen

A task enters the study set iff **all** hold:

| # | Criterion | Threshold | Why |
|---|---|---|---|
| 1 | **Headroom** | mean ≤ 0.90 | at ceiling nothing can be detected (`ExampleIsothermalLeakyWell`, 0.958) |
| 2 | **Floor** | mean ≥ 0.05 | a task nothing ever solves measures the ceiling of the model, not the adapter |
| 3 | **Tractable noise** | σ ≤ 0.30 | above this, MDE 0.05 needs ~97 cells |
| 4 | **Completes** | ≥ 80% non-harness-error | infrastructure failures scored as model failures is defect F-class, seen 3× |
| 5 | **Bounded cost** | ≤ 2× median turns | one runaway task can consume an arm's budget |

Tasks failing 1, 3 or 5 are **not discarded** — they move to a **reported-separately**
stratum, described with rates rather than means. `ExampleDPWellbore` (σ=0.33) is the
canonical member. Excluding a hard task silently is how a benchmark becomes flattering;
excluding it *and saying so, with its numbers* is honest.

### 3.3 Family structure — the part that matters most for validity

The 46-task pool is **not 46 independent tasks.** It is ~5 physics families with heavy
within-family structural sharing:

| family | n | examples |
|---|---|---|
| **Wellbore** | ~16 | `AdvancedExampleCased*`, `AdvancedExampleDeviated*`, `*DruckerPrager`, `*CamClay`, `ExampleDPWellbore`, `ExampleEDPWellbore`, `ExampleKirschWellbore` |
| **Fracture** | ~11 | `kgd*`, `pennyFrac*`, `pknViscosityDominated`, `TutorialSneddon`, `ExampleTFrac`, `ExampleProppantTest` |
| **Flow / multiphase** | ~8 | `buckleyLeverettProblem`, `Example*LeakyWell`, `ExampleSPE11b`, `TutorialCO2FieldCase`, `TutorialDeadOil*` |
| **Poroelastic / consolidation** | ~4 | `ExampleMandel`, `ExampleThermoporoelasticConsolidation`, `TutorialPoroelasticity`, `faultVerification` |
| **Material driver** | ~3 | `triaxialDriverExample`, `relaxationTest` |

`AdvancedExampleDruckerPrager`, `AdvancedExampleExtendedDruckerPrager` and
`AdvancedExampleViscoDruckerPrager` are near-siblings sharing constitutive blocks, mesh
idioms and solver stanzas. **A random task-level split leaks: an adapter that learns the
Drucker-Prager family from one member scores on its siblings without generalizing at all.**

> **Decision: splits are GROUPED BY FAMILY. A family lives entirely in one split.**
> This is the single most important methodological choice in this document, and it is the
> one that distinguishes our evaluation from every paper in `LITERATURE_2026-08.md`.

## 4. Splits — 3-way, family-disjoint, sealed

### 4.1 Two-way or three-way?

Genuinely in tension, so state the trade rather than assert:

- **For 2-way (train/test):** we are sample-starved. A third split costs tasks we cannot
  spare, and every task moved to dev widens the test CI.
- **For 3-way (train/dev/test):** harness *optimization* has a selection step. With 2-way
  you must either select on test — which is the contamination this programme exists to
  avoid — or select on train, in which case overfitting is invisible until the end and you
  have no early-stopping signal. The predecessor's failure was exactly this shape:
  **11 of 17 tasks its self-evolution loop optimized on sat inside its own designated test
  split.** And the field's own weakness is that only 1 of 6 surveyed methods uses a
  three-way split.

> **Decision: 3-way.** The whole claim of this programme is *"measured with a clean split
> and error bars nobody else reports."* Giving that up to buy ~4 tasks of precision
> forfeits the contribution. Affordability is bought back by opening **test exactly once**,
> on one configuration, at the end.

### 4.2 The split

| split | families | ~tasks | visibility | used for |
|---|---|---|---|---|
| **TRAIN** | Wellbore, Material driver | ~19 | fully visible | proposing edits; evidence corpus; failure mining |
| **DEV** | Fracture, Poroelastic | ~15 | scores visible, decks visible | selection, acceptance gate, early stopping, all ablations |
| **TEST** | Flow / multiphase | ~8 | **sealed** | one number, once, at the end |

Study set of 12 is drawn *within* train and dev by the §3.2 criteria; test is scored whole.

**Anticipated objection, and the answer.** Family-disjoint splits make the test set
genuinely out-of-family, so absolute test scores will be **lower** than an i.i.d. split
would give. That is the point: it measures generalization rather than family recall. Report
both, and report the i.i.d.-split number as the optimistic bound.

### 4.3 Sealing — mechanical, not procedural

The Q8 finding — a capability granted at the mount level went unnoticed for five weeks —
is the argument against enforcement by convention. **Enforce where the container is built.**

| # | Control | Mechanism | Failure it prevents |
|---|---|---|---|
| **S1** | Test GT physically absent | test ground-truth decks live outside the mounted tree during train/dev; the rollout container has no path to them | the agent reading its own answer |
| **S2** | Test task IDs blocked | hygiene corpus blocks test basenames, filename stems and numeric literals; **blocking, before any rollout is spent** | an adapter naming a test task |
| **S3** | Manifest records visibility | every run manifest records which split was mounted, with a hash of the mounted tree | a mount change going unnoticed for five weeks |
| **S4** | Pre-registration | split assignment + primary endpoint + MDE + stopping rule committed to git **before** the first test rollout; the commit hash goes in the paper | post-hoc split or endpoint shopping |
| **S5** | Sealed-envelope audit | before test is opened, an independent pass greps every accepted candidate artifact for test task names, stems and constants | leakage through the adapter text |
| **S6** | One-shot rule | test is scored once, on one configuration. A second look requires a new pre-registration and is reported as such | iterative test tuning |

**S1 is the load-bearing one.** Everything else is a check; S1 makes the failure
impossible rather than detectable.

## 5. Hypotheses

Ordered. Each is falsifiable, has a pre-registered prediction, and is worth writing up
whichever way it lands.

| # | Hypothesis | Prediction on record | Arms |
|---|---|---|---|
| **H1** | The evolved adapter beats the seed on **dev** | **null** — the CI spans zero (2607.12227; RLMOpt's seed-headroom result) | search vs seed, paired, 36 cells |
| **H2** | Any gain survives **compute-matching** against best-of-k at the k the ledger says search spent | **null** — matched sampling ties or wins (2607.12227: 67.4 vs 72.3) | matched-k baseline |
| **H3** | Which of the four ingredients carries any gain | gate and evidence are **inert** here — measured 2026-08-26: 0 hook interventions, zero rate already 0.000 | `--ablate gate\|evidence\|pareto\|delta` |
| **H4** | A gain on dev **transfers to a held-out family** | transfer is weaker than within-family; magnitude unknown | test, once |
| **H5** | **From-scratch converges to the handcrafted seed** (the bitter-lesson arm) | scratch plateaus below; if it overtakes, our prior is a ceiling | E0-scratch vs E0-siga |
| **H6** | The adapter transfers **across harnesses** | partial transfer; procedural content transfers, tool-specific content does not | Claude Code → second harness |
| **H7** | Orientation-cache (PEEK) beats delta-update (ACE) at equal token budget | PEEK wins on cost, ties on score | ingredient-D swap |

H1–H3 are the commitment. H4 is the paper's headline. H5–H7 are the differentiators.

## 6. Harness — stay on Claude Code, add one as a transfer test

**Decision: Claude Code remains primary.** Three reasons, in order of weight:

1. **Comparability.** Every SIGA number, the 109-rollout corpus, the hygiene gate, the R1
   receipt and the stop-hook plumbing are Claude Code specific. Switching resets the
   baseline and forfeits the historical comparison at the exact moment we finally have
   clean splits.
2. **It is the premise.** `PROJECT_PRIMER.md` §3.2: we adopted the adapter framing
   *because* our own harness lost to Claude Code. The frozen-strong-harness assumption is
   the setting, not an accident.
3. **Switching cost is not one-time.** Container spec, disallowed-tools list, stop hook,
   MCP wiring and the R1 feedback channel are all per-harness.

**But add exactly one alternative as H6, because it is a genuine contribution.**
Life-Harness (2605.22166) showed harnesses evolved on one 4B model transfer to 17 others;
**nobody has shown an adapter transferring across *harnesses*.** That result speaks
directly to `PROJECT_PRIMER.md` §5 — general methods, not geoscience- or vendor-specific.

Candidate, and the recommendation: **OpenHands.** Open source, container-native (matches
our enroot setup), model-agnostic via LiteLLM, and an established research baseline so
referees know what it is. **Codex** is the runner-up — closest in shape to Claude Code,
which makes transfer *easier* and therefore a weaker test. Defer `pi` and `opencode`;
lower research familiarity, no compensating advantage.

**Sequence it last.** H6 runs on a frozen, already-selected adapter. It costs one
evaluation pass, not a search.

## 7. Execution plan

| phase | what | rollouts | ~cost | gate to proceed |
|---|---|---|---|---|
| **P-1** | **Remove simulation execution from the loop**; measure the new per-rollout cost and turn count | 6 | ~$0.5 | turns < 100 median; cost < $0.10 |
| **P0** | **Screen the pool** — seed on ~40 tasks × 2 seeds; apply §3.2 criteria; publish the study set | 80 | ~$5 | ≥12 tasks pass; families balanced |
| **P0.5** | **Seal test** (S1–S4); pre-register splits, endpoint, MDE, stopping rule | 0 | $0 | audit S5 clean |
| **P1** | **H1** search vs seed on dev, 36 cells | 72 | ~$4.5 | — |
| **P2** | **H2** compute-matched baseline at ledger k | 72 | ~$4.5 | **never ship P1 without P2** |
| **P3** | **H3** four ablations × 36 cells | 144 | ~$9 | — |
| **P4** | **H5** E0-scratch | 72 | ~$4.5 | — |
| **P5** | **H4** test, once, one configuration | 24 | ~$1.5 | S5 audit signed off |
| **P6** | **H6/H7** harness transfer, PEEK swap | 48 | ~$3 | budget permitting |
| | **total** | **~518** | **~$33** | |

**Budget status, 2026-09-08:** OpenRouter key `limit_remaining` **$2.91**; account
`total_credits 210` − `total_usage 203.58` = **$6.42**. The programme needs **~$35–50**
including re-runs. **P-1 and P0.5 are free or nearly free and start now; P0 needs a
top-up.**

## 8. What changes in the code

1. **Remove simulation execution** — adapter/task negative constraint plus, durably, a
   wrapper on the `/opt/geosx-install` mount permitting only `--validate-input`. Keep
   **both** check paths: `xmllint` for well-formedness, `geosx --validate-input` for
   schema/semantic validity; they are subtly different and both are wanted.
2. **Turn cap ~100.** Timeouts averaged 199 turns vs 84 for completions.
3. **Family map** — `simulators/geos.py`, a task → family table; splits derive from it.
4. **Split enforcement** — `SimulatorSpec` gains a visible-split argument; the runner
   mounts only that split's GT tree; the manifest records the mounted-tree hash.
5. **Record `nproc` and load average per arm.** The box has been observed at 789/128.
6. **Screening report** — extend `scripts/report_geos.py` with the §3.2 criteria table.
