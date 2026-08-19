# W6 — runners + check plugins

Owns `runners/{mock,cached,subprocess}.py`, `checks/`, `tests/test_runners.py`,
`tests/test_checks.py`. `runners/base.py`, `types.py` and `core/` were treated
as frozen; concerns about them are recorded under "contract notes" below rather
than patched.

---

## What is here

| Module | Role |
|---|---|
| `runners/mock.py` | deterministic synthetic world; `MockRunner`, `MockWorld`, `MockOutcome`, `DeckAuthor` |
| `runners/cached.py` | `CachedRunner`, `RolloutRecord`, `CacheMiss` — replay a corpus, raise on a miss |
| `runners/subprocess.py` | `SubprocessRunner` — materialize, shell out to repo3, score, all in one call |
| `checks/constraints.py` | the negative-constraint declaration and its two surfaces |
| `checks/xmlview.py` | `ElementView` — adapter over `Artifact.tree`, which is `Any` by contract |
| `checks/api.py` | `CheckContext`, `run_checks`, `render_feedback`, `known_check_names` |
| `checks/builtins.py` | `parse`, `required_sections`, `cross_section_refs`, `constraints`, `geosx_validate` |
| `checks/sandbox.py` | the fence: vet in a subprocess, import only what passed |
| `checks/plugins/lazy_resolved_refs.py` (+ `_test.py`) | shipped example plugin |

83 tests across the two files; `python3 -m pytest tests/ -q` is green.

---

## Design decisions

**D6.1 — the mock's world model is separate from the mock's artifacts.**
`MockRunner.plan()` is pure: it decides quality, whether the rollout is a zero,
how many stop-hook blocks fired, and the cost, from a hash of
`(cid, task, seed)` plus the candidate's own text and stop policy. Only then is
an artifact written and handed to the simulator. Two payoffs. Tests can assert
on the knobs without touching a filesystem, and a failing search-loop test says
which half broke — the world model or the scoring path.

**D6.2 — the mock never writes a score.** A zero termination is expressed as an
empty or unparseable workspace, and the simulator returns 0.0 under its own
failures-as-zero rule. Overriding the number here would rebuild exactly the
fiction that hid v1's dead reward channel: a runner that reports what it wishes
had happened rather than what the scorer saw. The runner adds provenance under
`Score.detail["mock"]` and touches nothing else.

**D6.3 — the deck format is a seam (`DeckAuthor`), not a constant.** W2's
`simulators/mock.py` landed while this was in progress with its own deck format
(`[Section]` / `key = value`, `.mock` suffix). A runner writing XML into a
workspace that simulator parses would have scored *every* rollout 0 while
looking like it worked — the precise failure class this package exists to make
impossible. `author_for(spec, sections)` picks a matching author, guarded by a
try/except so `runners/mock.py` still works when that peer module is absent.
`tests/test_runners.py::test_mock_runner_writes_a_format_the_paired_simulator_can_parse`
locks the pairing down.

**D6.4 — value corruption is spread over the flattened key list.** Degrading
per section quantises the reward so coarsely that an 0.08 quality improvement
moves no score at all, and the search then sees no gradient. It also matters
substantively: which component binds is interface-dependent (structure on
GEOS/OpenFOAM, values on LAMMPS), and a mock that can only lose whole sections
cannot express the second regime.

**D6.5 — a cache miss raises `CacheMiss`, and the message names the near
misses.** It subclasses `KeyError` so ordinary lookup handling still works. The
message enumerates what the corpus *does* hold for that candidate, because
nearly every real miss is a seed or task-name mismatch, and that is a
ten-second fix if the message says so and an afternoon otherwise.
`RolloutRecord` is a distinct on-disk type rather than `Rollout.to_dict()`,
which reduces `validator_events` to a count — the stop-hook decisions are the
evidence half the stop-policy search rests on. `to_dict()`-shaped records are
still accepted, and replay with an empty validator-event list.

**D6.6 — every failure path in `SubprocessRunner.run` still scores.** Non-zero
exit, timeout, missing workspace, empty workspace, missing ground truth, and a
scorer that raises all produce a `Score` of 0.0 with a `status` that names the
cause. Nothing between the subprocess call and the returned `Rollout` may
return early. The v1 defect was structural, not a typo: scoring lived past a
branch that was never taken.

**D6.7 — the subprocess call is injected.** `CommandRunner` is a plain callable
taking `(argv, env, timeout, cwd)`. Everything except the four-line default
`run_command` is unit-tested against a fake that writes a plausible result
directory. This is what makes the module correct-by-test on a box that cannot
execute it at all.

**D6.8 — the stop policy is exported twice, on purpose.** Once into the child
environment via `StopPolicy.to_env()`, and once as `stop_policy.env` inside the
materialized adapter directory. See the contract note on `docker_cmd.py` below;
the second copy is not redundancy for its own sake.

**D6.9 — one constraint declaration, two rendering methods on the same
object.** `Constraint.to_prose()` and `Constraint.findings(view)` sit side by
side, and `Constraint.validate()` refuses a kind that cannot do both. A
hierarchy would have invited a kind implementing only one surface, which is the
drift the design exists to prevent. The declaration format is a ~120-line YAML
subset (list of flat mappings, block or inline) rather than a dependency; every
parse error carries a line number because these are proposer-authored.

---

## The check-plugin fence, and whether I think it is right

Enforced before any rollout is spent:

1. sibling test exists (`<name>.py` → `<name>_test.py`);
2. the plugin imports without error;
3. it exports `check` callable as `check(artifact, ctx)`;
4. the test passes;
5. the test actually **calls** `check` at least once;
6. import plus test finish inside 5 s.

Two things are stronger than the repo3 first pass. **The import happens in the
vetting child too.** repo3 imported the plugin in-process to see whether it
loaded, which means a module with a hang or an `os._exit` at import time takes
the search down — "import it to find out whether importing it is safe" is not a
fence. Only a plugin that has already survived a child process is imported into
the parent. **The test is instrumented.** The child replaces `check` with a
counting wrapper and pre-registers the module in `sys.modules` so the test's
`import <stem>` gets the instrumented object; a test that never calls it is
rejected as `vacuous_test`. Without that, "ship a test" is satisfiable by
`assert True`, and a proposer optimising against a gate will find that. A test
that `sys.exit()`s instead of asserting is `exited_early`, reported separately
because the fix the proposer needs is different.

**Is the fence right?** For the interface half, yes, and the evidence is
specific: arXiv:2603.05578 finds one-shot autonomous tool creation fails and
that interface errors compound rather than stay local, and this is a
sample-starved search where a rollout costs ~25 minutes. Every rejection here
is free.

Two reservations, recorded rather than resolved.

*It cannot tell a correct check from a check that merely passes its own test.*
A plugin whose test asserts the plugin's own wrong behaviour is accepted. The
fence is a syntax-and-safety gate, not a correctness gate; correctness is
adjudicated downstream by whether the plugin's findings move task scores. That
is the right division, but it should be said out loud rather than assumed —
the acceptance gate, not the fence, is what stops a confidently wrong check.

*The 5 s budget is a vetting-time budget, not a runtime budget.* A plugin that
passes vetting in 4 s pays that on every turn of every rollout, which is a real
efficiency cost the manifest's token budgets do not capture. A per-turn
watchdog in the hook would close it; there is none today, and a plugin cannot
currently be rejected post-hoc for being slow in production.

One deliberate softening: `run_checks` turns a raising check into a `warn`, and
only `error` blocks. A broken check that blocks would trap the agent in a retry
loop it has no way to escape, which is strictly worse than not running the
check at all. Same for a stop policy naming a check whose plugin was rejected —
`warn`, not abort.

---

## What is unexecuted in this environment, and why

**`SubprocessRunner` has never run a rollout.** There is no Docker daemon and
no `/data` volume on this box, so no `docker run` and no containerised harness
invocation has ever happened from this code. Concretely:

- *Unexecuted:* `run_command` (the real `subprocess.run` wrapper), and the
  end-to-end path through `repo3/scripts/run_experiment.py` → `src/runner/cli.py`
  → `docker run`.
- *Tested against a fake:* argv construction, stop-policy env export, the
  `stop_policy.env` file, adapter materialization, non-zero exit still scoring,
  timeout, missing workspace, empty workspace, scorer crash, cost parsing from
  `events.jsonl`, validator-event collection, per-seed result namespacing, and
  every `preflight()` branch.
- *Untestable here at all:* whether repo3's agent key, `--plugin-dir` handling,
  and the container's view of the adapter behave as assumed. First real use
  should be a single task with `--dry-run` before anything aggregate is
  believed.

`preflight()` on this box returns the docker-binary, data-volume, and
`ANTHROPIC_AUTH_TOKEN` reasons, which is the intended behaviour: a list, at
planning time, so the caller can degrade to the cached or mock runner instead
of dying mid-search.

**Everything else runs offline.** `MockRunner`, `CachedRunner` and the whole of
`checks/` need no network, no binaries, and no API key. The plugin sandbox does
spawn `sys.executable` subprocesses; that is local and permitted.

---

## Contract notes for the integrator (not patched — outside W6's scope)

1. **`core/manifest.py:KNOWN_CHECKS` is short.** It lists `parse`,
   `geosx_validate`, `required_sections`, `constraints` — no
   `cross_section_refs`, and it cannot know about a plugin that has just
   cleared the fence. A stop policy enabling either fails
   `Manifest.validate()`. `Manifest.validate(known_checks=...)` already takes an
   override; `harness_evolve.checks.known_check_names(plugins)` returns the
   right set. Whoever wires the search loop must pass it, or the search space
   silently excludes every check beyond the four hardcoded names.

2. **`repo3/src/runner/docker_cmd.py` forwards a fixed `-e GEOS_HOOK_*`
   allowlist** (lines 180-184) and knows nothing about the newer
   `GEOS_EVOLVE_FEEDBACK_SHAPE` / `GEOS_EVOLVE_CHECKS` names that
   `StopPolicy.to_env()` emits. A searched feedback shape would reach the host
   process and be dropped at the container boundary — the search would look
   like it was varying the feedback surface while the hook saw a constant. Two
   fixes, and both should happen: add the two names to that allowlist in repo3,
   and read `stop_policy.env` from the mounted plugin directory in
   `verify_outputs.py`. `SubprocessRunner` already writes that file.

3. **`verify_outputs.py` does not yet consume `GEOS_EVOLVE_CHECKS` or
   `GEOS_EVOLVE_FEEDBACK_SHAPE`.** The hook is where `checks/` is meant to run;
   today it implements parse + `geosx --validate-input` directly. Wiring it up
   means vendoring `checks/` into the plugin directory (which is why
   `checks/api.py` duplicates `FEEDBACK_SHAPES` instead of importing it from
   `core/manifest.py` — `core/` will not be present in the container).

4. **Two generative models now exist for the same effect.**
   `simulators/mock.py` has its own `zero_rate` / `help_strength` / quality
   model inside `MockSimulator.simulate()`, and `runners/mock.py` has
   `MockWorld`. Pairing them stacks two independent zero draws unless
   `simulate()` is bypassed. `MockRunner` only calls `SimulatorSpec.score`, so
   the pairing is currently coherent — but if a search-loop test starts calling
   `MockSimulator.simulate()` directly, whichever model is not being used should
   be turned off explicitly rather than left to interact.

5. **`runners/__init__.py` was left untouched** (docstring only, no re-exports);
   it is not in W6's ownership list. Import the runners by module path, or add
   re-exports there once the ownership question is settled.

6. **`RunnerCapabilities.deterministic` is `False` for `SubprocessRunner`.** A
   frozen agent is still a sampler: same candidate, same seed, different
   trajectory. Any evaluation code that skips repeats when `deterministic` is
   true must not be given this runner and expect one rollout to suffice.

---

## Open questions

- **Is `MockWorld`'s guard model calibrated to anything?** It is not. Retries
  and enabled-check count reduce the zero rate multiplicatively with weights I
  chose to be qualitatively right (guarded < unguarded, never zero). If the
  mock is ever used to make a quantitative claim about how much a stop policy
  buys, those weights need fitting against the run7/run9 block/allow logs — and
  until then the mock is for testing the loop, not for estimating effects.
- **Should the cached runner refuse to be selected as a search runner?**
  `capabilities.can_execute` is `False` and a miss raises, so misuse is loud.
  But nothing prevents a caller from wiring it in as the sole runner and
  discovering that at the first unseen candidate. A search loop asserting
  `runner.capabilities.can_execute` before round 1 would be cheaper than the
  exception.
- **`cross_section_refs` overlaps `geosx --validate-input`.** GEOSX_VALIDATE.md
  confirms the loader catches dangling `targetRegions` at load time, so the
  overlap is real for that class. It is kept because it is ~100x cheaper and
  because its message enumerates the defined names. Worth measuring whether
  enabling both is ever better than enabling the cheap one alone — that is a
  concrete stop-policy ablation the search could run for free on cached data.
- **The example plugin's `SOLVER_REFS` half is conservative on purpose.**
  Whether GEOS resolves `flowSolverName` at load time is not confirmed, so it
  only fires when the referenced name matches nothing anywhere in the deck. If
  someone confirms the laziness against the real binary, it should move into
  `LAZY_REFS` and get the stricter section-scoped treatment.
