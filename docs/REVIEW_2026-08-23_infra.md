# Independent review — correctness, over-engineering, infrastructure

**Date:** 2026-08-23 · **Scope:** whole repository, read-only · **Process and limits:** `worklogs/W8_review.md`

The brief was to find what is wrong. Nothing below is a compliment. **CONFIRMED**
means a reproduction exists and is quoted; **SUSPECTED** means I could not
demonstrate it and I say what would settle it. The confirmed list is not padded
— things I expected to be broken and are not are listed in the worklog so nobody
re-checks them.

### Two framing notes

**The working tree moved throughout the review — it is not a stable target.**
Another process was writing to this repository while I read it:

| time | state |
|---|---|
| 17:34 | 453 passed, 2 skipped (my baseline) |
| 17:38-17:43 | `evolvers/` (~870 lines), `evaluation/amortization.py` (693), `evaluation/zero_marginal.py` (396) and a modified `report.py` appear, untracked and untested |
| 17:44 | **452 passed, 2 failed** — the pass-10 documentation guard catching `evolvers/` missing from both package maps |
| 17:56 | 520 passed, 2 skipped; `tests/test_evolvers.py` added, package maps fixed, `amortization`/`zero_marginal`/`report` committed |

So the red window closed on its own. Two things survive it. First, ~1 950 lines
landed with no tests and stayed that way for at least six minutes of a repository
whose founding thesis is that the predecessor failed because nothing was tested
— that is a process observation, not a bug, and it is in §5. Second, **every
finding below was re-verified against the tree as of 17:56 and every one still
reproduces**; the concurrent work touched none of them.

**The one sentence that matters.** Six independent mechanisms in this repository
each convert an *infrastructure or plumbing* failure into an *adapter result*,
or into silence, without saying so: **F1, F2, F3, F7, F21, and the absence of any
circuit breaker (§4.3)**. That is the predecessor's failure — a dead channel
nobody noticed — reproduced six times inside a system built specifically to make
it loud. Everything else here is smaller than that.

---

# 1. CRITICAL

## F1 — The derived-constraint mechanism has no input. Its channel was never wired. **CONFIRMED**

`runners/subprocess.py:223-259` and `:383-396`; `core/search.py:223-228`.

The README calls this the contribution: *"Constraints are derived from the
validator, not guessed … `evidence/directives.py` mines that."* The worklog
calls it *"the gap … what I built for it"* and *"a mechanism we can
demonstrate"*. `GeosSimulator.validate()` (`simulators/geos.py:937-1012`) runs
`geosx -i <entry> --validate-input` and returns the full stderr — the attribute
tables, the ~50 legal solver types — verbatim in a `Finding`.

**No runner ever calls it.** `SubprocessRunner.run()` calls
`score_result_dir` → `spec.score`. It never calls `spec.validate` or
`spec.parse`. `Rollout.validator_events` is populated from exactly one place:

```python
def collect_validator_events(self, result_dir):
    path = Path(result_dir) / ".verify_hook_events.jsonl"
```

— the **stop-hook decision log** (`decision`, `reason_category`,
`retries_so_far`, `detail`; schema visible at `runners/mock.py:660-688`). So
`Search._observe_directives` feeds `ConstraintLedger` a stream of hook verdicts,
not GEOS validator output. `grep -rn "validator_events" src/harness_evolve/
{runners,simulators}` confirms: nothing bridges `Finding` → `Rollout`.

**How this fails.** Not with an error. `ConstraintLedger.summary()` renders
`"0 directive(s) over N round(s), 0% naming an action space"` — which
`worklogs/00_OVERALL.md` explicitly designates as the honest signal that *"the
verifier only emits verdicts"* and that *"the honest response is to stop claiming
the mechanism applies to it"*. The number a wired-but-inapplicable simulator
produces is byte-identical to the number an unwired one produces. The demo
already prints it: `validator constraints: 0 directive(s) over 17 round(s), 0%
naming an action space`.

**Why it matters here.** This is the claimed novel contribution, its
zero-rollout-cost economics are the argument for the whole design, and
`docs/RUNBOOK.md` step 3 — *"verify the validator actually emits repair
directives … if `actionable_fraction` reads 0%, the mechanism does not apply to
this build and should not be claimed"* — will read 0% for a reason that has
nothing to do with the build, and will be believed.

**Fix.** In `SubprocessRunner.run`, after scoring, call
`self.spec.validate(self.spec.parse(inputs_dir), inputs_dir)` and attach
`[f.to_dict() for f in findings]` to the rollout, in a field distinct from the
hook events (`validator_findings`). Add an assertion in `Search` that a runner
declaring `produces_validator_events=True` actually produced some.

---

## F2 — The evaluation module cannot tell a scorer crash from a bad deck, and will manufacture the exact headline this project expects **CONFIRMED**

`evaluation/stats.py:176-187` (`from_rollouts`), `:880-915` (`tail_stats`).

`grep -n "status" evaluation/stats.py` returns nothing. The module never reads
`Score.status` or `Rollout.error`. Every `0.0` is a deck the agent failed to
author. But `0.0` is also `no_workspace`, `empty_workspace`, `no_ground_truth`
and `scorer_error` (`runners/subprocess.py:329-350`) and `missing_ground_truth`
(`simulators/geos.py:1030`) — Docker, disk, path-config and scorer-crash events.

**Reproduction.** Two arms scoring 0.86 everywhere, differing *only* in two
baseline runs whose scorer crashed:

```
rescues        : rescued 2 ['t8','t9'], lost 0 []
mean delta     : 0.0573
wlt            : 2W / 0L / 8T at noise band ±0.0100
zero-rate delta: -0.0667
```

That is, line for line, "the entire held-out effect was 2 catastrophic-failure
rescues out of 10 tasks" — produced by two infrastructure faults and zero
adapter effect. `Comparison.to_dict()` carries no field a reader could use to
notice.

**Why it matters here.** The claimed effect *is* two tasks out of ten. Two
misattributed infra faults are the whole claim. Over 60 hours against a Docker
daemon, a handful of them is the expected case, not the tail.

**Fix.** Partition in `from_rollouts` on `r.error is not None or r.score.status
not in ("success","ok")`; carry `infra_failures` on `ArmScores`; report
`infra_failure_runs` beside `zero_runs`; make `rescue_ledger` **raise** if any
rescued/lost task has an infra failure on either side. The docstring's "nothing
is filtered here" is right about adapter failures and wrong about harness
failures — those are missing data, not zeros.

---

## F3 — GEOS scores an unparseable deck as `status="success"` with a plausible non-zero value **CONFIRMED**

`simulators/geos.py:160-201` (`load_and_resolve_dir`), `:1014-1050` (`score`).

`load_and_resolve_dir` parses every `*.xml`, **discards** the failures
(`parse_errors` is dropped unless *nothing* parsed, line 180), then picks the
entry as "the parsed file nothing else includes". If the main deck is malformed
it is not in `parsed`, so nothing references the auxiliaries, so an auxiliary
becomes the entry and is scored as the whole deck.

**Reproduction** (`/tmp/hrev/t_geos.py`) — one malformed 5-section `main.xml`
plus a 1-element `materials.xml`:

```
A. correct deck            -> value=1.0   status='success'
B. entry deck MALFORMED    -> value=0.2   status='success'
   parse_errors seen by parse(): ['main.xml']
```

The information exists — `parse()` records `main.xml` — and `score()` never
consults it.

**Why it matters here.** `types.py:71-80` and `geos.py:1016` both promise that
an unparseable deck is 0.0 with a distinct status, *"because the rate of these
is the quantity the whole reliability story is about"*. Scored 0.2 instead of
0.0 it is not counted as a zero, so the zero rate — which the acceptance gate,
the tail statistics and the entire reliability claim rest on — is
**undercounted in the flattering direction**. The mock cannot surface this; it
has no XML.

**Fix.** `score()` calls `parse()` first and returns
`Score(0.0, status="parse_error")` if any file the deck would be built from
failed. A partially-parsed workspace is not scorable.

---

## F4 — `Candidate.cid` embeds the parent, so byte-identical candidates never collapse. The rollout cache and the duplicate check both miss. **CONFIRMED**

`core/candidate.py:108-116`; `core/manifest.py:293-296` writes `parent` and
`generation` into `[meta]`, and `cid` hashes `manifest.to_toml()`.

```
root   files {'PRIMER.md': 'A'} cid cand_cb2a9f2eb9dd
revert files {'PRIMER.md': 'A'} cid cand_b58cc2a2af54
byte-identical content, same cid? False
identical content from different parents: True   same cid? False
```

This contradicts the class docstring (`:93-95`, *"identical candidates collapse
in the archive and the evaluation cache"*), and breaks three consumers:
`runners/cached.py:224` and `runners/recording.py:174` key on `cid`;
`core/search.py:407` skips duplicates by `cid`.

**Why it matters here.** The case it breaks on is exactly the one
`core/decision.py` goes to the trouble of detecting — `EditType.REVERT`,
cycling back to previously held content — which arXiv:2605.20086, cited in the
worklog, puts at **~30% of lines added during evolutionary search**. Each miss
costs a full anchor evaluation: 6-8 tasks × 2 seeds × 25 min ≈ **5-7 hours**.
At the recommended 9-21 candidates that is a large fraction of the entire
budget, spent re-measuring something already on disk. It is also the single
cheapest fix in this document.

**Fix.** Hash content only: the component files plus a canonical serialization
of the manifest **excluding** `[meta]`. Keep provenance in `metadata()`, not in
identity. (Same script confirms `materialize` → `from_dir` is not identity
either: `materialize` at `:250` appends a trailing newline, so a reloaded
candidate has different content and a third cid.)

---

## F5 — The cumulative-vs-root clause is a mean-based cliff test with no noise tolerance, and it is the clause that actually binds **CONFIRMED**

`core/acceptance.py:216-243`.

Integration pass 1 found a mean-based per-task cliff test *"rejects nearly every
candidate, including genuine improvements"* and fixed it — the per-step clause
got `_is_noise` / `_zero_is_noise`. The root clause added in pass 4 has **no
such tolerance**: it compares seed *means* against a flat `-0.10`. One
stochastic zero at one of two seeds is a mean drop of ~0.45, so the root clause
fires on it unconditionally.

The docs call the root bound "looser" (0.10 vs 0.05). In raw magnitude, yes; in
effect, no. The per-step clause forgives an intermittent zero and the root
clause cannot, so **the root clause is strictly binding and all the noise
tolerance beneath it is dead weight.**

**Reproduction** (`/tmp/hrev/t_gate3.py`) — a child that genuinely rescues the
root's tail task at both seeds and draws one unlucky zero elsewhere:

```
ACCEPTED: False | ['cumulative regression vs seed on t2: -0.440 (limit -0.100)']
per-step verdict: tolerated_as_noise=['t2']  new_zero_tasks=[]
TRUTH: zero-terminations 1/12 -> 1/12. Rescued the tail. Rejected.
```

False-rejection rate for a candidate *behaviourally identical* to the root,
6 anchor tasks × 2 seeds:

| per-rollout zero rate | rejected by the root clause |
|---|---|
| 2 % | 21.5 % |
| 5 % | 46.3 % |
| 10 % | 72.0 % |

**Visible in the shipped demo.** `scripts/evolve.py demo` prints
`rejections: cumulative regression vs seed on task_2=2, aggregate regression=2,
cumulative regression vs seed on task_4=2, …` — four of eight decisions killed
by this one clause, with reason strings that read as real regressions.

**Why it matters here.** At 9-21 candidates, discarding 20-70 % of them on coin
flips is most of the budget. Worse: the pre-registered kill criterion is *"the
search returns its seed"*. A gate that rejects everything by noise produces
exactly that outcome, indistinguishable from the real one. This is the worst
available confound for the headline result.

**Fix.** Give the root clause what the parent clause has: best-of-seeds for the
cliff term, zero *rates* for the reliability term. `_is_noise` and
`_zero_is_noise` already exist — call them with `root_by_seed`.

---

## F6 — The 16-37 hour plan assumes four concurrent rollouts. Nothing here can run two. **CONFIRMED**

`evaluation/budget.py:199-210`:

```python
def estimate_cost(rollouts, *, usd_per_rollout=0.066, minutes_per_rollout=25.0,
                  workers: int = 4):
    "wall_hours": rollouts * minutes_per_rollout / 60.0 / max(workers, 1),
```

`workers=4` is an undocumented default. Meanwhile `runners/base.py:60` —
`run_many` is a sequential list comprehension; `core/search.py` is a single
`while` loop; `runners/subprocess.py:314` hardcodes `"--workers", "1"`;
`runners/recording.py:143` appends without a lock and is not concurrency-safe
anyway.

Real sequential wall-clock: **150 rollouts = 62.5 h** (quoted 16 h);
**350 rollouts = 145.8 h — six days** (quoted 37 h).

The figure is cited as fact in `docs/ARCHITECTURE.md:41`, `docs/RUNBOOK.md:32-34`
(the table step 1 tells you to plan against), `runners/recording.py:5` (that
module's entire justification), and four times in `worklogs/00_OVERALL.md`.

**Why it matters here.** It is a 4× error in the one number that decides whether
the experiment is attemptable, and it changes every downstream decision —
checkpointing, resume design, whether 350 rollouts exists at all.

**Fix.** Implement concurrency (thread-pooled `run_many`, `--workers N`,
per-worker `adapter_root`, sharded corpus) or set `workers=1` and republish the
table. Do not leave a default that quietly divides the answer by four.

---

# 2. HIGH

## F7 — The GEOS directive regexes drop, merge and corrupt real validator output — silently **CONFIRMED**

`evidence/directives.py:137-165`.

Every pattern terminates its `alternatives` group with
`(?=\n\s*\n|\n\s*(?:Error|Warning|Fatal)\b|\Z)`. Real GEOS emits neither: it
uses `***** ERROR` / `***** LOCATION:` banners and appends *"For more details,
please refer to documentation at:"* directly after the attribute table.

**Reproduction** (two consecutive unknown-attribute errors in banner form):

```
directives parsed: 1     (expected 2)      <-- second error silently lost
context   : ''                              <-- attribution lost
n_alts    : 35                              <-- 7 real + 28 garbage
alts: (...,'For','more','details','please','refer','to','documentation','at:',
       'ERROR','LOCATION:','Rank','XML','Node','Problem.xml','l.42','contains',...)
nearest   : attribute                       <-- an English word, not a GEOS attribute
```

Four failures, all silent:

1. **Second and later errors in one stderr are swallowed** by the first match's
   `.+?` and never re-scanned. Rollouts routinely produce several errors; you
   would mine one.
2. **`entry["valid"]`** — the machine-readable legal-action-space list, the
   whole point of the mechanism — is mostly prose.
3. **`Problem.xml`, a deck filename, lands in the constraint prose injected
   into the proposer prompt** (`proposers/llm.py:235-240`), one line below
   system rule 4 ("NEVER NAME A FILE"). That is a leak surface the hygiene gate
   never inspects, because derived constraints bypass it.
4. **`context` is lost.** `(?:XML Node\s+(?P<context>\S+)\s+)?` needs exactly
   one non-space token before `contains`; real output is
   `XML Node Solvers/SinglePhaseFVM (Problem.xml, l.15) contains …`. So
   `entry["tag"]=""` and the ledger key `(kind, "", offender)` **merges the same
   attribute name across different elements, inflating support** past
   `min_support`.

**Fix.** Split the blob into error records first (on `^\*{2,}\s*(ERROR|WARNING)`),
then match within a record; terminate the alternatives list at the first line
that is not list-shaped; make `context` tolerate a trailing parenthetical. Above
all, add a loud counter: error-shaped lines seen vs directives extracted, and
warn when they disagree. A 90 % parse failure is currently invisible.

---

## F8 — Three drifted key lists mean the constraint channel can be dead while the corpus looks alive **CONFIRMED**

`evidence/directives.py:199`, `evidence/corpus.py:576`, `evidence/efc.py:99` —
three modules read the same validator payload through three different key
tuples.

```
key=message    directives=1  efc_events=1  corpus_shows_text=True
key=reason     directives=0  efc_events=1  corpus_shows_text=True
key=output     directives=0  efc_events=1  corpus_shows_text=True
key=text       directives=0  efc_events=1  corpus_shows_text=True
key=error      directives=0  efc_events=1  corpus_shows_text=True
key=feedback   directives=1  efc_events=0  corpus_shows_text=False
```

If the hook writes under `reason`/`output`/`text`/`error`: L3 renders the
validator text verbatim (so a human eyeballing the evidence concludes the
channel is live), EFC scores it, and the ledger mines **zero** — reported as
`"0% naming an action space"`. Combined with F1 this is two independent ways for
the same number to lie, in the same direction.

`ConstraintLedger.observe` returns a count that `core/search.py:226-228`
discards.

**Fix.** One shared `validator_text(payload)` helper in `evidence/`, used by all
three. Make "this round had validator events and produced zero directives" an
explicit logged warning.

---

## F9 — The advertised free gates are not wired into the loop **CONFIRMED**

`core/search.py` — the only free gate `Search` runs is hygiene (line 413).
`docs/ARCHITECTURE.md`'s loop diagram states
`manifest · budgets · hygiene · plugin tests   (no rollouts spent)`.

- **`child.validate()` is never called by `Search`.** Line 350 validates the
  seed only. With it goes `check_budgets()`, described at
  `core/candidate.py:194-197` as *"the structural fix for the over-specification
  failure mode … which the v1 lineage exhibits"*. Validation is left to the
  proposer; the `Proposer` protocol does not require it. Any proposer that skips
  it sends a budget-violating candidate straight to paid rollouts.
- **`checks/sandbox.py` has no caller.** `grep -rn "vet_plugin\|vet_plugins\|
  load_vetted_plugins" src/ scripts/` matches only the re-export in
  `checks/__init__.py`. 374 lines of module plus 503 lines of test, gating
  nothing.
- **`RegressionGate.evaluate(..., checks_ok=True)`** is never passed a value, so
  the "check plugin failed its own test" clause is unreachable.

At 25 min/rollout, discovering a token-budget violation costs a five-hour anchor
evaluation instead of a `len()`.

**Fix.** After `proposer.propose` returns, wrap `child.validate()`; on
`CandidateError`, record and `continue`. Either wire the sandbox or delete it
(§3).

---

## F10 — The runtime block list and the hygiene gate have already drifted, exactly as the module docstring warns **CONFIRMED**

`simulators/geos.py:757-775` vs `hygiene/corpus.py:50-68`.

`hygiene/corpus.py`'s own docstring: *"so the runtime gate and the hygiene gate
cannot drift apart. The predecessor system had them as two independent lists and
the drift is exactly how `.geos` dependency filenames reached a shipped
adapter."* They are two independent lists.

| | `simulators/geos.py` | `hygiene/corpus.py` |
|---|---|---|
| `VARIANT_SUFFIXES` | 9 | 19 |
| missing from geos | — | `_verification _fim _sequential _hybrid _benchmark_base _benchmark_fim _smoke_base _smoke_fim _smoke_sequential _base_hybrid` |
| `GENERIC_STEMS` | 7 | 15 |
| min stem length | **10** | **8** |

**Reproduction** (`/tmp/hrev/t_drift2.py`) — does the runtime gate hide the
sibling the hygiene gate calls the same family?

```
ThermalPoroMech_fim.xml        vs ThermalPoroMech_sequential.xml        -> runtime: NO
DruckerPragerWellbore_base.xml vs DruckerPragerWellbore_verification.xml -> runtime: NO
CO2InjectionFlux_smoke_fim.xml vs CO2InjectionFlux_benchmark.xml         -> runtime: NO
PoroElasticWellbore_base.xml   vs PoroElasticWellbore_benchmark.xml      -> runtime: YES
```

Three of four realistic GEOS patterns: the agent can read the sibling deck at
rollout time, and the hygiene gate — which only inspects adapter *text* — never
sees it. VaG (2608.05810), cited in the worklog, is the finding that skill
contamination is structurally irreversible, so pre-commit is the only gate that
works. This is a pre-commit gate with a hole in the half nobody re-checks.

**Fix.** Delete `geos.VARIANT_SUFFIXES`, `GENERIC_STEMS`, `MIN_STEM_LENGTH` and
`variant_stem_keys`; import `stem_keys` from `hygiene.corpus`. Add a test that
fails if the constant is defined twice.

---

## F11 — `LLMProposerConfig` is silently ignored: the proposer does not run the model you configured **CONFIRMED**

`proposers/llm.py:120-131, 185-189`.

```
configured model : claude-opus-5   | backend actually used: gemini-3-flash-preview
configured url   : https://my-proxy/...  | backend url: https://openrouter.ai/...
configured max_tok: 64000 -> 4000 | temp: 0.0 -> 0.8 | timeout: 900 -> 300.0
```

`_backend_caller` calls `default_backend()`, which builds `OpenRouterBackend()`
with **its own** defaults. Five config fields — `model`, `api_url`,
`max_tokens`, `temperature`, `timeout_s` — are dead unless the caller hand-builds
a backend.

**Why it matters here.** The method section will say "the proposer model was X".
It will be wrong, and nothing in the decision log records what actually ran.
`proposers/llm.py:142-170` `call_openrouter` is dead code (zero callers) that
duplicates `OpenRouterBackend.__call__` with drifted defaults (`max_tokens`
2000 vs 4000).

**Fix.** Have `_backend_caller` construct the backend **from** the config, or
delete the transport fields. Record the resolved backend `name`/`model` into
the decision log so the run self-documents.

---

## F12 — `GateConfig.severity_overrides` does not reach the sources the rules emit **CONFIRMED**

`hygiene/gate.py:841-846` matches `f.source not in cfg.severity_overrides` by
exact string. `rule_filenames` (`:277-281`) emits `"filename"` **or**
`"filename_generic"`; `rule_task_ids` (`:350-368`) emits `"task_id"` **or**
`"task_id_table"`. `ALL_RULES` registers only the first of each, and its own
comment says the key is the *"`Finding.source` prefix"*.

```
source=filename            severity=warn     <- applied
source=filename_generic    severity=error    <- not applied  (x3)
source=task_id_table       severity=error    <- not applied
still BLOCKED: True
```

**Why it matters here.** `docs/RUNBOOK.md` step 4: *"raise thresholds rather
than disabling a rule — a gate people route around is worse than no gate."*
`filename_generic` is a blocking rule with **no threshold**; the override map is
its only knob, and it does not work. `unknown_filename_severity` defaults to
`"error"` and fires on any `*.xml`/`*.geos` token, which a legitimate GEOS primer
will contain. Step 4 will fail and the only sanctioned remedy will not work.

**Fix.** Match by prefix; apply overrides *before* `_cap`, not after.

---

## F13 — The subprocess timeout equals the harness's own timeout, and firing it orphans the container **CONFIRMED by reading**

`runners/subprocess.py:232` passes `cfg.timeout_s` to `_run_command`; `:313`
passes `str(int(cfg.timeout_s))` to `run_experiment.py --timeout`. Identical.

1. **Every inner timeout becomes an outer kill.** The outer clock also covers
   container startup, so it expires first. The harness is killed before writing
   `status.json` or flushing the workspace, `score_result_dir` finds no
   `inputs/`, and returns `0.0 / no_workspace`. A partial deck worth 0.6 is
   recorded as a catastrophic termination — which, given F2, then flows into the
   tail statistics as an adapter failure.
2. **`subprocess.run(timeout=…)` kills only the direct child.** The `docker run`
   grandchild survives, holding CPU and writing into `results_root`. Nothing
   here reaps it, and there is no disk guard on `adapter_root` or `results_root`
   (a full scaffolding copy per candidate × seed, never cleaned).

**Fix.** Outer = inner × 1.2 + 300 s. `start_new_session=True`, kill the process
group. Name the container and `docker rm -f` in a `finally`. Clean
`adapter_root` after a candidate's last rollout.

---

## F14 — `decide()` resolves ledger arms by the wrong key and silently drops the arm **CONFIRMED**

`evaluation/report.py:278-283`; producer `evaluation/baselines.py:774-790`.

`run_matched_suite` returns comparisons keyed `seed_control`,
`best_of_k_oracle`, `best_of_k_validator`, `sequential_refinement`, but records
ledger arms `control`, `best_of_k`, `sequential_refinement`. `matches.get(key)`
misses; the `m is None` branch appends to `unmatched` and `continue`s **without
appending a reason**, so the arm vanishes with no explanatory line.

**The dangerous direction:** a best-of-k arm that genuinely spent 90 rollouts
(ratio 1.00×, matched) and **beat** the adapter 0.95 vs 0.80 is dropped because
its key is `best_of_k_oracle` and the ledger says `best_of_k`. A weaker,
correctly-named baseline is counted instead, and the verdict renders `survives`.

**Why it matters here.** Budget-matched baselines are the one control separating
"the adapter helped" from "the adapter arm had more compute" — the error
`WHY_V1_FAILED.md §2` exists to prevent and 2607.12227 is cited for. Defeated by
a string mismatch. `tests/test_evaluation.py:569-574` hand-writes an aligned
ledger, which is why it has never fired.

**Fix.** `BaselineResult.ledger_arm: str`, set from `arm_key`, read by
`decide()`. An unresolvable arm must **raise**. Build the fixture from
`run_matched_suite`.

---

## F15 — The permutation test holds non-mover deltas as an unpermuted constant, and reports p-values below its own stated floor **CONFIRMED**

`evaluation/stats.py:596-644`. `fixed_sum = sum(d for d in deltas if abs(d) <=
noise_band)` is added to every permuted statistic and never sign-flipped, so the
null is centred on `fixed_sum/n` rather than 0 while `_extreme` applies a
symmetric `|stat| >= |observed|` rule. Neither the sign-flip test (permute all
n) nor the Wilcoxon convention (drop zeros from the sum *and* n).

`deltas = [0.005]*8 + [0.4, 0.3]`, band 0.01:

```
module p          = 0.25
module min_achv_p = 0.5    <- its own floor, violated by its own p, in the same render
reference exact sign-flip over all 10 = 0.00195
```

The rendered string is `p = 0.2500 (exact, 2/10 tasks moved) — **underpowered**:
the smallest p this design can produce is 0.500`. Same contradiction at m=1.
With `noise_band=0` the module agrees with an independent reference exactly — the
bug is entirely `fixed_sum`.

**Fix.** Enumerate all n (~2 s at n=20; n is 10-17 here). Delete `movers`,
`fixed_sum`, `m`, the Monte-Carlo branch and the `resamples`/`seed`/
`exact_max_movers` parameters; `min_achievable_p = 2/2**n`.

---

## F16 — A single-seed cell contributes a fabricated SD of 0.0 to the noise band **CONFIRMED**

`evaluation/stats.py:206-208` (`seed_sd` returns 0.0 at n=1),
`:1054-1058` (`noise_band_from_seeds` guards only that *some* task is
multi-seed, then medians over *all* tasks).

5 tasks at 3 seeds with SD 0.1 plus 6 tasks at 1 seed → observed median SD
**0.0000**, band collapses to the 0.01 floor. All-3-seed gives 0.20. A **20×**
understated band, in the direction that converts jitter into wins, triggered by
the thing that actually happens: a few cells whose reruns died.

**Fix.** Median over multi-seed tasks only; fall back to `DEFAULT_NOISE_BAND`
when fewer than half are multi-seed. Better: return `None` at n=1 so
"unobserved" cannot read as "zero".

---

## F17 — The noise-band guard is one keyword away, and the file written to check the arithmetic from outside disables it in 8 of 15 tests **CONFIRMED**

`evaluation/stats.py:1172-1177`, `:409-418`, `:540-541`. On the project's own
tail fixture:

| | derived band (0.01) | `noise_band=0.0` |
|---|---|---|
| bootstrap | **refused**, "only 2 of 10 tasks moved" | `95 % CI [-0.0002, +0.2418]` |
| `n_movers` | 2 | 7 |
| permutation | `p=0.5000`, **underpowered** | `p=0.4062`, `underpowered=False` |

The refusal the module docstring calls its reason for existing evaporates, and
`underpowered` flips to `False` — so a non-rejection resting on 2 real movers is
reported as a *powered* one, i.e. as evidence of absence. The CI lands 0.0002
from excluding zero.

`tests/test_stats_verification.py` — whose docstring says it exists because
*"'the tests pass' and 'the arithmetic is right' are different claims when the
same author wrote both"* — passes `noise_band=0.0` in 8 of 15 tests, which is
exactly the setting where F15's bug is invisible.

**Fix.** `band = max(supplied, MIN_NOISE_BAND)`; `noise_band=0.0` raises. Record
`min_n`/`min_movers`/`noise_band` in `BootstrapResult.to_dict()`.

---

## F18 — `compare()` accepts arms with different seed counts; `from_rollouts` double-counts a resumed rollout **CONFIRMED**

`evaluation/stats.py:280-304`, `:176-187`. `paired_deltas` checks task sets and
nothing else, so a 3-seed baseline against a 1-seed treatment runs silently and
every tail statistic compares different denominators. `from_rollouts` keys only
on `r.task`, so a re-emitted `(task, seed)` double-counts:
`[(t1,s1,0.9),(t1,s1,0.9),(t1,s2,0.1)]` → mean 0.633 instead of 0.5.

The second one is not hypothetical: `RecordingRunner` exists to make runs
resumable, and its within-run deduplication is advertised as a feature. The
corpus is *expected* to contain repeated keys, and the module that reads it
cannot handle them.

**Fix.** Key on `(task, seed)`; raise on a conflicting duplicate. Require equal
per-task seed counts, or record the imbalance on `Comparison`.

---

## F19 — EFC scores the task prompt as harness feedback, worth a perfect 1.000 on every rollout **CONFIRMED**

`evidence/diagnostics.py:702-709` + `evidence/efc.py`. Any `user`-role text
block not matching `_HOOK_MARKER_RE` becomes `FeedbackEvent(source="injected")`
— and the first user turn of every run *is the task prompt*.

```
EFC: 1.0 n_events: 1
  [0] injected I=1.00 V=1.00 N=1.00 R=1.00 -> 1.000  Author a GEOS deck for a poroelastic problem...
```

It scores the maximum a single event can contribute: informative (names
entities), valid (the agent's next call touches them), novel (first), retained
(no preceding call ⇒ `retention_changed`, `efc.py:335-337`). **A rollout in which
the harness gave the agent nothing reports EFC 1.0 with no `no_feedback` flag.**
Since EFC then varies with prompt wording, it varies by *task*, not by adapter —
exactly backwards for a signal that exists to be dense where scores are flat.

**Fix.** Mark any turn preceding the first assistant turn as
`source="task_prompt"` and exclude it. Only count turns that follow an agent
action.

---

## F20 — The headline L0 delta compares means over different task sets, and the evidence corpus ignores `Rollout.slice` **CONFIRMED**

`evidence/corpus.py:277-279, 379-385`. `RoundEvidence.mean` averages all tasks
present; `parent_mean` averages only tasks the parent scored.

```
mean score      0.500   (parent 1.000, delta -0.500)
per-task delta rows: [('hard', None), ('easy', 0.0)]
```

Nothing regressed — the paired delta on the shared task is 0.000 — and the
proposer is told the candidate lost half its score.

Live, not hypothetical: `core/search.py:378-383` extends the same rollout list
with **probe** rollouts drawn by `rng.sample` each round, while
`scripts/evolve.py:180-182` passes `parent_scores=entry.scores` (anchor only).
The task sets differ every probe round. And `RoundEvidence.from_rollouts`
(`:219-226`) never reads `Rollout.slice`, despite `types.py:157-161` stating a
rollout separated from its slice *"cannot be safely aggregated"* — probe
rollouts are folded into the mean and zero-rate the proposer optimises against.

**Fix.** Compute L0 over the intersection and label it. Group by slice; render
anchor and probe as separate blocks.

---

## F21 — One observation counted N times defeats `min_support` **CONFIRMED**

`evidence/directives.py:198-203` iterates *every* candidate key with no `break`,
so a payload carrying the same blob under two keys is parsed twice.

```
directives from ONE event carrying the same blob under 3 keys: 3
constraints promoted at min_support=2 from a SINGLE observation: 1
```

`min_support=2` is the module's only guard against writing a one-off into an
always-on artifact (`:244-249`), and a single event with both `stdout` and
`stderr` — the shape `geos.py:1121-1123` `_combined_output` implies — defeats
it. Combined with F7's lost `context` (which merges support across elements),
support is inflated by two independent routes.

**Fix.** `break` after the first key that yields text; dedupe by
`(kind, context, offender, raw)` within an event; count support over *events*.

---

## F22 — "Resumable" holds only for a deterministic proposer, and no search state is persisted **CONFIRMED by reading**

`runners/recording.py:174` keys on `(candidate.cid, task, seed)` where `cid` is
a content hash (and, per F4, a parent hash too). On restart the search must
re-derive byte-identical candidates for a single replay.

With `RandomEditProposer` (seeded from `archive.rng`, fixed seed 0) it does —
which is what the worklog's verification measured (*"second run: 0 executed,
138 replayed"*). With `LLMProposer` — the configuration a real run uses — the
first proposal differs, every downstream cid differs, nothing replays, and the
corpus now holds two disjoint lineages.

Independently, `Search` persists **no state**: archive, `_by_seed`, constraint
ledger, budget ledger, `_seen_hashes` and the RNG position are in-process only,
and `Candidate.files` are never written to any durable record. **After a crash
you can recover the winner's hash but not its text.** `DecisionLog.append`
(`core/decision.py:136-142`) writes without `fsync`, unlike `RecordingRunner`,
so the log can lose its tail too.

At the corrected wall-clock (F6), a crash at hour 40 of 62 is the realistic
case, and what survives it is scores keyed by hashes whose contents are gone.

**Fix.** Checkpoint after each decision: `archive.save()`, every candidate's
`files` to `.evolve/candidates/<cid>.json`, both ledgers. `fsync` the decision
log. Document that rollout replay only helps a deterministic proposer.

---

## F23 — Every API failure collapses into one string, nothing retries, and proposer spend is not tracked at all **CONFIRMED by reading**

`proposers/backends.py:81, 145, 149`. `except Exception as exc: raise
ProposerError(f"{self.name} call failed: {exc}")` makes 429, 529, auth failure,
connection reset and a local `TypeError` indistinguishable. `core/search.py:395`
then catches `(ProposerError, Exception)` and counts them all toward
`max_consecutive_proposer_failures = 5` — **three transient overloads in a row
abort a 60-hour run.** There is no retry or backoff anywhere in the proposer
path.

Also: neither backend checks `stop_reason == "max_tokens"` /
`finish_reason == "length"`, so a truncated response and a refusal both surface
as `ProposerError: no <edit> block in response`; OpenRouter's `content` can be
`null`, reaching `parse_edits(None)` → `TypeError`, not a `ProposerError`; and
**no cost accounting exists** — neither backend reads `usage`, and
`evaluation/budget.py` counts only rollouts, so opus-class proposer spend over a
full evidence corpus is entirely absent from the ledger that the budget-matching
argument depends on.

(The Anthropic call shape itself is correct — `thinking`, `output_config`,
`stop_reason == "refusal"` handling and the model id all check out. One nit: a
300 s non-streaming timeout with adaptive thinking at high effort is tight, and
the SDK's default 2 retries makes the worst case ~15 min before a
`ProposerError`.)

**Fix.** Catch `APIStatusError`/`RateLimitError`/`APIConnectionError` separately;
retry retryable ones with backoff *without* incrementing the failure counter;
raise a distinct `ProposerTruncated` on `max_tokens`; capture `usage` into a
`Cost` and record it in the ledger.

---

## F24 — `materialize` writes outside `dest`, and no caller validates first **CONFIRMED**

`core/candidate.py:247-250` — `target = dest / rel` with no containment check.

```
1. escaped file written at: /tmp/tmpXXXX/pwned.txt exists = True
```

`validate()` (`:184-188`) would have caught it via `is_writable`, but neither
`materialize` nor `runners/subprocess.py:270-282` calls it (see F9). An absolute
key escapes the same way, since `Path("/a") / "/b" == Path("/b")`. A symlinked
`dest` with `overwrite=True` raises a raw `OSError` from `shutil.rmtree`, not a
`CandidateError`.

Component paths come from proposer output, so this is reachable from a model
response. **Fix.** Resolve and assert containment before writing; call
`self.validate()` at the top; unlink a symlinked `dest` before `rmtree`.

---

## F25 — The edit-block regex cannot express an anchor containing a double quote, which is most XML lines **CONFIRMED**

`proposers/edits.py:129-133` uses `anchor="[^"]*"`.

```
canonical          -> 1 edit(s)
attrs swapped      -> 0 edit(s)
single quotes      -> 0 edit(s)
anchor has quote   -> 0 edit(s)
extra attr first   -> 0 edit(s)
```

The artifacts are GEOS XML guidance, where nearly every quotable line looks like
`<Solvers name="…">`, and the system prompt demands the anchor quote the
existing line verbatim. **Delete and replace on any XML-shaped line are
structurally unreachable**, and the failure presents as
`no <edit> block in response` (`proposers/llm.py:279`) — read as a malformed
model, not a broken parser. System-prompt rule 3 ("DELETION IS A REAL MOVE") is
the half of the vocabulary this removes, and ACE's "itemized delta updates incl.
*delete*" is the reason the vocabulary has that half.

**Fix.** Parse the tag's attributes properly (order-independent, either quote
style, entity-decoded), or move the anchor into an `<anchor>…</anchor>` child.

---

# 3. MEDIUM

**F26 — `Rollout.slice` is not persisted, so the corpus cannot support the slice
discipline it exists for.** `runners/cached.py:63-130`: `RolloutRecord` has no
`slice`; `to_rollout` reconstructs `"anchor"`. Harmless inside `Search` (both
paths re-tag), but `ARCHITECTURE.md:39-44` and `recording.py:12-17` sell the
corpus as what every later statistic is recomputed from, and
`RecordingRunner.as_cached()` is "the handoff to offline analysis". There, probe
/ anchor / held-out are indistinguishable and all claim anchor.
`evaluation/protocol.py` enforces discipline over task *names*, which cannot
recover a held-out re-score of the same tasks. *Fix:* persist `slice`,
`candidate_generation` and a run id; old corpora load with `slice=None`, which
the protocol should refuse rather than default.

**F27 — Output tokens counted twice.** `evidence/diagnostics.py:623` and `:631`
both `+=` into the same field: per-assistant-message `usage.output_tokens` and
the terminal `result` event's aggregate. Mined total 2000 against a true 1000.
`runners/subprocess.py:426-427` reads the result event with `=`, so the two
accountings disagree by 2× and `efc._raw_compute` (`:409`) prefers whichever is
non-zero. `runners/mock.py:604-620` emits assistant turns without usage, which
is why no test sees it. Output tokens are a gated efficiency field
(`acceptance.py:247`).

**F28 — `build_slices` returns more anchor tasks than requested.**
`evaluation/slices.py:174, 201-203, 216-222`: `n_boundary` is computed before
`target = anchor_size - n_fresh`, so `anchor_size=4, boundary_fraction=1.0` → 5
tasks and `anchor_size=8` → 9. The shortfall warning at `:226` only fires on
`<`. Propagates into `plan_budget(anchor_size=…)`, so per-candidate cost is
understated and the search overspends the plan — in a regime where the plan is
the whole point of runbook step 1. *Fix:* `n_boundary = min(…, anchor_size -
n_fresh)`; assert the length before returning.

**F29 — `prediction_hit_rate` masks "task not evaluated" as "task did not
improve".** `core/decision.py:156` uses `.get(t, 0.0)`. The model named
`ExampleProppantTest`; the round scored `exampleProppantTest`, which rose 0.40 →
`hit_rate 0.0`, `unearned: True`, and the run notes warn about
over-specification. `predicted_beneficiaries` is free-form model JSON validated
against nothing anywhere in the repo. Every hallucinated or mistyped task id
pushes proposer calibration — a headline result of this project — toward zero.
*Fix:* reject predictions naming unknown task ids in `llm.parse` (free); split
`unknown_beneficiaries` out of the rate.

**F30 — `ledger=None` renders the verdict `fails` with a blurb describing
something that did not happen.** `evaluation/report.py:296-308, 340-341`. No
ledger → all baselines unmatched → `baselines_beaten=False` → `fails`, rendered
as *"A compute-matched baseline matched or beat the evolved candidate…"*.
Neither occurred; nothing was tested. Pinned as intended by
`tests/test_evaluation.py:615-621`. `indeterminate` exists and says the right
thing.

**F31 — The report's per-task table prints means while labelling them with the
comparison's aggregator.** `evaluation/report.py:419-421, 440, 445` —
`arm.aggregate(task)` with no `agg` always uses `agg_mean`, while the header
says `per-task summary across seeds: min` and the delta column comes from
`comp.pairs`. A reader subtracting the two printed columns gets `+0.033`; the
printed delta is `+0.000`, in the same row. `min` across seeds is the natural
aggregator for a tail-driven objective, so this is not a hypothetical column.

**F32 — `preflight` can never pass, and there is no `search` entry point.**
`scripts/evolve.py:99-106` appends the R1 `UNVERIFIED:` blocker
**unconditionally**, so preflight always exits 1 whatever the state of the
world; once R1 is fixed in repo3 there is no way to record it except by editing
source, and the predictable response is to stop running the gate. Separately,
`evolve.py`'s own module docstring advertises `search  run a real search`, and
there is no `cmd_search` and no subparser. `test_docs_consistency.py::
test_advertised_cli_subcommands_exist` scans only the README, so a CLI lying in
its own header passes. **There is no entry point for a real run at all** —
assembling `SubprocessRunner` + `GeosSimulator` + corpus + `Search` + ledger is
left to whoever goes first, at hour zero. *Fix:* file-backed R1 attestation;
ship `cmd_search`.

**F33 — `GroundTruthCorpus.finalize()` never re-indexes numeric literals.**
`hygiene/corpus.py:303` — `if not self.numeric_literals and self.deck_texts:`.
Once populated, `add_decks()` → `finalize()` skips it, so decks folded in later
contribute nothing to the numeric rule.

**F34 — Missing `geosx` is indistinguishable from "every deck is valid".**
`simulators/geos.py:953-958`: when the binary is absent, `validate()` emits one
`severity="info"` finding and returns. Only `error` blocks. A container whose
`geosx` path changes mid-run yields clean validation for every deck forever,
with no error anywhere. Downstream `actionable_fraction` reads 0 %, which
nothing acts on. Combined with F1 and F8 this is a third route to the same
silent zero.

**F35 — Ledger `attempts` is nominal and can certify a budget match.**
`evaluation/baselines.py:186, 602, 657, 730`. `Rollout` has no attempts field
(`types.py:168-177`), so `attempts` is `n_rollouts × configured max attempts`. A
sequential-refinement rollout that succeeded on attempt 1 bills the full retry
budget. `attempts` is a legal `VerdictCriterion.budget_unit`, so a verdict can
certify "budget-matched in attempts" on a number nobody measured — contradicting
`record_rollouts`' docstring ("summed from the rollouts themselves rather than
estimated").

**F36 — `Candidate.from_dir` silently drops declared components and never
validates.** `core/candidate.py:120-136` — `if p.exists()` skips a declared
component whose file is missing, and the result never sees `validate()`.
Materialize it and the frozen agent runs with no primer; scores drop and the
search attributes the drop to whatever edit happened that round. Latent (only
`scripts/derive_constraints.py:132` calls it) but it is the documented way to
load an adapter.

**F37 — Two bare `except Exception` in `core/manifest.py:68-77` silently truncate
the search space.** The docstring names this exact failure (*"the loop looks
like it is searching over checks while quietly refusing most of them"*) and then
implements it twice: any import or registry error falls back to four hardcoded
names, after which a stop policy naming a real check is rejected as
`unknown checks [...]` — a loud error with a wrong cause, non-deterministic
across environments. A candidate-authored plugin with a syntax error takes the
whole check vocabulary down.

**F38 — `Candidate.with_component_texts` swallows a corrupt manifest.**
`core/candidate.py:296-302` — `except ManifestError: manifest =
template.manifest` returns a candidate that looks successfully mutated, and
nothing records that the edit was dropped, so the decision log attributes the
unchanged result to an edit that never happened. It also pops a file for an
empty *declared* component, which `with_edits` (`:163-167`) explicitly refuses
because it breaks the next validation — two drifted implementations of one
operation.

**F39 — Smaller silent-drop sites** (each **CONFIRMED**, each a one-line fix):
`evidence/efc.py:375-376` skips a payload under an unlisted key with no note;
`:380-381` treats a string `index` (`"3"`) as absent, relocating an inline
validator run to the end of the stream where it scores retention 0 by
construction; `:524-527` returns `harness_efficiency = 0.0` on a zero
denominator, indistinguishable from a real zero (should be `None`);
`evidence/diagnostics.py:460` skips unparseable JSONL without counting, so
partial corruption yields `available=True` and a truncated trajectory;
`:866` renders every environment text block as `!!` (error), so the proposer
reads the task prompt as a failure message;
`proposers/demonstrations.py:140-164` returns the **unredacted** demo alongside
`kept=False`, so `clean, _ = sanitize(...)` gets the leaky one;
`:179-185` `Demonstration.render` never emits `artifact_excerpt`, so the field
is loaded, sanitized, gated and dropped.

---

# 4. LOW

**F40 — `core/acceptance.py:339-385` is a dead, drifted duplicate** of
`core/decision.py:130`'s `DecisionRecord`, including a second copy of F29's bug.
Nothing imports it.

**F41 — Two identical `Prediction` dataclasses**, `core/candidate.py:49-85` and
`core/decision.py:55-84`. `proposers/llm.py:40` imports one,
`proposers/scripted.py:249` the other, and `llm.py:330` does
`Prediction.from_dict(prediction.to_dict())` — a round trip that *looks* like a
conversion and converts nothing. `Candidate.predictions` is therefore
heterogeneously typed depending on which proposer ran.

**F42 — `Archive.add` does not dedupe by cid**, so the same candidate can appear
twice on the frontier and be double-weighted in `select_parent`. With F4
unfixed this happens whenever a lineage revisits content.

**F43 — The winner is selected by the criterion the architecture rejects.**
`core/archive.py:116-118` — `best()` is `max(pool, key=mean)`. The Pareto
frontier governs *parent* selection, and then the single candidate released to
held-out is picked by exactly the mean-based rule `ARCHITECTURE.md` fact 1 and
`WHY_V1_FAILED.md §4` argue against (*"mean-based hill climbing discards the
candidate that produced a rescue"*). The frontier keeps the rescue alive all
search and the mean throws it away at the end. *Fix:* report the frontier and
let the protocol choose, or select by tail rather than mean.

**F44 — The check-plugin vetting verdict is forgeable.**
`checks/sandbox.py:288-296` takes the **last** marker line in stdout; the real
verdict is written before `sys.exit`, so an `atexit` handler registered by a
plugin or its test lands after it and wins. Low only because the sandbox is not
wired in (F9) and the proposer is not adversarial — but rule 5's own docstring
says *"a proposer optimising against a gate will find that"*. *Fix:* take the
first marker, or use a dedicated fd.

---

# 5. What to delete

| What | ≈lines | Why |
|---|---|---|
| `checks/sandbox.py` + `checks/plugins/` + the sandbox half of `tests/test_checks.py` | 880 | No caller (F9). And it is not a fence: the vetting child inherits the full environment including `ANTHROPIC_AUTH_TOKEN`, full filesystem and network, bounded only by a 5 s clock. It defends against hangs and vacuous tests, and not at all against the thing that matters here — a check plugin that reads ground truth at rollout time and writes the answer where the agent sees it, which the static-text hygiene gate cannot detect. Either build a real sandbox or delete the module and drop `checks` from the manifest. Do not keep an elaborate gate that is neither wired in nor sufficient. |
| `stats.py` Monte-Carlo permutation branch + `resamples`/`seed`/`exact_max_movers`/`PermutationResult.exact`/`n_permutations` | 40 | Unreachable: needs >20 movers, there are 10-17 tasks. |
| `stats.py` `cohens_dz` + the `EffectSizes` field | 50 | Twenty lines of docstring explaining the denominator is untrustworthy at this n, then rendered in every report as `d_z = +2.34 (diagnostic only)`. A number labelled "do not trust this" is a number that gets quoted. |
| `stats.py` `cluster_bootstrap_ci` | 50 | Ten clusters of three gives a zero-rate interval quantized to ~1/30 with endpoints decided by which of ten tasks was drawn — exactly what `MIN_N_FOR_CI` exists to refuse, except its own floor (`min_groups=6`) lets 10 through. `TailStats` already reports Wilson. |
| `stats.py` `agg_median`, `all_values` | 15 | `agg_median` is `agg_mean` at 2 seeds; `all_values` has zero references. |
| `budget.py` `BudgetOption.matched`/`.ratio`/`.tolerance`, the `o.matched` term in `feasible()`, the "UNMATCHED" render | 35 | Dead: `plan_budget` sets `search_rollouts = baseline_rollouts`, so `ratio == 1.0` always. `tests/test_budget.py:191` asserts a tautology. |
| `acceptance.py` `DecisionRecord` (F40) + `should_accept`/`reject_reason`/`_instance_ids` | 77 | Dead duplicate; and a protocol adapter for `gepa`, an optional dependency nothing imports and no code path constructs. |
| `archive.py` `select_parent_via_gepa` | 20 | Three nested `except Exception` fallbacks to the local implementation, for a dependency the repo never requires and no test exercises. It cannot fail loudly and cannot be observed to have run. |
| One of the two `Prediction` classes (F41) | 35 | |
| `proposers/llm.py` `call_openrouter` | 30 | Dead, duplicates `OpenRouterBackend` with already-drifted defaults (F11). |
| Three copies of "get the text out of a validator payload" (F8) → one helper | 20 | The duplication *is* the bug. |
| `runners/mock.py` `DeckAuthor` ABC + `XmlDeckAuthor` + `SectionKeyDeckAuthor` + `author_for` | 150 | A pluggable synthetic-deck-authoring hierarchy inside a test fixture. `mock.py` is 688 lines — larger than `core/search.py`, the thing it exists to test — with hand-tuned world constants (`extra_block 9 -> 11`) measured on a different system. Collapse to one author and a dict. |
| `runners/subprocess.py:277-281` the `stop_policy.env` "belt and braces" write | 5 | Nothing reads it — no hook in this repo, no test, no preflight check that a reader exists. Its only effect is to make it look as though the stop policy reached the container when R1 says it does not. Defensive code manufacturing false confidence about the exact thing that is broken. |
| `baselines.py:443-465` `validator_error_proxy`'s three-way schema sniffing | 25 | Three speculative schemas for a format that does not exist yet, one of them a bare-except that counts a parse failure as one error. When the format exists it will be one of the three and the other two become silent mis-parses. |

**Not yet in the repo, and I would push back on it landing as-is:**
`evolvers/` (~870 lines), `evaluation/amortization.py` (693),
`evaluation/zero_marginal.py` (396) — 1 950 lines, untracked, **zero tests**,
absent from both package maps (which is what turned the suite red).
`evolvers/base.py`'s stated purpose is to make the evolution strategy pluggable
so several methods compare under one budget. At 17 tasks, 2 seeds and a hard
ceiling of 21 candidates, a multi-arm evolver framework is machinery for an N
this project will never reach. The `BudgetedRunner` idea inside it is the one
genuinely missing piece (§6.4) and it is fifty lines. Land the budget cap; leave
the framework.

**Tests that assert implementation rather than behaviour:**
`test_budget.py:191` (tautology, see above); `:249` restates
`candidates_for`'s arithmetic instead of asserting `9`;
`test_evaluation.py:569-574` hand-writes an aligned ledger, which is precisely
why F14 never fires in CI; `:615-621` pins F30's mislabel as intended;
`:352-353` tests `BudgetLedger.arms()` bookkeeping, not comparison behaviour;
`test_docs_consistency.py::test_package_map_lists_every_module_directory` checks
only `f"{d}/" in text`, which any prose mention satisfies.
Nothing anywhere asserts that `compare` refuses `noise_band=0`, that arms have
equal seed counts, or that a non-`success` `Score.status` is handled — three
assertions that would have caught F2, F17 and F18.

---

# 6. What a long run needs that does not exist

**6.1 An honest wall-clock number, or concurrency.** F6. Six days sequential at
the recommended budget. Everything below assumes that is the real number.

**6.2 Any observability during the run.** `Search.run()` prints nothing and
returns a `SearchResult` after the whole budget is spent. No progress line, no
candidate counter, no ETA, no heartbeat. `RecordingRunner.stats` — including
`write_failures`, i.e. *"this run is silently no longer resumable"* — is only
surfaced by `summary()`, which `Search` never calls. At hour 30 the only
instrument is `wc -l` on the decision log. Minimum: a structured line per
candidate to stderr **and** to `.evolve/progress.jsonl` — elapsed, USD spent,
rollouts spent, accept/reject, reason.

**6.3 An infrastructure circuit breaker.** `no_workspace`, `empty_workspace`,
`no_ground_truth` and `scorer_error` are produced by `runners/subprocess.py` and
**consumed nowhere in the package**. If `ground_truth_dir` is wrong, or
`results_root` does not match where `run_experiment.py` writes, or the image is
missing, every rollout scores 0.0 and the search spends its full budget on a
dead channel. `preflight` checks the directories exist; it does not check
`<ground_truth_dir>/<task>` for the anchor tasks, and nothing verifies the
`<results_root>/<agent>/<run>/<task>/inputs` convention at all. **The single
highest-value addition to this repository is: abort after N consecutive rollouts
whose `Score.status` is an infrastructure status, and refuse to start if the
seed's first evaluation is uniformly zero.** Ten lines.

**6.4 A budget the runner enforces.** `SearchConfig` caps `budget_candidates`
(a count). There is no USD cap, no rollout cap, no wall-clock cap; `self.ledger`
only records; and proposer API spend is not counted at all (F23). A proposer
failure loop or a mis-set `seeds` tuple overspends without limit. Wrap the
runner: refuse the rollout that would cross `max_usd`/`max_rollouts`/`deadline`
and raise a catchable exhaustion the loop turns into a clean finish.

**6.5 Crash recovery beyond rollout replay.** F22. Without candidate contents on
disk, a crash loses the winning adapter even though its scores survive.

**6.6 Signal handling.** No `SIGINT`/`SIGTERM` handler. Ctrl-C or an OOM at hour
30 discards the `SearchResult` entirely.

**6.7 Partial-failure semantics.** `Search._evaluate` never checks that
`run_many` returned a rollout for every requested `(task, seed)`. A dropped one
produces a `scores` dict with a missing key; `RegressionGate` then compares over
`set(child) & set(parent)` and records `n_common_tasks` in metrics nobody reads.
A candidate evaluated on 5 of 6 anchor tasks is silently compared on 5.

**6.8 Disk and container hygiene.** `adapter_root/<run_name>` gets a full
scaffolding copy per (candidate, seed) and is never cleaned; `results_root`
accumulates a workspace per (candidate, seed, task); orphaned containers
accumulate on every timeout (F13). Nothing is bounded and nothing checks free
space before starting.

**6.9 Concurrency safety, if 6.1 is solved that way.**
`RecordingRunner._append` has no lock, and `SubprocessRunner.materialize` writes
to a directory shared by every *task* at a given (candidate, seed) with
`overwrite=True` — two concurrent tasks would wipe each other's adapter mid-run.

---

# 7. Claims that do not hold

| Where | Claim | What the code does |
|---|---|---|
| `README.md`, worklog "the gap, and what I built for it" | validator-derived constraints are the contribution; `directives.py` mines GEOS's inline attribute tables | no runner ever calls `spec.validate`; `Rollout.validator_events` carries only stop-hook decisions (F1). And the regexes cannot parse real GEOS output (F7) |
| `ARCHITECTURE.md` loop diagram | free gates are `manifest · budgets · hygiene · plugin tests` | only hygiene is in `Search` (F9) |
| `ARCHITECTURE.md:41`, `RUNBOOK.md:32-34`, `recording.py:5`, worklog ×4 | a credible search is 16-37 hours | 62-146 hours; the estimate divides by `workers=4` and nothing is concurrent (F6) |
| `hygiene/corpus.py` docstring | runtime gate and hygiene gate "cannot drift apart" | two hardcoded lists, already drifted; 3 of 4 realistic sibling patterns hidden by one and not the other (F10) |
| `types.py:71-80`, `geos.py:1016` | every unscorable deck lands on 0.0 with a distinct status | an unparseable entry deck scores 0.2 with `status="success"` (F3) |
| `candidate.py:93-95` | "identical candidates collapse in the archive and the evaluation cache" | `cid` hashes the parent, so byte-identical candidates never collapse (F4) |
| `acceptance.py:93-95` | the root bound is "looser than the per-step bound" | numerically looser, operationally strictly binding — the only clause without noise tolerance, firing on exactly what the per-step clause was fixed to forgive (F5) |
| worklog, integration pass 1 | "the zero-rate clause compares **rates**, not incidences" | the top-level clause compares seed *means*; the rate comparison lives only in `_zero_is_noise`, whose `+0.5` slack (`acceptance.py:305`) makes it vacuous at 2 seeds — a child zeroing at one of two seeds on a task the parent never zeroed is tolerated |
| `recording.py` | "a restarted search replays what it already has" | true only for a deterministic proposer; no search state and no candidate contents are persisted (F22) |
| `ARCHITECTURE.md:39-44` | the corpus is what every later statistic is recomputed from | `RolloutRecord` drops `slice` (F26) |
| `ARCHITECTURE.md` fact 1, `WHY_V1_FAILED.md §4` | selection is Pareto because mean-based hill climbing discards the rescue | the winner released to held-out is `max(pool, key=mean)` (F43) |
| README / ARCHITECTURE package maps | complete | `evolvers/` missing from both; this is what turned the suite red |
| `scripts/evolve.py` docstring | a `search` subcommand exists | it does not; there is no entry point for a real run (F32) |
| worklog pass 4 | `max_extra_zeros_vs_root = 0` answers a winner whose zero rate was 4× the seed's | the shipped demo still produces a winner at 4.0× (0.222 vs 0.056), relabelled as seed overfitting. The reframing may be correct; it is asserted, not shown, and the symptom is numerically unchanged |
| `test_docs_consistency.py` | "every advertised CLI subcommand exists" | scans the README only, so a CLI misdescribing itself in its own header passes |
| `baselines.py` `record_rollouts` docstring | "costs are summed from the rollouts themselves rather than estimated" | `attempts` is nominal and can certify a budget match (F35) |
| worklog pass 10 | the statistics were "checked from the outside" | the verification file disables the noise band in 8 of 15 tests, the one setting where F15's bug is invisible (F17) |
| `checks/sandbox.py` | "the fence around candidate-authored check code" | full environment, filesystem and network, bounded by a 5 s clock; and never invoked (F9, §5) |
| `manifest.py:68-77` docstring | names the "silently refusing most of them" failure | then implements it twice with bare excepts (F37) |

---

# 8. Suspicions I could not settle

1. **The repo3 CLI contract is unverified.** `runners/subprocess.py:300-316`
   assumes nine flag spellings, and `result_dir` assumes
   `<results_root>/<agent>/<run>/<task>/inputs`. A wrong flag exits non-zero
   (visible). **A wrong results path exits zero and scores every task 0.0
   (invisible, given §6.3).** If `--include` is a prefix or substring match, one
   rollout silently runs several tasks and the cost accounting is wrong.
   *Settle it:* a dry run with a deliberately wrong `results_root`, asserting
   the run refuses rather than scoring zeros.
2. **`variant_stem_keys`' `MIN_STEM_LENGTH = 10`** (admitted in source as "a
   heuristic, not a measured threshold") silently disables variant expansion for
   short task names. *Settle it:* run it over the real 17 basenames and count
   empty key sets.
3. **`rule_task_ids` has no minimum length and no generic-word filter**, unlike
   every sibling rule. A short or word-like task id makes any adapter mentioning
   it a hard `error`.
4. **`rule_blocklist` substring-matches every file in each ground-truth task
   dir**, including non-simulator files — `from_ground_truth_dir` adds
   `f.name.lower()` for *every* file, not just leaky extensions, so a `README.md`
   becomes a blocking substring.
5. **`_count_tool_uses`** (`subprocess.py:440`) recurses over the whole record.
   If Claude Code's `stream-json` emits both incremental assistant events and a
   final `result` carrying the full message list, every tool call is counted
   twice — and the efficiency ratio is a hard acceptance gate. *Settle it:* one
   real `events.jsonl`.
6. **`collect_cost`'s status.json fallback** (`:368-380`) triggers whenever
   `tool_calls == 0`, which is legitimate for an agent that failed immediately;
   and `float(data.get("elapsed_seconds", cost.wall_seconds) or 0.0)` discards
   the events-derived wall time when the key is present but null.
7. **`load_and_resolve_dir` globs `*.xml` only** (`geos.py:168`) while
   `included_targets`' own docstring insists `.geos` files must be visible. An
   entry deck named `*.geos` is invisible to the scorer.
8. **`max_efficiency_ratio = 1.15` on `wall_seconds`** (`acceptance.py:247`).
   Wall time against a container is dominated by host load and image caching; a
   15 % ceiling at 2 seeds will reject candidates for machine noise. `usd` is not
   gated at all, which is the one that is actually budgeted.

---

# 9. If you fix five things

1. **F1 + F7 + F8** — the claimed contribution has no input channel, and its
   parser cannot read the format it was written for. Right now "0 % naming an
   action space" is what you get whether the mechanism works, does not apply, or
   was never connected.
2. **F2 + F3 + §6.3** — make an infrastructure failure impossible to read as an
   adapter result and impossible to survive silently. This is the project's
   founding purpose and it is unmet in three places.
3. **F5** — give the root clause the noise tolerance the parent clause has, or
   the search discards most of its budget on coin flips and produces the
   pre-registered null for the wrong reason.
4. **F4 + F6** — the two arithmetic facts that determine whether the experiment
   fits: identity that actually caches, and a wall-clock number that is not 4×
   optimistic.
5. **F15 + F16 + F17** — the three statistical faults that move the reported
   p-value and the noise band in the flattering direction, in the module whose
   output decides whether any of this gets believed.
