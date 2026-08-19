# Why the predecessor loop failed

The self-evolution loop this project replaces lived at
`repo3/scripts/self_evolving/`. It produced an adapter lineage `v0 → v1 → v2 →
v3`, and `v3` was reported as the self-evolved (SE) configuration. This document
records what actually happened, because the design decisions in
`ARCHITECTURE.md` are mostly responses to specific items here.

Everything below is established from committed artifacts — `.reflection_meta.json`
files, adapter contents, and script source. The run logs and evaluation outputs
lived on a volume that is not available in this environment, so where a claim
depends on them it is marked as inferred.

## 1. The loop never received a reward signal

`run_full_evolution.sh` alternates two steps:

```bash
bash scripts/self_evolving/run_round.sh 0 "${TASKS_R0[@]}"
python3 scripts/self_evolving/reflect.py --from-version 0
```

`run_round.sh` invokes `scripts/run_experiment.py`, which runs the agent. It does
not score. The only code that writes `<task>_eval.json` is
`scripts/eval/batch_evaluate.py`, and no step in the pipeline calls it.

`reflect.py:gather_round()` reads `treesim` out of those files. They did not
exist, so `treesim` was `None` for every task, the list of scores was empty, and
`mean_ts` fell through to `0`.

The proposer's prompt therefore read:

```
RECENT ROUND RESULTS (mean treesim 0.0000, n=7):

--- AdvancedExampleDruckerPrager (treesim N/A) ---
R: /geos_lib/inputFiles/...
B: grep -rn ...
```

Confirmed on disk — `plugin_evolving/v{1,2,3}/.reflection_meta.json` each record:

```json
"round_mean_treesim": 0
```

The equation the method section states,
`θ* = argmax E[r]`, was not weakly approximated. There was no reward anywhere in
the loop, and `v3` is not a selected candidate — it is the last link in a chain
of three unconditioned rewrites.

**Compounding it.** The prompt also said: *"If the current plugin is already
working well (≥0.85 mean treesim), it's fine to make small additions or no
changes."* With `0.0000` rendered every round, that branch could never fire. The
proposer was told it was failing catastrophically at every step, and responded
the way that instruction invites:

| version | `PRIMER.md` | `memory/cheatsheet.md` |
|---|---|---|
| v0 | 270 B | — |
| v1 | 1 883 B | 2 838 B |
| v2 | 2 488 B | 4 843 B |
| v3 | 3 159 B | 4 526 B |

A 12× growth in an always-on artifact, with no evidence that any of it helped.

**→ Design response.** Run-and-score is a single call on `RolloutRunner` that
cannot be half-performed. The loop is tested end-to-end against a synthetic
problem with a known optimum (`tests/test_search.py`), so a dead reward channel
fails a test in 0.1 s instead of running for three rounds.

## 2. The reported gain was not from evolution

The published held-out numbers, all for the same cell shape:

```
S+X+M            0.783 ± 0.022     (hand-designed, no evolution)
Self-Evolve      0.789 ± 0.012
Self-Evolve-prose 0.775 ± 0.024
```

The headline "+0.069 over Vanilla" decomposes into +0.063 from the hand-designed
adapter and +0.006 for everything three rounds of self-evolution contributed —
±0.008 against σ ≈ 0.02 at n = 3. Given item 1, there is no mechanism by which it
could have been more than chance.

**→ Design response.** The honest control (seed adapter, same seed count, no
extra budget) is a required baseline, not an optional one, and the evaluation
protocol refuses to report a confident interval when n is too small to support
one.

## 3. No selection operator

`reflect.py` wrote `v{N+1}` unconditionally. The only rejection paths were
malformed output, path traversal, and a hardcoded path allowlist. No
accept-if-better gate, no regression check, no rollback, no re-evaluation of the
parent.

**→ Design response.** `core/acceptance.py`, gating on per-task cliffs, new
zero-score terminations, aggregate drop, and cost inflation — with the rejection
reason recorded rather than discarded.

## 4. Linear chain, no archive

One lineage, three reflections, one proposer call each. No population, no
branching, no way to return to an earlier candidate.

**→ Design response.** `core/archive.py`, Pareto frontier over per-task scores.
The effect being optimised is a small number of tail rescues; mean-based hill
climbing discards the candidate that produced one.

## 5. Evidence was a list of tool names

`trajectory_summary()` emitted 2 500 characters of `R: <path>`, `B: <cmd[:80]>`,
`GR: <pattern[:60]>`. No observations, no errors, no validator output, no failure
classification, no per-section scores.

The repository already contained `scripts/bottleneck/extract.py`, which computes
per-section scores, the k worst failing subtrees, missing/extra element types,
mined trajectory features, and a trajectory excerpt. None of it was wired in.

**→ Design response.** `evidence/`, a layered corpus with on-demand drill-down.

## 6. The search space excluded the components that mattered

Writable paths were `PRIMER.md`, `memory/`, `skills/`, `agents/`.
`copy_scaffolding()` copied hooks, validators, and MCP servers verbatim as
untouchable. So the loop could not modify the termination gate — the component
the project's own ablation identifies as dominant on two of three simulators.

arXiv:2604.25850's ablation localises its gains to tools, middleware and memory
*rather than* the system prompt, concluding that factual harness structure
transfers while prose-level strategy does not. The predecessor searched only the
half that paper says does not transfer.

**→ Design response.** The stop policy — retry budget, feedback shape, active
checks — is a first-class searchable component in `core/manifest.py`.

## 7. Contamination

Two findings, one of which reached the shipped artifact.

**The hygiene gate was one `.xml`-only regex.** `v3` — the adapter reported as
SE — carries ground-truth dependency filenames with a different extension
(`tables/time.geos`, `tables/radialStress.geos`, `tables/axialStrain.geos`)
across three files. The durable audit script used the identical pattern, so it
had the same blind spot.

**A separate artifact was a task-to-answer lookup table.**
`plugin_evolving/v4/memory/cheatsheet.md` opens:

> **Read the listed file(s) FIRST. Do not Grep/Glob to find them — they are already verified.**
> | Task name keyword | Canonical XML(s) |

followed by a row for each of the 17 evaluation tasks. It did not come from
`reflect.py` (whose regex would have stripped every filename and logged the
count), and its `.reflection_meta.json` is a byte-identical copy of v3's. It was
wired into a launcher script. No published number used it — SE is v3 — but it
was live in the tree until it was quarantined.

arXiv:2607.22368 calls this class of thing an *exposure* and quantifies the
resulting score inflation; it found roughly two thirds of traces in two science
benchmarks showed exposure or reward hacking.

**→ Design response.** `hygiene/` is a blocking gate covering filenames across
every extension the simulator declares leaky, ground-truth path components,
task-id tables, content overlap, and canonicalised numeric literals — run before
any rollout is spent. Demonstrations are sanitized through the same gate, since
a record of an expert solving the scored task is the most concentrated leak
source in the system.

## 8. Smaller defects, each of which hid something

| Where | Defect | Consequence |
|---|---|---|
| `analyze_evolution.py:67` | invalid f-string format spec raising into a bare `except: pass` | the version log **always rendered empty**, so `round_mean_treesim: 0` was never displayed to anyone |
| `reflect.py:113` | iterated every subdirectory of the run dir as a task | a non-task directory was fed to the proposer as a task (`round_n_tasks: 7` for a six-task round) |
| `run_round.sh:29-50` | cheatsheet concatenated into the primer; a computed `CHEATSHEET_ARG` never used | the lineage had no separable memory component, so it could not be budgeted |
| `run_full_evolution.sh:17-19` | rounds ran on disjoint task thirds | round-over-round changes confounded adapter quality with task difficulty |
| `plugin_evolving/v*/hooks/` | scaffolding snapshotted at v0 | the lineage evolved against a validator the project had since replaced — 274 lines of drift |
| `reflect.py:49,51` | hardcoded absolute paths | nothing was runnable off the original machine |

The first one deserves emphasis. A single malformed format string, swallowed by
a bare `except`, is why the most important fact about this experiment — that its
reward channel was dead — was invisible in the one report designed to surface it.

**→ Design response.** No bare excepts on a reporting path; the anchor slice is
fixed across rounds; scaffolding is resolved at materialize time rather than
snapshotted; paths are configuration.

## What to take from this

The proximate cause was a missing line in a shell script. But a missing line
survived three rounds and a written result because nothing in the system was
positioned to notice: no end-to-end test, no selection gate that would have
divided by a reward it never received, no report that rendered, and no
per-edit record of what any change was supposed to accomplish.

The rebuild is organised around making each of those failures loud.
