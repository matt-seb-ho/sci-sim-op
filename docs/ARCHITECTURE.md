# harness-evolve — architecture

Search over *simulator-grounding adapters*: the small set of artifacts wrapped
around a frozen coding agent so it can author a valid simulator input deck.
Successor to `repo3/scripts/self_evolving/`. See `docs/WHY_V1_FAILED.md` for the
evidence that motivated a rebuild rather than a patch.

## The shape of the problem, and why it dictates the design

Five facts about this task drive nearly every decision below. A method that
ignores them will fail here even if it works on a coding benchmark.

1. **The gain is reliability, not quality.** Adapters cut across-run σ by
   roughly an order of magnitude by preventing zero-score terminations. The
   quantity being optimized is the tail.
2. **The tail is two tasks out of ten.** So selection is Pareto over *per-task*
   scores, and the acceptance gate asks "did anything fall off a cliff", not
   "did the mean rise".
3. **Sample-starved.** ~17 search tasks, n≈2 seeds, ~25 min per task-run. Every
   design choice that saves rollouts beats one that improves per-rollout
   quality.
4. **Efficiency is a hard constraint.** An adapter that wins on score while
   inflating tool calls is the over-specification failure mode. It is a gate,
   not a metric.
5. **Which component binds is interface-dependent.** Structural completeness
   binds on GEOS and OpenFOAM; value correctness binds on LAMMPS. So the
   simulator is a plugin and the loop is expected to *discover* what binds.

## Three contracts

Everything plugs into one of these. Nothing else is allowed to be
simulator-specific, harness-specific, or model-specific.

| Contract | Module | Answers |
|---|---|---|
| `SimulatorSpec` | `simulators/base.py` | how to parse, validate, score, diagnose, and contamination-block for *a* simulator |
| `RolloutRunner` | `runners/base.py` | how a candidate is executed on a task — real, cached-replay, or mock |
| `Proposer` | `proposers/base.py` | how a child candidate is produced from a parent plus evidence |

The non-real runners are not conveniences. The **recording** runner appends
every rollout durably as it completes, which makes a 16–37 hour search resumable
after a crash and turns its rollouts into a corpus; the **cached** runner replays
that corpus, which is what makes offline protocol work (compute-matched
baselines, paired statistics, binding-constraint probes) possible for ~$0 — the
statistics are cheap and the rollouts are the expensive part. The **mock** runner
is what makes the search loop testable end to end, which v1 never was.

## The loop

```
        ┌──────────────── archive (Pareto frontier over per-task scores)
        │                        │ select parent
        │                        ▼
        │                  evidence corpus  ← L0 aggregate / L1 per-task /
        │                        │             L2 failure / L3 drill-down
        │                        ▼
        │                    proposer  ── one component + a prediction
        │                        │
        │            free gates  ▼  manifest · budgets · hygiene · plugin tests
        │                        │           (no rollouts spent)
        │                        ▼
        │                     runner  ── anchor slice × n seeds
        │                        │
        │            regression gate  ── no per-task cliff · no new zeros
        │                        │        no aggregate drop · no cost blowup
        │                        │        no cumulative drift from the seed
        └────────────────────────┴──→ decision record (prediction vs outcome)
                                 └──→ validator directives → derived constraints
                                      (fed forward to the next proposal, free)
```

The gate bounds drift against the **seed** as well as the immediate parent:
a sequence of individually acceptable steps can walk reliability downhill, since
each is only ever compared to the step before it. Seed overfitting is the one
thing it cannot bound — selection sees only the search seeds — which is why the
protocol re-scores the winner at held-out seeds before any number is reported.

**Round structure.** One *fixed* anchor slice scores every candidate, so
round-over-round numbers are comparable by construction. A separate probe slice
supplies fresh failure modes to the proposer but is never scored for selection.
The held-out split is touched exactly once, at the end, by the single selected
candidate — alongside compute-matched baselines.

## Package map

```
core/         manifest, candidate, archive, acceptance, decision log, search loop
simulators/   base protocol + geos/ openfoam/ lammps/ mock/
evidence/     layered corpus, per-task diagnostics, EFC, repair directives
hygiene/      contamination gate: filenames, path components, task-id tables,
              blocklist, content overlap, numeric literals, near-miss stems,
              structural fingerprints, rare-token overlap, lookup-table shape
proposers/    base protocol, bounded edits, LLM proposer, model backends,
              expert demonstrations, scripted + random controls
evaluation/   compute-matched baselines, paired and tail statistics, slice
              construction, budget planning, protocol enforcement, reports
runners/      base protocol, subprocess / recording / cached / mock
checks/       check-plugin sandbox and built-ins
```

## Deliberate non-goals

- **The model and the base coding harness stay frozen.** The claim is about
  adapters, and it is what makes the result portable.
- **No bespoke simulator agent.** Adaptation over reconstruction.
- **No open-ended search over whole harness programs.** It needs cheap
  plentiful evaluations we do not have, and the published evidence is that it
  does not reliably beat simple test-time scaling even where they are cheap.
