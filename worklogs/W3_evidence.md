# W3 — evidence corpus, trajectory diagnostics, EFC

Owns `src/harness_evolve/evidence/` and `tests/test_evidence.py`. 43 tests.

---

## What the deficiency actually was

The predecessor proposer received a 2500-character list of tool names with
truncated arguments. Enumerated, that is: no observations, no tool errors, no
validator output, no failure classification, no per-section scores, no reward.
The interesting part is *why* it was that shape — the corpus was assembled by
dumping everything into one global character budget, and once a budget is
global, the only free variable is truncation. The single most consequential
design decision here is therefore not "add more fields"; it is **making L3
fetched on demand for one named task**, which is what allows the global cap to
be deleted rather than raised. `CorpusConfig.max_validator_chars` defaults to
`0` (uncapped) precisely so that a GEOS unknown-attribute error can print its
full table of legal attributes — the highest-quality feedback text the harness
produces, and previously a truncated fragment of one sentence.

## Decisions

**D3.1 — Levels are cumulative, L3 is not a level but a fetch.**
`render(level=2)` is L0+L1+L2 and touches no filesystem. `render(level=3)` with
no task renders a *menu* naming the tasks worth drilling into; the drill-down
itself only happens on `render(level=3, task="X")` / `drill_down("X")`. This
keeps the default prompt small without any truncation anywhere.

**D3.2 — Zero-rate is the headline, sigma is a consequence.**
L0 prints zero-rate first with an explicit `<-- headline reliability quantity`
marker, and prints both a pooled sigma and a mean across-seed sigma. The
architecture's claim is that adapters prevent zero-score terminations; sigma is
downstream of that rate, and a proposer told only sigma will optimise variance
rather than the thing causing it.

**D3.3 — Corpus mean is task-weighted, not rollout-weighted.**
`RoundEvidence.mean` averages per-task means. With n≈2 seeds and occasional
lost rollouts, a rollout-weighted mean silently reweights the objective toward
whichever task got more runs.

**D3.4 — L1 is sorted worst-first, not alphabetically.**
Selection is Pareto over per-task scores and the whole effect is two tail
tasks; the reader's attention belongs at the top of the list.

**D3.5 — Diagnosis is an input, never computed here.**
The corpus consumes `list[Rollout]` + `dict[TaskId, Diagnosis]`, so it is
indifferent to simulator and runner. `diagnostics.diagnosis_from_tree` is
offered as a *helper* for simulator plugins whose scorer produces a recursive
tree, not as a dependency of the corpus.

**D3.6 — The drill-down defaults to the worst seed.**
The best seed explains nothing about a candidate whose failure mode is the
tail. `drill_down(task, seed=...)` overrides.

**D3.7 — A rollout with no logs scores EFC 0, not "absent".**
Same reasoning as failures-as-zero in `Score`: a candidate that produces
nothing must not outrank one that produces something bad.

## Port notes — repo3 `scripts/bottleneck/extract.py`

Good code; two substantive generalisations and three fixes.

- **Simulator-specific counters became `MiningConfig`.** `/geos_lib` prefixes,
  `.rst` reads, `xmllint`/`geosx` command detection, `.xml` output detection
  are now `library_prefixes`, `doc_extensions`, `validator_commands`,
  `artifact_extensions`. These are exactly the counters that stop meaning
  anything on OpenFOAM/LAMMPS, and the interface-dependence finding says the
  loop must be able to run there.
- **Observations became first class.** The original mined *actions only* — it
  never looked at a single tool result. That is the mechanical root of "the
  proposer saw no errors". `mine_trajectory` now also extracts errored tool
  results, stop-hook blocks (detected in the transcript as injected user turns)
  and injected retry prompts, each carrying its **position in the action
  stream**, which is what makes EFC's validity and retention questions
  answerable at all.
- **`trajectory_excerpt` now keeps environment turns.** The original kept
  assistant turns only; the tail of a failed rollout is typically a hook block
  followed by the agent's response, and dropping the block left the reader
  looking at an answer with the question deleted.
- **Surprise 1: `gt_size()` is dead and internally contradictory.** It is never
  called (`worst_subtrees` uses `n_gt_children + 1` directly), it double-counts
  children then subtracts 1 to compensate, and its own comment says "simpler
  approach" mid-function. Dropped.
- **Surprise 2: `_flatten` indexes `node['tag']` unconditionally**, so a
  partially populated detail blob raises — which is exactly the blob you most
  want to diagnose. Now `node.get('tag', '?')`.
- **Surprise 3: nothing in the original ever raised on a missing eval file but
  everything raised on a malformed one.** All parsing here is
  skip-the-bad-line; a truncated final JSONL line is the normal shape of a
  killed 25-minute rollout.

## Contract friction (coded around, not edited)

- `Diagnosis.section_scores` is `dict[str, float]`, so per-section match counts
  (`n_matched` / `n_gt_children` / `n_extra`) have nowhere to live. "0.4 because
  2 of 9 children matched" and "0.4 because attribute values are wrong" call for
  different proposals, so `diagnosis_from_tree` folds those counts into
  `Diagnosis.notes` for the three weakest sections. If W2/W1 ever revisit
  `simulators/base.py`, a `section_detail: dict[str, dict]` field would be the
  right home.
- `Rollout` has no `hook_events_path`. The stop hook writes its own JSONL
  (`decision` / `reason_category` / `retries_so_far`) next to the workspace, so
  `CorpusConfig.hook_events_filename` (default `.verify_hook_events.jsonl`) is
  resolved relative to `Rollout.artifacts_dir`. A dedicated field would be
  cleaner than a filename convention.
- `Rollout.validator_events` is `list[dict[str, Any]]` with no declared schema.
  Both the corpus and EFC accept a union of plausible text keys
  (`message`/`text`/`output`/`detail`/`stderr`/`reason`/`error`) plus
  `source`/`severity`/`location`, which is a superset of `Finding.to_dict()`.
  **Ask for the integrator:** if validator events can carry a step index
  (`index` or `step`), pass it — see the EFC note on terminal feedback below.

---

## EFC — design, and what it honestly is

Basis: arXiv:2605.29682, which defines EFC as a trace-level scaling coordinate
over feedback that is **informative, valid, non-redundant, retained**, reporting
R²=0.99/0.93 where raw compute (tokens, tool calls, wall time) fits near zero.

**Why we want it as an optimization target.** Our task score is one sparse
scalar per ~25-minute rollout across ~17 tasks with n≈2, and the
in-distribution split is at a ceiling — so the objective the search actually
sees is nearly flat. EFC is computable per trajectory from logs we already
write, needs no ground truth, and is dense (tens of feedback events per
rollout). A proposal that makes feedback arrive earlier and land better should
move EFC even on a task whose score cannot move. As far as we know nobody has
used EFC this way; the paper uses it explanatorily.

### The four estimators (all proxies, all from our logs)

| Property | Estimator | Approximation being made |
|---|---|---|
| informative | does the message name a **locatable entity** (quoted identifier, markup tag, attribute key, path, XPath, multi-hump CamelCase), saturating at 2 entities, floor 0.10 | syntactic stand-in for "actionable". Over-credits an irrelevant name; under-credits actionable prose that names nothing. **Length is deliberately not an input** — a 4 kB stack trace naming nothing is less actionable than one line naming the attribute, and rewarding length selects for the wrong harness. |
| valid | did any of the next `validity_window=4` actions **mention the named entity** (in tool name, path, pattern, command, or edit text) | **the weakest of the four.** The paper's construct is whether the feedback was *correct*; we have no per-step oracle, so this measures the agent's *belief*. Confidently-wrong-and-obeyed feedback scores 1.0. Feedback naming nothing gets `validity_unknown=0.5`, not 0 and not 1. |
| non-redundant | geometric decay `0.35^prior` over a signature = (source, digit-stripped whitespace-collapsed first 240 chars). 1st/2nd/3rd identical message → 1.00 / 0.35 / 0.12 | the decay rate is a modelling choice, not a measurement. Digits are stripped so retry counters and line numbers do not make a repeat look novel. |
| retained | first action after vs last action before: different tool or target → 1.0; same target, different args → 0.6; byte-identical repeat → 0.0; **no following action → 0.0** | cannot separate acting *because of* the feedback from acting *coincidentally after* it. |

**Combination.** `efc = Σ_events (informative × valid × novel × retained)`. A
**product** because the paper's definition is a conjunction — an event failing
any one property should contribute nothing however well it does on the others.
**Summed** over events because EFC is used as a scaling *axis*, i.e. extensive.
`harness_efficiency = efc / raw_compute`, basis configurable
(`tool_calls` default, also `wall_minutes`, `output_ktokens`).

`EFCReport` always carries the components, never just the scalar: EFC falling
because the harness stopped emitting feedback, because the feedback went stale,
and because the agent stopped listening are three different bugs with three
different fixes, and only the components tell them apart.

### The consequence the integrator most needs to know

**Terminal feedback is worth exactly zero.** A validator event with no step
index is placed after the final action, so `retained = 0` by construction and
its contribution is 0 — with a note saying so in the report. This is not a bug:
feedback the agent had already stopped listening to cannot have changed
anything it did. The intended reading is that **moving validation inline is
worth more than improving a terminal report**, which is a real and actionable
design lever for the adapter search. If validator runs *do* happen inline, log
them with `index`/`step` and they will be scored positionally.

### How this can be gamed (written down because we intend to guard against it)

1. **Entity-stuffing.** A hook printing "check `<Solvers>`, `<Mesh>`,
   `<Events>`" on every stop maximises informativeness for free. Partial guard:
   novelty decay kills the repeat, so the stuffing must also be *varied* to keep
   paying.
2. **Validity is agent belief.** A hook naming whatever file the agent just
   touched will nearly always be "addressed" by the next action. **This is the
   sharpest hole and nothing here closes it.** Closing it needs a per-step
   score oracle we do not have.
3. **Retention rewards change.** A harness that perturbs the agent into doing
   something different after every message scores high retention. The
   conjunctive product limits but does not eliminate the payoff; the
   `unearned_retention` flag (retention ≥ 0.8 with validity ≤ 0.35) fires on
   exactly this shape.
4. **EFC is a sum**, so many small distinct events beat one excellent one.
   `efc_density` (EFC per event) is reported alongside as the intensive
   companion.

Flags emitted for diagnosis: `no_feedback`, `low_novelty`,
`unearned_retention`, `informative_but_ignored`, `all_feedback_terminal`.

**Therefore: EFC is a search signal only.** Acceptance stays gated on task
score, per-task cliffs, and cost. A candidate whose EFC rises while its score
does not should be read as a suspected gaming case first and a win second. The
tuning constants all live in one `EFCConfig` dataclass so they can be swept;
defaults were chosen to make the *ordering* of trajectories robust rather than
the absolute values meaningful.

## Deliberately not done

- **No calibration of EFC against score.** That is an evaluation-protocol
  question (W5) and needs the cached-rollout corpus. The right first experiment
  is: does EFC rank candidates the same way score does on the runs we already
  have? If it does not, the constants are wrong or the proxies are.
- **No LLM in the evidence path.** Every level renders deterministically from
  logs. An LLM summariser would reintroduce the failure mode this workstream
  exists to remove — an unauditable lossy compression between the run and the
  proposer.
- **No caching of mined trajectories to disk.** `RoundEvidence` caches
  in-process only. If drill-down IO becomes hot, that is a runner concern.
- **No `tool_calls.json` sidecar support.** repo3's extractor read one for
  primer/RAG call counts; those quantities are adapter-specific and belong in
  `Cost`, which the runner already populates.
- **No per-turn token accounting.** `output_tokens` is read opportunistically
  from a `result` event or per-message `usage`; when absent it is 0 and the
  `output_ktokens` efficiency basis degrades to 0 rather than lying.

## Open questions

1. Should `retention` credit a *thinking* block that quotes the feedback but is
   followed by no action? Currently no (retention 0). Arguably reading is
   retention; measurably it is indistinguishable from ignoring.
2. `validity_window=4` is a guess. Long-horizon feedback ("your Mesh block will
   fail later") is legitimately acted on ten actions later and scores as a miss.
3. The novelty signature is exact-ish after digit-stripping. Two *semantically*
   identical schema errors phrased differently (different element names, same
   root cause) count as fully novel. A cheap fix would be to key on the entity
   set instead of the text when entities are present — worth trying once there
   is a corpus to check it against.
4. Whether `RoundEvidence` should carry the probe-slice rollouts separately
   from the anchor slice. Right now a caller passing both would get them mixed
   into one corpus; the round structure says probe rollouts must never be
   scored for selection. Flagging for W1 — this may want a `slice` field on
   `Rollout` or two corpora per round.
