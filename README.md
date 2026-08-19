# harness-evolve

Search over **simulator-grounding adapters**: the small set of always-visible
artifacts wrapped around a *frozen* coding agent so it can author a valid input
deck for a scientific simulator.

The adapter is a primer, a procedural-memory cheatsheet, a set of negative
constraints, a termination policy, and some checks. The model and the base
coding harness do not change. Only the adapter moves.

```bash
python3 scripts/evolve.py demo        # full search on a mock simulator, ~30s, $0
python3 scripts/evolve.py preflight   # what would make a real run meaningless
```

## Start here

| If you want to know | Read |
|---|---|
| how the pieces fit together | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| why the previous system failed, and what each design decision answers | [`docs/WHY_V1_FAILED.md`](docs/WHY_V1_FAILED.md) |
| what the literature actually says as of Aug 2026 (60 verified papers) | [`docs/LITERATURE_2026-08.md`](docs/LITERATURE_2026-08.md) |
| what must change elsewhere before a real run means anything | [`docs/INTEGRATION_REQUIREMENTS.md`](docs/INTEGRATION_REQUIREMENTS.md) |
| the first result, and why its two views disagree | [`docs/EXPERIMENT_01_proposer_control.md`](docs/EXPERIMENT_01_proposer_control.md) |
| how any of this was decided | [`worklogs/`](worklogs/) |

## The five facts that determine the design

A method that works on a coding benchmark can fail here for reasons specific to
this task. Nearly every choice in this repository traces to one of these.

1. **The gain is reliability, not quality.** Adapters cut across-run variance by
   roughly an order of magnitude by preventing zero-score terminations. The
   quantity being optimised is the tail, so selection is Pareto over *per-task*
   scores and the acceptance gate asks "did anything fall off a cliff", not "did
   the mean rise".
2. **The tail is two tasks out of ten.** A cell mean at small n cannot
   distinguish rescuing the tail from getting lucky on it, so every comparison
   is paired and per-task, and tail statistics are reported as first-class.
3. **Severely sample-starved.** ~17 search tasks, 2–3 seeds, ~25 minutes per
   task-run. A design that saves rollouts beats one that improves per-rollout
   quality. Hence gated screening, free gates before paid gates, and constraints
   *derived* rather than proposed-and-tested.
4. **Efficiency is a hard constraint, not a metric.** An adapter that wins on
   score while inflating tool calls is the over-specification failure mode. It
   is an acceptance clause.
5. **Which component binds is interface-dependent.** Structural completeness
   binds on some simulators, value-correctness on others. So the simulator is a
   plugin (`SimulatorSpec`) and the loop is expected to discover what binds
   rather than be told.

## Three contracts

Everything plugs into one of these. Nothing else may be simulator-, harness-, or
model-specific.

- **`SimulatorSpec`** — parse, validate, score, diagnose, contamination-block.
  Adding a simulator is implementing one class.
- **`RolloutRunner`** — real / cached-replay / mock, behind one interface. The
  cached runner makes offline protocol work possible for ~$0; the mock runner
  makes the search loop testable end to end.
- **`Proposer`** — one bounded edit per call, with a prediction attached.

## What is unusual here

**Constraints are derived from the validator, not guessed.** Every
verifier-grounded method in the literature consumes a *pass/fail* verifier. A
scientific simulator gives more: rejecting a deck, GEOS prints the full table of
valid attributes, or the ~50 legal solver types, or the set of names actually
defined. It names the **correct action space at the point of failure**.

`evidence/directives.py` mines that. A negative constraint can be derived from
what the simulator already said instead of proposed by a model and then paid for
with a full evaluation round — at zero rollout cost, correct by construction, and
with no contamination risk of the usual kind, since it comes from the checker's
schema rather than a ground-truth deck.

**Every edit is a falsifiable contract.** A proposal states which tasks it
expects to help and by how much, before evaluation. The decision log verifies it
next round and reports proposer calibration, cycling rate, and *unearned* edits —
accepted changes whose named beneficiaries did not move, which is
over-specification in disguise.

**The null result is a first-class outcome.** Published evidence predicts a
search in this regime returns its seed. That is pre-registered as a kill
criterion rather than something to discover later, and `mechanism_only` is a
verdict the report can render.

## Layout

```
src/harness_evolve/
  core/         manifest, candidate, archive, acceptance, decision log, search
  simulators/   base protocol + geos / openfoam / lammps / mock
  evidence/     layered corpus, diagnostics, EFC, repair directives
  hygiene/      contamination gate — 11 rules, blocking, run before any rollout
  proposers/    bounded edits, LLM proposer, scripted + random controls
  evaluation/   compute-matched baselines, paired statistics, slices, reports
  runners/      mock / cached / subprocess
  checks/       check-plugin sandbox and built-ins
scripts/        evolve.py CLI, experiments
tests/          401 tests, offline, ~4s
```

## Status

Runs end to end on the mock simulator. **No real run has happened**, and
`preflight` will tell you why: the ground-truth tree is not mounted here, and the
container currently drops the two environment variables that carry the stop
policy — so a search would vary a knob nothing reads. Both are recorded in
`docs/INTEGRATION_REQUIREMENTS.md` with the tests that settle them.

```bash
python3 -m pytest tests/ -q
```
