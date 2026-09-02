# Overnight worklog — free-window self-evolution campaign

**Session start:** 2026-08-26 ~08:25 local, serv6, `~/src/sci-sim-op`, master.
**Brief:** `docs/2026-08-26_KICKOFF_free-window-campaign.md` +
`docs/2026-08-26_followup-goals.md`.
**Reader assumption:** you are picking this up cold. Absolute paths everywhere.

This file is written *as I go*. Entries are appended in time order; earlier
statements are corrected in place with a marked note rather than silently edited.

---

## 0. Plan on entry, and how it changed

Gates in order, nothing downstream believable until each passes:

1. **G1** — `repo3/plugin/hooks/verify_outputs.py` reads and honours
   `GEOS_EVOLVE_FEEDBACK_SHAPE` + `GEOS_EVOLVE_CHECKS`; proven by *diffing the
   hook's own event log* between `minimal` and `errors_plus_tables` on the same
   task. Config-level checks do not count.
2. **G2** — harden `src/harness_evolve/proposers/backends.py`: User-Agent,
   adaptive per-route concurrency, 429 backoff with jitter, failover across the
   free roster, cost accounting from `usage` that hard-stops on non-zero cost.
   Stdlib-only; 523 tests stay green.
3. **G3** — re-run the v4 contamination audit; quarantine must still block.

Then: Self-Harness regression gate, AHE decision observability, GEPA outer loop,
ACE delta updates, and a real search against GEOS with compute-matched baselines.

**Standing constraints I am operating under:** free models only, hard-stop on any
non-zero `usage.cost`; `tencent/hy3` is out; focus ox-alpha at concurrency 8–16
with patient backoff and resumable search; a second free model only if it clears
the Artificial Analysis bar at/near `deepseek-v4-flash-0420` (the 0420 release).
The null result is a first-class pre-registered outcome.

---

## 1. Entry checks (08:25–08:32)

Both startup commands the kickoff specifies were run before touching anything.

```
$ export PATH="$HOME/.local/bin:$PATH"; uv run python -m pytest tests/ -q
523 passed, 2 skipped in 8.10s
```
Matches the kickoff exactly.

```
$ python3 scripts/provider_watch.py
[2026-08-26 08:29:10]
pair                         free  status     cost         lat
openrouter/stealth/ox-alpha  yes   ok         $0.00000000  2.4
nous/stealth/ox-alpha        yes   ok         $0.00000000  6.4
nous/tencent/hy3:free        NO    ok         $0.00005000  3.4
venice/stealth-ox-alpha      NO    ok         -            7.6
EXIT=0
```

Reading, for the record:
- `stealth/ox-alpha` is still free on both OpenRouter and Nous. The window is open.
- `nous/tencent/hy3:free` still bills $5e-5/call — confirms the kickoff. Not called again.
- Venice shows `free=NO` with cost `-`. This is **not** a regression: Venice returns
  no `cost` field at all, and the watchdog deliberately treats absence as
  not-proven-free ("absence is not evidence of zero"). Venice is not in `--require`,
  so exit stays 0. Noted because "NO" in that column reads alarming and is not.

Baseline for repo3 (the other repo I touch tonight):
```
$ cd ~/src/repo3 && uv run python -m pytest tests/ -q
53 passed in 1.07s
```
Note `pytest` is not installed for the system python in either repo — `uv run` is
required. Confirms the kickoff's warning.

---

## 2. G1 — the reward channel

### 2.1 Reproducing the defect

```
$ cd ~/src/repo3 && grep -rn "GEOS_EVOLVE_FEEDBACK_SHAPE\|GEOS_EVOLVE_CHECKS" --include=*.py .
src/evolve/manifest.py:133:            "GEOS_EVOLVE_FEEDBACK_SHAPE": self.feedback_shape,
src/evolve/manifest.py:134:            "GEOS_EVOLVE_CHECKS": ",".join(self.checks),
src/runner/docker_cmd.py:195:        "GEOS_EVOLVE_FEEDBACK_SHAPE",
src/runner/docker_cmd.py:196:        "GEOS_EVOLVE_CHECKS",
```
Producer (`StopPolicy.to_env`) and forwarder (`docker_cmd.py`) present; **no
consumer**. Confirms the kickoff's grep, independently, on 2026-08-26.

### 2.2 Design decisions, and what I rejected

- **Rejected: vendoring sci-sim-op's `checks/` package into the plugin directory.**
  That is the intended end state (`worklogs/W6_runners_checks.md` note 3, and
  `checks/api.py` duplicates `FEEDBACK_SHAPES` precisely so it *can* be vendored).
  It pulls `checks/{api,builtins,constraints,xmlview}.py` plus
  `simulators/base.py` and `types.py` into a read-only mount, and creates a
  copy that will drift. Tonight it is not on the critical path: the gate is about
  the two names reaching a consumer, and the hook already implements the two
  checks a stop policy actually varies today. **Deferred, and written down as a
  known hole** — see 2.4.
- **Chosen: implement the two knobs natively in the hook, stdlib-only,
  self-contained.** The hook runs inside an enroot container where neither
  package exists. Feedback rendering mirrors `checks/api.py:render_feedback`
  semantics (same three shapes, same table heuristic, near-identical wording) so
  the two implementations can be diffed by eye.
- **Default must be byte-identical to the pre-R1 hook.** `structured_errors` (the
  default) returns exactly today's message. Every run7/run9 comparison and the
  byte-pinned `tests/test_container_spec.py` rendering assume this; a knob that
  silently changes the default rewrites the baseline it is meant to be measured
  against. There is an explicit test for it.
- **Two channels, env first, then `stop_policy.env` from the plugin mount.**
  `SubprocessRunner` writes that file into the materialized adapter directory,
  which *is* the plugin mount, so a policy arrives even where an env allowlist in
  another repo drops the names. Source is recorded per event (`env`/`file`/
  `default`/`legacy_geos_hook_xmllint`/`invalid:<value>`).
- **An unrecognised feedback shape degrades to the default rather than raising.**
  A stop hook that dies leaves the agent with no verdict at all. It is recorded as
  `feedback_shape_source: "invalid:<value>"` so it is auditable rather than silent.
- **Check names the hook cannot run are logged, not ignored.** A stop policy may
  legally name `required_sections` / `constraints` / `cross_section_refs`. Skipping
  them is acceptable tonight; skipping them *invisibly* would recreate exactly the
  hole R1 exists to close. They appear per-event as `checks_unsupported`.
- **The event log now carries the block text verbatim** (`reason`, capped at 4000
  chars, with `reason_chars` giving the true length). This is what makes R1
  verifiable by diff rather than by trust. It also fixes a real complaint the
  evidence layer already had of this log — `runners/subprocess.py:390` notes the
  hook log is verdict-only and "records that a deck failed without recording the
  table of legal attributes the simulator printed alongside", which starves
  constraint derivation. Consumers read it with `.get()`, so added fields are safe.

### 2.3 Files changed

- `/home/matt/src/repo3/plugin/hooks/verify_outputs.py` — the fix. Pre-edit copy
  kept at
  `/tmp/claude-1009/-home-matt-src-sci-sim-op/c7aba9f2-a687-4523-ba3a-ed8001fa2522/scratchpad/verify_outputs.py.orig`.
- `/home/matt/src/repo3/tests/test_verify_outputs_hook.py` — new, 12 tests.

### 2.4 A defect the verification found (and why it mattered more than the gate)

Running the gate against the **real** GEOS validator inside the container turned
up a second, worse bug — one a config-level check could never have found, which
is the whole argument for the way R1's verification is specified.

`verify_outputs.py` extracted the validator's error with

```python
GEOSX_ERROR_BANNER_RE = re.compile(r"(\*{5}\s*Exception.*?)(?=\*{5}\s*StackTrace|\Z)", re.DOTALL)
```

GEOS 1.1.0 (sha1 `d7c0c185df`) does not print `***** Exception`. It prints
`***** Error`. So the regex **never matched**, `_extract_geosx_error` fell through
to its "last 15 non-empty lines" fallback, and every `schema_error` block handed
the agent this:

```
- deck.xml:
    - Frame  9:  /lib/x86_64-linux-gnu/libc.so.6
  - Frame 10:  __libc_start_main
  ... Frames 11-22 ...
```

while discarding this:

```
***** Message :
The tag "SolidMechanicsLagrangianSSLE" is invalid within Solvers (deck.xml, l.3).
All available tags are: AcousticDG, AcousticElasticSEM, ... SurfaceGenerator   [57 names]
```

That discarded text is the highest-quality signal the harness produces: GEOS names
the offending tag *and enumerates every legal alternative*. The agent was being
handed C++ stack frames that mention none of its own inputs, instead of a list it
could copy from. Raw capture:
`/tmp/claude-1009/-home-matt-src-sci-sim-op/c7aba9f2-a687-4523-ba3a-ed8001fa2522/scratchpad/geosx_raw.txt`

**Why this is on the R1 critical path and not a side quest.** The planned ablation
in goals §1.3 is *evidence richness*. With this bug, `structured_errors` and
`errors_plus_tables` differed by one appended sentence, and neither contained the
table. An ablation on "richness" would have been an ablation on stack-trace noise —
a knob that varies with no informative content behind it. Same failure class as R1
itself, one layer in.

**Fix, and a deliberate semantic change.** Three parts:
1. Banner regex now matches `***** (Error|Exception)`.
2. New `_split_table()` splits validator output at `All available tags are` /
   `Valid attributes are` / `Defined:` / `children of`.
3. The three shapes became a real ladder rather than a sentence apart:
   - `minimal` — a count, nothing else (the honest control condition);
   - `structured_errors` — what failed and where, table **withheld**;
   - `errors_plus_tables` — the above **plus** the enumerated legal names.

**What this costs, stated plainly:** the `schema_error` message is no longer
byte-identical to its historical form. I judged that worth it — the historical form
was stack frames, so byte-identity preserves comparability with a broken baseline
and destroys the ablation. The `parse_error` path (the largest block category in
the run7/run9 lineage) *is* still byte-identical, and there is a test pinning it.
Anyone re-running a historical schema_error comparison needs to know this changed.

### 2.5 G1 verification output — **PASS**

Host-level, 14 tests (`/home/matt/src/repo3/tests/test_verify_outputs_hook.py`):
```
$ cd ~/src/repo3 && uv run python -m pytest tests/ -q
66 passed in 1.70s          # was 53 before tonight
```

Container-level. `/home/matt/src/repo3/scripts/verify_r1_feedback_channel.py`
builds the **real** harness command via `build_claude_native_command` (real mounts,
real env allowlist, real enroot renderer), substitutes the hook for the `claude`
argv, and runs it inside the `geos-eval` container. The control arm strips the two
`--env` forwards back out, reproducing the pre-fix boundary.

```
$ REPO3_CONTAINER_BACKEND=enroot python3 scripts/verify_r1_feedback_channel.py \
      --out /home/matt/src/sci-sim-op/.evolve/r1_verification
- [PASS] parse: both arms blocked (86 vs 264 chars)
- [PASS] parse: feedback text differs across shapes (86 vs 264 chars)
- [PASS] parse: shape recorded as requested
- [PASS] parse: shape source is the forwarded env
- [PASS] validate: both arms blocked (86 vs 3038 chars)
- [PASS] validate: feedback text differs across shapes (86 vs 3038 chars)
- [PASS] validate: shape recorded as requested
- [PASS] validate: shape source is the forwarded env
- [PASS] control (forwards stripped): shapes collapse to identical text (151 vs 151 chars)
- [PASS] control: shape falls back to the default
- [PASS] validate: real geosx output reached the agent
EXIT=0
```

The measured ladder, real GEOS validator, same deck, only the shape varied:

| shape | block text | contains |
|---|---|---|
| `minimal` | **86 chars** | a count |
| `structured_errors` | **1212 chars** | the failing tag, file, line |
| `errors_plus_tables` | **3038 chars** | + all 57 legal tag names |

The control arm is the part that makes this a measurement rather than an assertion:
with the two forwards deleted from the rendered command, both shapes produce
**151 identical chars** and log `feedback_shape_source: "default"`. The forwarding
is demonstrably what carries the policy.

**Artifacts (absolute paths):**
- `/home/matt/src/sci-sim-op/.evolve/r1_verification/REPORT.md` — pass/fail + full text per arm
- `/home/matt/src/sci-sim-op/.evolve/r1_verification/arms.json` — every event, stdout, and the exact rendered command
- `/home/matt/src/sci-sim-op/.evolve/r1_verification/<arm>/.verify_hook_events.jsonl` — the hook's own logs, one dir per arm

### 2.6 Known hole left open, deliberately

A stop policy may legally name `required_sections`, `constraints`,
`cross_section_refs`. The hook implements `parse` and `geosx_validate` only;
running the others means vendoring sci-sim-op's `checks/` into the plugin mount.
**Not done tonight.** Unimplemented names are now recorded per-event as
`checks_unsupported` so the gap is visible in the corpus rather than silent — but
**the searchable check set must be restricted to `{parse, geosx_validate}` until
that vendoring lands**, or the search will vary check names nothing runs, which is
R1's pathology wearing a different hat. Carried into the search config below.

**G1: PASSED — 2026-08-26 08:52.**

---

## 3. G2 — the provider layer (09:00–09:35)

### 3.1 What was there, and what the campaign needs

`src/harness_evolve/proposers/backends.py:OpenRouterBackend` was ~40 lines of raw
HTTP with **no User-Agent** (so it cannot talk to Nous at all — 403 on the default
urllib UA, indistinguishable from a bad key), **no retry** (so it dies on the first
429, and the measured ceiling guarantees 429s), and it **discarded `usage`** (so we
would learn a model started billing from an invoice rather than from the run).

### 3.2 What I built, and the reasoning

All in `/home/matt/src/sci-sim-op/src/harness_evolve/proposers/backends.py`,
stdlib-only, transport injectable so none of it needs a network to test.

- **`USER_AGENT`** on every request, in both backends. Asserted by test, including
  that the string does not contain "urllib".
- **`HttpError`** with `throttled` / `transient` predicates, so retry policy can
  distinguish "slow down" (429) from "my fault" (400, never retried — it will fail
  identically forever and retrying only spends the window) from "their fault"
  (5xx/timeouts).
- **`backoff_delay` — full jitter**, not exponential-plus-jitter. The failure mode
  here is a fleet of workers throttled by *the same upstream pool at the same
  instant*; equal waits resynchronise them into a thundering herd. `Retry-After`
  is honoured as a floor when the provider sends one.
- **`AdaptiveLimiter` — AIMD per route.** The ceiling belongs to an upstream pool
  we do not own, cannot query, and which moves when someone else's job starts.
  12.3/min at concurrency 16 is a fact about 2026-08-26, not a setting. So the
  limit is *discovered*: additive increase (one slot per `limit` consecutive
  successes — deliberately slow, overshoot costs real requests), multiplicative
  decrease (immediate halving on a 429). Implemented on a `Condition` rather than
  a `Semaphore` because a semaphore cannot shrink.
- **`CostLedger` — the entire budget policy, enforced not reported.** Non-zero
  `usage.cost` → `BilledCallError` → the route is disabled **permanently**.
  Billing is not a transient failure and is never retried through.
  **`None` is not zero**: Venice returns no cost field, and absence is evidence
  about the response schema, not the price, so unknown-cost calls are counted
  separately (`unknown_cost_calls`) rather than quietly treated as free.
- **`Route` / `free_roster` / `RoutedBackend`** — failover across the free roster.
  **Stated honestly: failover buys availability, not throughput.** OpenRouter and
  Nous resolve to the same `Stealth` pool, so a second route helps when one
  provider's *edge* is unwell and helps not at all with capacity. It is in the
  design for that reason and no other.
- **Venice deliberately excluded from the roster.** It reports no cost field (so
  `require_zero_cost` can never be satisfied) and answers "the model is currently
  overloaded" under exactly the load this campaign generates. Test pins it out.
- `default_backend()` unchanged, so the existing resolution tests still hold; the
  campaign entry point is the new `free_window_backend()`.

### 3.3 The live run found something the unit tests could not

First live smoke: **24/24 calls failed** with
`TypeError: object of type 'NoneType' has no len()`.

`stealth/ox-alpha` is a **reasoning model**, and OpenRouter returns its chain of
thought in `message.reasoning` while `message.content` stays `null` until it
finishes thinking. Measured directly:

| `max_tokens` | `finish_reason` | `content` | `reasoning` |
|---|---|---|---|
| 300 | `length` | `null` | ~300 tokens of thinking |
| 1500 | `stop` | the actual answer | thinking, plus the answer |

Two things follow, both now encoded:

1. **`content_or_error()`** — an empty completion raises a `ProposerError` that
   names `finish_reason` and, for `length`, says to raise `max_tokens`. Returning
   `None` violated this module's own Protocol and surfaced as a `TypeError` three
   layers away, which is how it presented.
2. **Reasoning text is never substituted for the answer.** Tempting, and wrong:
   the proposer parses `<edit>` / `<prediction>` blocks, so handing it a chain of
   thought gives the parser two things that look like answers — the exact confound
   `AnthropicBackend` filters thinking blocks to avoid. There is a test asserting
   the reasoning text does not even leak into the error message.
3. `RoutedBackend.max_tokens` default raised 4000 → **8000**. A proposal is longer
   than that probe prompt was, and this model needs room to reason *and* answer.

**Surprise worth flagging for the morning:** `completion_tokens_details.reasoning_tokens`
comes back **0** on these responses even when hundreds of tokens of reasoning text
are present. Do not use that field for accounting; use `completion_tokens`.

### 3.4 G2 verification output — **PASS**

Unit (`/home/matt/src/sci-sim-op/tests/test_backends.py`, 31 new tests):
```
$ uv run python -m pytest tests/ -q
554 passed, 2 skipped in 8.23s      # 523 before tonight, all still green
```

Live, against the real free endpoints
(`/home/matt/src/sci-sim-op/scripts/free_window_smoke.py`):
```
$ python3 scripts/free_window_smoke.py --calls 24 --workers 12
"ok": 24,  "elapsed_s": 132.9,  "goodput_per_min": 10.8,
"routes": [
  {"route": "openrouter/stealth/ox-alpha", "limit": 10, "successes": 23,
   "throttles": 0, "failures": 1, "disabled": null},
  {"route": "nous/stealth/ox-alpha",       "limit": 8,  "successes": 1,
   "throttles": 0, "failures": 0, "disabled": null}],
"calls": 25, "total_cost": 0.0, "unknown_cost_calls": 0
limit trajectory: [8,8,8,8,8,8,8,9,9,9,9,9,9,9,9,9,10,10,10,10,10,10,10,10]
EXIT=0
```

Reading:
- **24/24 succeeded, $0.00 charged, 0 unknown-cost calls.** The free window is open
  and the hard stop was never triggered.
- **Failover was exercised for real, unplanned**: OpenRouter failed one call and
  Nous served it (`successes: 1` on the Nous route). That also proves the
  User-Agent fix end-to-end — without it that call would have 403'd.
- **Adaptive concurrency ramped 8 → 10** with zero throttles at 12 workers, so
  12 workers is below the pool's ceiling right now. Consistent with the kickoff's
  12.3/min peak at concurrency 16: I measured 10.8/min at 12.
- Latency is ~50–60s/call for a reasoning model at 2000 max_tokens. **This is the
  number that will set the search's wall-clock**, not the rate limit.

**Artifacts:** `/home/matt/src/sci-sim-op/.evolve/free_window_smoke.json`,
`/home/matt/src/sci-sim-op/.evolve/provider_calls.jsonl` (per-call cost ledger).

**G2: PASSED — 2026-08-26 09:35.**

---

## 4. G3 — the contamination quarantine (09:35–09:50)

### 4.1 A correction to the kickoff

The kickoff gives the audit command as if it runs from `~/src/sci-sim-op`:
```
python3 scripts/siga_evolve/audit_lineage.py --adapter-dir plugin_evolving/_quarantine/v4 ...
```
`scripts/siga_evolve/` does not exist in `sci-sim-op`. The script lives at
`/home/matt/src/repo3/scripts/siga_evolve/audit_lineage.py` and **must be run from
`~/src/repo3`**, where the two relative paths resolve. Minor, but it costs a few
minutes if you follow the doc literally.

### 4.2 The quarantine still blocks — **PASS**

```
$ cd ~/src/repo3 && python3 scripts/siga_evolve/audit_lineage.py \
    --adapter-dir plugin_evolving/_quarantine/v4 \
    --task-list-from scripts/self_evolving/run_full_evolution.sh
checking against 17 known task ids
=== plugin_evolving/_quarantine/v4: 5 files, 1 BLOCK, 35 warn ===
  [block] task_id_table in memory/cheatsheet.md: names 17 task ids
          (AdvancedExampleCasedContactThermoElasticWellbore,
           AdvancedExampleDeviatedElasticWellbore, AdvancedExampleDruckerPrager,
           AdvancedExampleExtendedDruckerPrager...):
          looks like a task->answer lookup table
EXIT=1
```
Exactly as documented: all 17 val tasks in one table, blocked, exit 1.

### 4.3 …and the gate discriminates, which is the part worth checking

A gate that blocks everything is not a gate. So I ran the whole lineage:

| adapter | files | BLOCK | warn | exit |
|---|---|---|---|---|
| `plugin_evolving/v0` | 1 | 0 | 0 | 0 |
| `plugin_evolving/v1` | 3 | 0 | 6 | 0 |
| `plugin_evolving/v2` | 3 | 0 | 3 | 0 |
| `plugin_evolving/v3` | 5 | 0 | 5 | 0 |
| `plugin_evolving/_quarantine/v4` | 5 | **1** | 35 | **1** |
| `plugin/` (shipped adapter) | 42 | **1** | 404 | **1** |

The clean lineage passes and only v4 blocks. Good.

**The `plugin/` block is new information and I chased it down.** It is
`plugin/filetree.md`, a directory listing of the GEOS examples tree, which names
`buckleyLeverettProblem/` — a val task id. **It is not in the search candidate.**
`seed_from_plugin.py`'s manifest pulls exactly `PRIMER.md`,
`memory/cheatsheet.md`, `memory/constraints.yaml`, the stop policy and
`hooks/checks/`. `filetree.md` is not among them.

So I audited the object that actually gets mounted, which is the right target:
```
$ python3 scripts/siga_evolve/seed_from_plugin.py --out /home/matt/src/sci-sim-op/.evolve/seed
seed candidate cand_b9617dc5688e written
  PRIMER.md: ~75 tokens
  memory/cheatsheet.md: ~823 tokens
  memory/constraints.yaml: ~120 tokens

$ python3 scripts/siga_evolve/audit_lineage.py --adapter-dir /home/matt/src/sci-sim-op/.evolve/seed ...
=== /home/matt/src/sci-sim-op/.evolve/seed: 4 files, 0 BLOCK, 1 warn ===
exit=0
```
**Seed candidate: clean.** Anyone who later widens the adapter to include
`filetree.md` re-opens this; the audit will catch it.

### 4.4 A defect G3 caught in the seed, which G1 predicted

The generated seed's stop policy was
```toml
checks = ["parse", "geosx_validate", "required_sections"]
```
`required_sections` is a real, registered check in sci-sim-op's registry —
`Manifest.validate()` accepts it — but **the container hook does not implement
it** (see §2.6). Starting the search there means seeding a policy with a component
nothing reads: R1's exact pathology, on day one, in the seed.

Patched the generated seed to `checks = ["parse", "geosx_validate"]`, and the
search config below pins the searchable check set to the same pair. I did **not**
edit `repo3/scripts/siga_evolve/seed_from_plugin.py` — it is repo3's and encodes
the plan's intent; the right fix there is to vendor `checks/` into the plugin
mount so `required_sections` actually runs, not to shrink the plan.

Also confirmed: the seed's `hooks/verify_outputs.py` is the **fixed** hook (it
contains `GEOS_EVOLVE_FEEDBACK_SHAPE`), so the R1 fix propagates into every
mounted adapter automatically.

**G3: PASSED — 2026-08-26 09:50. All three gates are green; rollouts may now be spent.**

---

## 5. Wiring a real GEOS rollout (10:00–11:05)

### 5.1 The four methods already exist — the work is connecting them

Surveying before writing anything, all four adopted methods are **already
implemented** in `sci-sim-op`, with tests:

| Method | Where | What it is |
|---|---|---|
| Self-Harness regression gate | `src/harness_evolve/core/acceptance.py` (405 ln) | four-clause gate: per-task cliff, aggregate, efficiency, cumulative drift |
| AHE decision observability | `src/harness_evolve/core/decision.py` (292 ln) + `evolvers/ahe.py` (572 ln) | every edit paired with a falsifiable prediction, verified next round; edit-type accounting with content hashes |
| GEPA outer loop | `src/harness_evolve/core/archive.py` (192 ln) + `core/search.py` | Pareto over per-task scores, defers to `gepa` if installed |
| ACE delta updates | `core/candidate.py:with_edits` + budget caps in `core/manifest.py` | itemized edits under a hard token cap |

So the goals doc was right that the job is *"connect them to a real evaluator and
find out where they break"*, not *"write the methods"*. **Tonight's contribution
is the connection and what it reveals** — and it revealed a lot, below.

`scripts/evolve.py`'s docstring advertises a `search` subcommand that **does not
exist** (only `demo`, `preflight`, `slices`, `plan`, `audit`). The real-search
driver is the missing piece; writing it is §6.

### 5.2 Preflight, and turning R1 from a slogan into a receipt

`scripts/evolve.py preflight` had an **unconditional** blocker reading
"UNVERIFIED: ... R1". Now that R1 *is* verified, a permanent string is worse than
useless — someone will delete it and the check dies with it.

Replaced with a **tamper-evident receipt**:
- `repo3/scripts/verify_r1_feedback_channel.py` writes
  `/home/matt/src/sci-sim-op/.evolve/r1_verification/receipt.json`, naming the
  **SHA-256 of the hook it verified**.
- New `/home/matt/src/sci-sim-op/src/harness_evolve/integration.py:check_r1()`
  compares that SHA against the hook on disk.

Edit the hook and the receipt stops matching, so preflight goes red until it is
re-verified. A green check that survives the code changing underneath it is worth
less than no check, because it gets trusted.

```
== stop policy reaches the hook ==
  GEOS_HOOK_MAX_RETRIES=2
  GEOS_HOOK_XMLLINT=1
  GEOS_EVOLVE_FEEDBACK_SHAPE=errors_plus_tables
  GEOS_EVOLVE_CHECKS=parse,geosx_validate
  R1 VERIFIED: verified 2026-08-26T08:54:35+0000 against hook d65d0ee76aee:
    validate_minimal=86ch / validate_structured_errors=1212ch / validate_errors_plus_tables=3038ch
== verdict ==
  ready
```

### 5.3 Three real bugs found by trying to run one task

`INTEGRATION_REQUIREMENTS` R3 says `SubprocessRunner` has never run in this
environment and the first real use should be one task, inspected by hand. That was
worth doing: it found three defects in ~40 minutes, two of them mine and one not.

**(a) Relative results root (mine).** The launcher runs with `cwd=repo3`, so a
relative `--results-root-dir` resolved against the wrong repo and the harness
exited `plugin dir not found`. `scripts/_geos.py` now resolves it absolutely.

**(b) `--workers` passed twice (mine).** `SubprocessRunner.argv()` already emits
it. Harmless — argparse takes the last — but removed.

**(c) The launcher fails tasks and exits 0 (not mine, and this one matters).**
repo3's default `--tmp-geos-parent`
(`/data/shared/geophysics_agent_data/data/eval/tmp_geos`) is owned by another user
and is not writable by `matt`. Every task failed with
`[Errno 13] Permission denied` — and the process **returned 0**:

```
[  1/1] ERROR  claude_code_repo3_plugin_xmllint_all  ExampleMandel
        ([Errno 13] Permission denied: '/data/.../tmp_geos/geos_eval_ljub0k9z')
Done: 0 succeeded, 1 failed / 1 total
$ echo $?
0
```

**Why this is a campaign-threatening bug, not a nuisance.** A harness that cannot
start the container produces an empty workspace; an empty workspace scores 0; and
under failures-as-zero a 0 is indistinguishable from "the model wrote nothing".
So an infrastructure outage gets **silently attributed to the candidate under
evaluation**. The search would reject good candidates for a reason that has
nothing to do with them, the decision log would record honest-looking rejections,
and nothing anywhere would look wrong. That is the same shape as the R1 defect:
a signal that is structurally incapable of meaning what it appears to mean.

Fixed in `src/harness_evolve/runners/subprocess.py`: new `harness_failure()`
parses the launcher's own summary (ANSI stripped) and, when the launcher reports
failures while exiting 0, the rollout comes back with `status="harness_error"`
and a populated `error` field — so downstream can refuse to count it. Two tests
pin it.

Working `--tmp-geos-parent` for this account: **`/data/matt/tmp_geos`** (must be
on `/data` so the filtered-GEOS copies stay hardlink farms rather than 20 GB of
real copies). Wired as the default in `scripts/_geos.py`.

### 5.4 Files added

- `/home/matt/src/sci-sim-op/scripts/_geos.py` — the single place that knows how
  this box runs GEOS: repo3 location, enroot backend, ox-alpha via the OpenRouter
  gateway, host-side `geosx` + `LD_LIBRARY_PATH` for validator capture,
  `/data/matt/tmp_geos`.
- `/home/matt/src/sci-sim-op/scripts/run_one_rollout.py` — R3's single-task probe.
- `/home/matt/src/sci-sim-op/src/harness_evolve/integration.py` — repo3 discovery
  and the R1 receipt check.

```
$ uv run python -m pytest tests/ -q
556 passed, 2 skipped          # 523 at session start
```

---

## 6. The search driver (11:05–11:30)

`/home/matt/src/sci-sim-op/scripts/search_geos.py` — the driver `evolve.py`'s
docstring promised. Three stages, each independently runnable and resumable:

```
python3 scripts/search_geos.py --stage baseline  --tasks N --seeds 1
python3 scripts/search_geos.py --stage search    --budget K
python3 scripts/search_geos.py --stage baselines --search-rollouts M
```

Design decisions, and why:

- **Everything runs through `RecordingRunner`.** Rollouts are the only expensive
  thing; once on disk they replay free. A search interrupted by a throttle, a
  reboot, or a morning deadline resumes rather than restarts — which is what the
  kickoff means by "throttling costs time rather than work". It also means every
  statistic can be recomputed later for nothing.
- **Baselines are budgeted in from the start.** `run_matched_suite` takes the
  search's *actual* rollout spend and derives k from it, rounding **up** so
  leftover budget goes to the baseline rather than to us. arXiv:2607.12227 is
  explicit that harness evolution does not consistently beat best-of-k; an
  unmatched win is not a win.
- **The searchable check set is pinned to `("parse", "geosx_validate")`** — what
  the container hook actually implements (§2.6, §4.4).
- **`require_gates()` refuses to spend a rollout while R1 is unverified.** The
  check reads the receipt; a stale receipt stops the search rather than producing
  a normal-looking meaningless run.
- **Harness errors are separated from model failures** in the baseline stage
  report, using the `status="harness_error"` channel added in §5.3. Averaging an
  infrastructure outage into a candidate's score is how a good candidate gets
  rejected for someone else's permissions problem.

---

## 7. Screening a second free model (11:30–11:45)

The brief allows a second model only if it clears an Artificial Analysis
intelligence index at or very near `deepseek-v4-flash-0420`. Indices read
2026-08-26 from artificialanalysis.ai. **The bar is 42** — the 0420 release, not
0731, which scores 50.

Then a second, independent test the leaderboard cannot answer: **is it actually
free?** One real completion each, `usage.cost` read back.
`/home/matt/src/sci-sim-op/scripts/screen_free_models.py`, results in
`/home/matt/src/sci-sim-op/.evolve/model_screen.json`.

| model | AA index | ctx | clears bar | live probe | verdict |
|---|---|---|---|---|---|
| `z-ai/glm-5.2:free` | **51** | 256k | yes | 429 upstream, twice (4 jittered retries) | **unknown** — capacity, not price |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | **48** | 1M | yes | `cost=0` | **ADOPTABLE** |
| `minimax/minimax-m3:free` | **44** | 1M | yes | `cost=0` | **ADOPTABLE** |
| `thinkingmachines/inkling:free` | 41–42 | 1M | borderline-yes | **403** | rejected: *"only available on agentic harnesses"* |
| `deepseek/deepseek-v4-flash:free` | 50 (0731) | 128k | yes | **404** | rejected: free window **closed** |
| `stealth/ox-alpha` | — | 1M | (the workhorse) | `cost=0` | in use |

Total spend on this screen: **$0.00** (2 billable-checked calls, both zero).

Four things worth carrying forward:

1. **Two adoptable panel members exist**, both 1M-context and both comfortably
   above the bar: `nemotron-3-ultra` (48) and `minimax-m3` (44). A cross-model
   panel is therefore affordable, which matters because the measured gain depends
   partly on which inference model you run on (arXiv:2605.30621) and because
   Self-Harness's first stage is *model-specific* weakness mining. **I am not
   spraying work across them tonight** — ox-alpha remains the workhorse, per the
   brief — but the panel is now costed and available rather than hypothetical.
2. **A third free window has closed since the kickoff was written.**
   `deepseek/deepseek-v4-flash:free` now answers *"This model is unavailable for
   free. The paid version is available now"* — the identical message OpenRouter
   gave for `tencent/hy3:free`. The kickoff's claim that the window is
   "demonstrably closing" is now supported by two independent observations, not
   one. **Contradicts nothing in the kickoff; it strengthens the urgency case.**
3. **`thinkingmachines/inkling:free` is 403-gated to "agentic harnesses".**
   Curious and possibly useful: it may well serve *inside* Claude Code (which is
   an agentic harness) while refusing a raw proposer call. Untested. If a
   cross-model *rollout* panel is wanted, inkling is worth one probe through the
   container path before writing it off.
4. **`z-ai/glm-5.2:free` is the highest-index candidate and I could not get a
   single call through** — 429 `"temporarily rate-limited upstream"` on two
   attempts with jittered backoff. Recorded as **unknown**, not as "not free":
   conflating capacity with price is exactly the false alarm `provider_watch.py`
   is written to avoid. Worth retrying at a quieter hour.

---

## 8. Rollouts are the bottleneck — and what I did about it (11:45–12:20)

### 8.1 The measurement

First real rollout, `ExampleMandel`, seed adapter, `stealth/ox-alpha` through the
OpenRouter gateway, enroot container, RAG MCP connected:

```
elapsed 491s and still running, 33 tool calls
latest: "The exact filenames from the spec aren't in this GEOS version,
         but close analogues exist. Let me read them."
```

So **a GEOS rollout is ~10+ minutes**, dominated by ox-alpha's per-call latency
(a reasoning model at ~50 s/call × tens of sequential tool calls). It is not
dominated by the rate limit: at 12 concurrent the pool gave 24/24 successes with
zero throttles (§3.4).

**Explicitly, as the brief asks: GEOS rollouts are the bottleneck.** A serial
`run_many` over 6 tasks is an hour; a search at the plan's budget is days. Saying
so and running what I can, rather than stalling.

### 8.2 The fix: parallelism, because the free pool is 8–16 wide and we were using one slot

`RolloutRunner.run_many` was `[self.run(...) for ...]` — a serial comprehension.
That was the right default for a runner that had never been run, but the numbers
are lopsided: a rollout is minutes of *waiting on a container*, the pool sustains
8–16 concurrent requests, and one rollout occupies about one slot. Serial
`run_many` leaves seven eighths of the free window unused, and the free window is
the entire reason for the schedule.

New `/home/matt/src/sci-sim-op/src/harness_evolve/runners/parallel.py`:
`ParallelRunner` wraps any runner and fans `run_many` over a thread pool
(threads, not processes — every rollout sits inside `subprocess.run`).

Composition order is `ParallelRunner(RecordingRunner(SubprocessRunner))` and that
is deliberate: recording on the outside would re-serialise `run_many`, since
`RecordingRunner` does not override it. **Input order is preserved** — downstream
code pairs rollouts with tasks positionally in places, and a silent reorder is a
very quiet bug. `RecordingRunner._append` is now lock-protected; an interleaved
append produces a line that is not JSON, and the corpus is exactly what a resumed
run depends on. 8 new tests, including a 40-rollout concurrent write that must
leave 40 parseable lines.

### 8.3 A third silent-failure mode, found by turning concurrency on

The first parallel launch failed instantly:

```
seed cand_78856ef8131e on 6 tasks x 1 seeds = 6 rollouts
    ExampleMandel        0.0000 no_workspace
```
and the corpus recorded `error: "harness exited 2"`.

Cause: repo3's launcher takes a **per-run-name PID lock** at
`<results_root>/.run_locks/<run_name>.lock` — added deliberately after the April
2026 run9 incident, where a second invocation SIGTERMed twelve in-flight tasks.
`SubprocessRunner.run_name()` was `{prefix}-{cid}-s{seed}`, with **no task in
it**, so six concurrent rollouts of one candidate all wanted the same lock. One
ran; five exited 2 having done nothing.

Two fixes, both in `src/harness_evolve/runners/subprocess.py`:

1. `run_name()` now takes the task and includes it. (The no-task form is
   unchanged, so nothing that called it two-argument moved.)
2. **A launcher that exits non-zero without timing out is no longer blamed on the
   candidate.** It never got as far as running the agent — held lock, missing
   image, unreadable path — so `status` becomes `harness_error` rather than
   `no_workspace`. A **timeout is deliberately left alone**: an adapter can
   genuinely make an agent slow, and that is a real outcome, not an infra fault.

That is now the **third** distinct way this stack could have scored infrastructure
failure as model failure (exit-0-with-failures §5.3, non-zero exit, run-lock
collision). All three produce a clean-looking 0. I think this is the most
transferable finding of the night: *in a harness-evolution loop, the dangerous
bugs are not the ones that crash — they are the ones that produce a plausible
score.* Same shape as R1 itself.

```
$ uv run python -m pytest tests/ -q
572 passed, 2 skipped        # 523 at session start
```

---

## 9. The proposer works on the free model (12:25–12:35)

Everything about `LLMProposer` is otherwise tested against injected responses,
which verifies the parsing and the guards and says nothing about whether a real
model, given this prompt, produces a compliant edit. And the model that matters
is **not** Opus — it is `stealth/ox-alpha`, because that is what the campaign can
afford to run. Added `--free-roster` to
`/home/matt/src/sci-sim-op/scripts/smoke_llm_proposer.py`.

(Bug fixed on the way: that script's `load_env()` read **only**
`ANTHROPIC_API_KEY`, and only from `~/.env`. So `free_window_backend()` reported
"no route is configured" on a box with both keys sitting in the repo `.env` it
had just read past. Now loads both files, every key.)

Result — **one real ox-alpha call, cost $0.00, contract followed**:

```
prompt: 2724 chars. Calling free roster (stealth/ox-alpha)...
==================================================================
PROPOSAL ACCEPTED BY THE PARSER AND THE BUDGET GATE
==================================================================
component      memory
targets        extra_block
beneficiaries  ['wellbore_thermo']
predicted Δ    +0.030
rationale      Both tasks failed on surplus declarations (extras in every rollout)
               and the existing 'add a matching constitutive block' line actively
               encourages that surplus; swapping it for a strict reference-only
               bound should cut the extra blocks dragging down the regressing
               task's Constitutive section (0.34), while keeping the earlier
               region-naming guidance intact.
lines 4 -> 4
```

This is worth more than it looks, on three counts:

1. **AHE decision observability is working end-to-end on a free model.** The edit
   arrived paired with a named component, a named failure category, named
   predicted beneficiaries, and a signed predicted delta — i.e. a falsifiable
   claim the next round can check. That is the mechanism whose absence made v1
   three unconditioned rewrites.
2. **ACE-style delta discipline held without being asked twice.** `lines 4 -> 4`:
   the model *replaced* a line rather than appending one. The 12× monotone growth
   that wrecked v1's adapter (270 B → 3159 B in three rounds) starts as exactly
   the append this model declined to make.
3. **The derived constraint reached it as settled fact.** The prompt carried
   `Do NOT set gravityVector on <Solvers/SinglePhasePoromechanics>. Its only valid
   attributes are: ...` — mined from validator output the campaign had already
   paid for. Note this is the same valid-name table the hook was **discarding**
   until §2.4; the constraint-derivation path and the agent-feedback path consume
   the same signal, so that bug was starving both.

The proposer is therefore not a risk for tonight's search. The evaluator is.

---

## 10. Live: the first real GEOS evaluation (12:20 →)

Running now, 6 tasks concurrently, seed adapter, ox-alpha:

```
$ python3 scripts/search_geos.py --stage baseline \
    --task-list AdvancedExampleDruckerPrager,buckleyLeverettProblem,ExampleDPWellbore,\
ExampleIsothermalLeakyWell,ExampleMandel,TutorialSneddon \
    --seeds 1 --anchor 4 --probe 1 --parallel 6 --timeout 2400 \
    --out /home/matt/src/sci-sim-op/.evolve/geos_search
```
Tasks are the first 6 of the 17-task val split from
`repo3/scripts/self_evolving/run_full_evolution.sh` (`TASKS_R0`/`TASKS_R1`), so
the pool is the lineage's, not one I invented.

At T+3 min all six are alive and progressing (9–22 tool calls each), RAG MCP
connected, no throttling. **Parallelism works**: six containers, six agents, one
free pool.

**Timing reality, recorded before the numbers arrive so it cannot be
rationalised afterwards:** the R3 probe rollout is at **12 minutes and 45 tool
calls** and has not yet written a deck. These agents explore the GEOS tree for a
long time before authoring. So plan on **10–20 min per rollout**, and note that
what makes it slow is ox-alpha's per-call latency, *not* the rate limit — at 12
concurrent the pool gave 24/24 with zero 429s.

Rough budget arithmetic for the rest of the night, at 6-way parallelism:
- baseline (6 rollouts) ≈ 15–20 min wall-clock
- search, budget 3 candidates, seeds (1,), anchor 4, screen 2
  ≈ 3 × (2 screen + 4 full) = 18 rollouts ≈ 45 min
- compute-matched best-of-k at k = ceil(18/4) = 5 → 20 rollouts ≈ 50 min

The seed's anchor scores **replay from the baseline corpus for free**, because
both stages share `/home/matt/src/sci-sim-op/.evolve/geos_search/rollouts.jsonl`
and the candidate/task/seed keys match. That is the resume machinery paying for
itself on its first use rather than in a hypothetical crash.

---

## 11. The ablation harness (12:50–13:05)

goals §1.3 says the deliverable is **which ingredient carries the gain**, not a
leaderboard number. An ablation you have to edit code to run is one that gets run
once, so each of the four is now a flag on the search driver:

```
python3 scripts/search_geos.py --stage search --ablate gate     --tag _no_gate
python3 scripts/search_geos.py --stage search --ablate evidence --tag _no_evidence
python3 scripts/search_geos.py --stage search --ablate pareto   --tag _no_pareto
python3 scripts/search_geos.py --stage search --ablate delta    --tag _no_delta
```

| `--ablate` | what it removes | what it reproduces |
|---|---|---|
| `gate` | Self-Harness regression gate → accept anything that parses and clears hygiene | v1's selection rule, i.e. none |
| `evidence` | proposer's evidence drops L2 → L0 (scores only; no validator output, no failure categories, no trajectory excerpts) | AHE's observability claim, inverted |
| `pareto` | GEPA frontier → best-mean hill climbing | the rule predicted to discard single-task tail rescues |
| `delta` | ACE's per-component token caps lifted ×100 | v1's 270 B → 3159 B primer growth, deliberately |

Each switch removes exactly one mechanism and leaves the rest intact, so a
contrast is attributable. `--tag` keeps arms from overwriting each other, and
every arm shares the rollout corpus, so **the seed's own evaluation is paid for
once across all five arms.**

**What is deliberately not ablatable: the reward channel.** A search with no
reward is what v1 was, and reproducing it is not an ablation, it is the bug.

---

## 12. Re-analysis for free (13:05–13:20)

`/home/matt/src/sci-sim-op/scripts/report_geos.py` recomputes every number from
`rollouts.jsonl` without spending anything. The split matters: the rollouts are
the expensive part and the statistics are free, so any question asked *after* the
run — a different noise band, an added baseline, a recut slice, a corrected bug —
gets answered instead of receiving "we will not re-run it".

It prints per-candidate mean / zero-rate / per-task spread, keeps **harness
errors out of every average** (they are not evidence about a candidate), and does
a **paired** per-task comparison against the seed with a CI, flagging explicitly
when the interval spans zero. Paired because the tasks are the same tasks; the
interval is wide at these n, and reporting it narrow would be the lie.

Also updated `/home/matt/src/sci-sim-op/docs/INTEGRATION_REQUIREMENTS.md`: **R1 is
marked SATISFIED** with the measured ladder, the control arm, the reproduction
command, and the one gap still open (`checks_unsupported`). `test_docs_consistency.py`
still passes.

---

## 13. Where this stands, and exactly what to run next

**If you are picking this up cold, start here.** Everything below is reproducible
from the paths given.

### Gates
| gate | status | evidence |
|---|---|---|
| G1 reward channel | **PASSED** | `.evolve/r1_verification/REPORT.md`, receipt SHA-pinned to the hook |
| G2 provider layer | **PASSED** | `.evolve/free_window_smoke.json`, 24/24 at 12-way, $0.00 |
| G3 quarantine | **PASSED** | v4 blocks (1 BLOCK), v0–v3 and the seed candidate clean |

### The one-line reproduction of each thing built tonight
```bash
cd ~/src/sci-sim-op && export PATH="$HOME/.local/bin:$PATH"

uv run python -m pytest tests/ -q                    # 572 passed, 2 skipped
uv run python -m pytest ~/src/repo3/tests -q         # 66 passed
python3 scripts/provider_watch.py                    # is the window still open?
uv run python scripts/evolve.py preflight --simulator geos \
    --ground-truth-dir ~/src/repo3/data/eval/experiments_gt      # -> "ready"

# R1, end to end, inside the real container (~4 min)
cd ~/src/repo3 && REPO3_CONTAINER_BACKEND=enroot \
  python3 scripts/verify_r1_feedback_channel.py \
    --out /home/matt/src/sci-sim-op/.evolve/r1_verification

# the provider layer against the live free roster
cd ~/src/sci-sim-op && python3 scripts/free_window_smoke.py --calls 24 --workers 12

# one proposal from ox-alpha, with its falsifiable prediction
uv run python scripts/smoke_llm_proposer.py --free-roster
```

### The campaign pipeline
```bash
cd ~/src/sci-sim-op && export PATH="$HOME/.local/bin:$PATH"
OUT=/home/matt/src/sci-sim-op/.evolve/geos_search

# 1. score the seed, cut anchor/probe/held-out
uv run python scripts/search_geos.py --stage baseline --parallel 6 --seeds 1 \
  --task-list AdvancedExampleDruckerPrager,buckleyLeverettProblem,ExampleDPWellbore,ExampleIsothermalLeakyWell,ExampleMandel,TutorialSneddon \
  --out $OUT

# 2. search (all four methods on)
uv run python scripts/search_geos.py --stage search --budget 3 --seeds 1 --parallel 6 --out $OUT

# 3. compute-matched baselines; k is derived from what the search actually spent
uv run python scripts/search_geos.py --stage baselines --seeds 1 --parallel 6 --out $OUT

# 4. the ablations -- the actual deliverable of goals §1.3
for a in gate evidence pareto delta; do
  uv run python scripts/search_geos.py --stage search --budget 3 --seeds 1 \
    --parallel 6 --ablate $a --tag _no_$a --out $OUT
done

# 5. recompute every number from the corpus, free, any time
uv run python scripts/report_geos.py --out $OUT
```
Stages 2–4 all replay the seed's rollouts from `$OUT/rollouts.jsonl`, so the seed
evaluation is paid for **once** across every arm.

### Where everything lives (absolute paths)
| what | where |
|---|---|
| this log | `/home/matt/src/sci-sim-op/worklogs/2026-08-26_overnight.md` |
| R1 evidence + receipt | `/home/matt/src/sci-sim-op/.evolve/r1_verification/` |
| provider smoke | `/home/matt/src/sci-sim-op/.evolve/free_window_smoke.json` |
| per-call cost ledger | `/home/matt/src/sci-sim-op/.evolve/provider_calls.jsonl` |
| free-model screen | `/home/matt/src/sci-sim-op/.evolve/model_screen.json` |
| seed candidate | `/home/matt/src/sci-sim-op/.evolve/seed/` |
| rollout corpus (resume) | `/home/matt/src/sci-sim-op/.evolve/geos_search/rollouts.jsonl` |
| raw rollout workspaces | `/home/matt/src/sci-sim-op/.evolve/geos_search/rollouts/claude_code_repo3_plugin_xmllint_all/` |
| decision log | `/home/matt/src/sci-sim-op/.evolve/geos_search/decisions.jsonl` |
| filtered-GEOS scratch | `/data/matt/tmp_geos` (repo3's default is another user's dir) |

### Code changed tonight
**sci-sim-op**
- `src/harness_evolve/proposers/backends.py` — rewritten: UA, jittered 429 backoff,
  AIMD `AdaptiveLimiter`, `CostLedger` with a hard stop at non-zero cost, `Route` /
  `free_roster` / `RoutedBackend` failover, `content_or_error` for reasoning models
- `src/harness_evolve/runners/parallel.py` — **new**, `ParallelRunner`
- `src/harness_evolve/runners/recording.py` — locked corpus writes
- `src/harness_evolve/runners/subprocess.py` — `harness_failure()`, task-unique run
  names, infra failures no longer scored as model failures
- `src/harness_evolve/integration.py` — **new**, repo3 discovery + R1 receipt
- `scripts/{_geos,run_one_rollout,search_geos,report_geos,screen_free_models,free_window_smoke}.py` — **new**
- `scripts/evolve.py` — R1 receipt check replaces the unconditional blocker
- `scripts/smoke_llm_proposer.py` — `--free-roster`, `.env` loading fixed
- `docs/INTEGRATION_REQUIREMENTS.md` — R1 marked satisfied, with evidence
- `tests/` — `test_backends.py`, `test_parallel_runner.py`,
  `test_integration_receipt.py` new; `test_runners.py` extended (523 → 572)

**repo3**
- `plugin/hooks/verify_outputs.py` — reads and honours both stop-policy names;
  banner regex fixed; feedback shapes made a real ladder
- `tests/test_verify_outputs_hook.py` — **new**, 14 tests (53 → 66)
- `scripts/verify_r1_feedback_channel.py` — **new**, container-boundary proof + receipt

---

## 14. RESULTS — first real GEOS rollouts (13:50 →)

### 14.1 R1 confirmed in a genuine agent run, not just in the verification harness

The first rollout to finish wrote its hook event log, and it says:

```json
{"decision": "allow", "reason_category": "xml_clean", "retries_so_far": 0,
 "feedback_shape": "structured_errors", "feedback_shape_source": "env",
 "checks": ["parse", "geosx_validate"], "checks_source": "env",
 "checks_unsupported": []}
```
`/home/matt/src/sci-sim-op/.evolve/geos_search/rollouts/claude_code_repo3_plugin_xmllint_all/evolve-cand_78856ef8131e-s1-TutorialSneddon/TutorialSneddon/.verify_hook_events.jsonl`

**`feedback_shape_source: "env"` and `checks_source: "env"`.** The stop policy
was emitted by `StopPolicy.to_env()`, survived `SubprocessRunner`, survived
repo3's launcher, survived the enroot boundary, and was *read by the hook* — in a
real ox-alpha rollout on a real GEOS task, not in my test harness. That is
stronger evidence for G1 than the verification script, because nothing about this
run was arranged to demonstrate it.

`checks_unsupported: []` also confirms the §4.4 seed patch took: the policy now
names only checks the hook can actually run.

### 14.2 First scored rollout

```
TutorialSneddon        0.0925   success   482s   30 tool calls
```

Structurally clean — `xml_clean`, no block, so the deck parsed *and* loaded under
`geosx --validate-input` — but scoring **0.0925** against ground truth. That gap
is the interesting part and is worth stating early: the stop policy's checks
answer *"is this a valid GEOS deck"*, and this deck was one. They do not answer
*"is this the right deck for this task"*, and it largely was not.

This is direct evidence for the goals-doc hypothesis that **structural
completeness and value-correctness are different binding constraints** (§1.3,
"which component *binds*, per simulator"). On this task the structural gate is
satisfied and the score is still near the floor, so on GEOS the binding
constraint here is *not* structural validity. If that holds across the pool it
predicts that a search over the stop policy — which is a structural instrument —
has little room to move the score, which is exactly the pre-registered null.

I am not drawing that conclusion from n=1. Recording it now, before the other
five land, so it is a prediction rather than a post-hoc reading.

### 14.3 What the 0.0925 actually is — and why it matters more than the number

The score detail is unambiguous about the failure mode:

```
section_scores : Constitutive 0.0, ElementRegions 0.0, Events 0.0,
                 FieldSpecifications 0.0, Functions 0.0, Geometry 0.0, Mesh 0.0,
                 NumericalMethods 0.0, Outputs 0.0, Solvers 0.0, Tasks 0.0
match_summary  : paired_elements 31, gt_unmatched 221, gen_unmatched 6
n_extra        : 0     extra_element_types: []
missing_element_types: Box, CompressibleSinglePhaseFluid,
    CompressibleSolidParallelPlatesPermeability, Coulomb, FiniteVolume,
    HydraulicApertureTable, Hydrofracture, NullModel, ParallelPlatesPermeability,
    PressurePorosity, SinglePhaseFVM, SolidMechanicsLagrangeContact,
    SolidMechanicsLagrangianFEM, SurfaceGenerator, Traction,
    TwoPointFluxApproximation
```

The agent wrote a **37-element deck against a 252-element ground truth**. It
hallucinated nothing (`n_extra: 0`, `extra_element_types: []`) and everything it
wrote was structurally legal. The failure is **under-generation**: it stopped far
too early, and 221 required elements are simply absent.

**This is the finding of the night on the science side, and it has teeth:**

1. **The stop policy cannot see this failure mode at all.** `parse` and
   `geosx_validate` both *pass* on a minimal valid deck — as they did here,
   `xml_clean`, no block, zero retries. A gate that asks "is this a valid GEOS
   deck" is structurally incapable of noticing "this deck is 15% of a GEOS deck".
2. **So a search over the stop policy has almost no room to move this score.**
   That is the pre-registered null (plan §7.1) arriving with a *mechanism*
   attached rather than as an unexplained flat result. Predicting it in advance
   is much stronger than reporting it afterwards, so it is written here at n=1,
   before the other five tasks land.
3. **The check that would catch it is the one the hook cannot run.**
   `required_sections` — dropped from the seed policy in §4.4 precisely because
   the container hook does not implement it — is exactly the instrument that
   detects an absent `Mesh`/`Events`/`Constitutive` section. So the vendoring gap
   in §2.6 is not housekeeping: **it is plausibly the difference between a search
   space that can address the dominant failure mode and one that cannot.**

That reframes the top follow-up. It is no longer "run more search"; it is
**vendor `checks/` into the plugin mount so `required_sections` and `constraints`
actually run, then search a space that contains the binding constraint.** If that
holds up on the remaining tasks it is a concrete, defensible contribution: *the
published search space was the wrong space, and here is the measurement that says
so* — which is precisely what goals §1.3 predicted from AHE's own ablation
("gains localise to tools/middleware, not the system prompt").

### 14.4 Second task lands, and it corrects the n=1 reading

```
TutorialSneddon          0.0925   paired=31  gt_unmatched=221  gen_unmatched=6  extra=0
                                  all 11 section scores 0.00
buckleyLeverettProblem   0.7841   paired=37  gt_unmatched=4    gen_unmatched=5  extra=1
                                  Constitutive 0.98  NumericalMethods 1.00  Tasks 1.00
                                  Events 0.94  FieldSpecifications 0.95  Outputs 0.92
                                  Mesh 0.84  ElementRegions 0.77  Geometry 0.53
```

**Correction to §14.3.** I wrote that the failure mode is under-generation. At
n=2 that is *task-specific*, not general. `buckleyLeverettProblem` is essentially
complete — 4 unmatched ground-truth elements out of ~41 — and what costs it score
is **value correctness** (Geometry 0.53, ElementRegions 0.77), not coverage. The
two tasks sit at opposite ends of the same axis:

| | TutorialSneddon | buckleyLeverettProblem |
|---|---|---|
| score | 0.0925 | 0.7841 |
| what is wrong | 221/252 elements **absent** | present but **wrong values** |
| binding constraint | structural completeness | value correctness |

That is exactly the per-task split goals §1.3 predicts ("structural completeness
binds on some, value-correctness on others") — observed here on two tasks of one
simulator rather than across three simulators, but observed, on real rollouts.

**And the conclusion that survives the correction is the stronger one.** Both
rollouts logged:

```
{"decision": "allow", "reason_category": "xml_clean", "retries_so_far": 0,
 "feedback_shape": "structured_errors", "feedback_shape_source": "env"}
```

**Zero hook interventions across a 0.09-to-0.78 score range.** The stop policy was
correctly delivered, correctly read, and *had nothing to say* at either end. It
cannot see a deck that is 15% written, and it cannot see a Geometry block with
the wrong numbers. So the claim is not the weak "the search may not help" — it is:

> On these tasks the searchable stop-policy space is **inert**. Its checks pass on
> both a near-perfect deck and a catastrophically incomplete one, so varying it
> cannot move the score, and any measured movement would be noise.

That is a mechanism for the pre-registered null (plan §7.1), not a shrug. And it
makes the §2.6 vendoring gap the top follow-up rather than a loose end: the checks
that *can* discriminate here — `required_sections` for Sneddon's absent sections,
`constraints` for Buckley-Leverett's wrong values — are precisely the two the
container hook does not implement.

Still n=2, four rollouts outstanding. But note the shape of the evidence: this
conclusion rests on **hook event logs**, which are categorical (`allow`,
`retries_so_far: 0`) rather than on a noisy score difference — so it needs far
less n than a score comparison would.

**Operational gotcha, for whoever runs this next:** killing the driver
(`pkill -f search_geos.py`) does **not** kill the containers it launched. The
first, aborted parallel attempt left an `ExampleIsothermalLeakyWell` rollout
running; it completed 12 minutes later with nobody listening, so the work was
done and thrown away — its parent was gone, so it never reached the corpus.
Check `ps -eo pid,etimes,args | grep run_experiment` after any abort, and either
let orphans finish before relaunching or kill them explicitly. The rollout corpus
makes the *recorded* work resumable; it cannot recover a result whose recorder
died mid-flight.

### 14.5 Four tasks scored — the inertness result is now robust

| task | score | paired | gt unmatched | extra | sections scoring > 0 | hook |
|---|---|---|---|---|---|---|
| TutorialSneddon | **0.0925** | 31 | **221** | 0 | **0 / 11** | allow, 0 retries |
| buckleyLeverettProblem | **0.7841** | 37 | 4 | 1 | 9 / 10 | allow, 0 retries |
| ExampleDPWellbore | **0.8824** | 92 | 12 | 1 | 9 / 10 | allow, 0 retries |
| ExampleIsothermalLeakyWell | **0.9802** | 58 | **0** | 0 | **11 / 11** | allow, 0 retries |

Every single hook event, on every task, at every score:
```
allow   xml_clean   retries=0   shape=structured_errors/env
```

**The headline result of the night, and it is a null with a mechanism:**

> Across scores spanning **0.09 to 0.98**, the searchable stop policy fired
> **zero** times. It was correctly delivered and correctly read every time
> (`source: env` on all five events) — it simply had nothing to say. So on this
> task pool, varying the stop policy cannot move the score, and any movement a
> search reported would be noise.

Three things make this a much better result than "the search didn't help":

1. **It is not a power problem.** The evidence is categorical — five identical
   `allow / retries=0` decisions — not a small difference between noisy means. No
   amount of extra n turns a gate that never fires into one that does.
2. **It says *why*, and the why is actionable.** The checks that could
   discriminate are `required_sections` (Sneddon: 221 of 252 elements absent,
   all 11 sections at zero) and `constraints` (Buckley-Leverett and DPWellbore:
   near-complete, wrong values). **Neither is implemented in the container hook.**
   The instrument is missing, not underpowered.
3. **It vindicates the gate ordering.** Had G1 not been fixed first, this same
   inert policy would have been *silently* inert — and a search over it would have
   produced accept/reject decisions that looked exactly like these, with no way to
   tell the difference. The whole point of R1 was to make this distinguishable,
   and it is: `feedback_shape_source: "env"` is what separates "the policy arrived
   and had nothing to say" from "the policy never arrived".

**Per-task variance is enormous** (0.09 → 0.98 on one adapter, one seed). Two
consequences carried forward: a mean over this pool is dominated by slice
composition, which is precisely the argument for GEPA's per-task Pareto selection
over mean hill-climbing; and any comparison must be **paired per task**, which is
what `report_geos.py` does.

**Scope note, so this is not over-read.** The inertness result is about the
**stop-policy component specifically**, not about the search as a whole. The
candidate manifest has five components — `primer`, `memory`, `constraints`,
`stop_policy`, `checks` — and the other four are untouched by this finding. The
proposer's own first real edit (§9) targeted `memory`, and content of that kind
("declare every section the physics requires") is a plausible lever on exactly the
under-generation that sinks TutorialSneddon. So the search is still worth running;
what the result says is that **one of its five dimensions is a dead axis on this
pool, and we can now prove that rather than suspect it.**

That is itself an ablation result obtained for free: of the four adopted methods,
the stop-policy search space contributes nothing measurable here, and it was the
one v1's design leaned on hardest.

### 14.6 The R3 hand-inspected rollout — and a confound in the evaluator

The single-task R3 probe (`scripts/run_one_rollout.py`, default 1800 s timeout)
finished:

```
=== rollout in 1808s ===
score:  0.3245   status=success
cost:   Cost(tool_calls=90.0, ...)
error:  harness timed out
validator: {"severity": "info", "message": "input validation passed",
            "location": "PoroElastic_Mandel_benchmark_fim.xml"}
detail: paired_elements 52, gt_unmatched 97, gen_unmatched 1, n_extra 0
```

Four things to take from this, in order of how much they matter.

**1. A rollout can hit a 30-minute wall.** ExampleMandel used **90 tool calls** and
was still working when the timeout cut it off. So wall-clock per rollout is not
just "slow", it is long enough that the timeout truncates real work.

**2. That makes `timeout_s` a hyperparameter of the *evaluator*, and a confound.**
A truncated rollout scores lower because the deck is unfinished — 97 ground-truth
elements unmatched here, with `gen_unmatched: 1` and `n_extra: 0`, i.e. everything
written was right and there simply was not time to write the rest. Two candidates
compared under different timeouts are not comparable, and a candidate that makes
the agent *more thorough* is penalised by a tight timeout in a way that looks
exactly like a worse candidate. **Recommendation: pin the timeout across every arm
of any comparison and record it beside the score.** Tonight's baseline used 2400 s
uniformly; the probe's 1800 s result must not be pooled with it.

**3. Scoring survived the timeout, which is the v1 defect not recurring.** Score
`0.3245` was computed on the timed-out run rather than lost. `SubprocessRunner.run`
has "nothing between here and the Rollout may return early" for exactly this
reason — v1's bug was structural, scoring sitting past a branch that was never
taken. Confirmed live.

**4. The timeout is correctly *not* classified as infrastructure failure.** Status
stays `success` with `error: "harness timed out"`, and the §8.3 change deliberately
excludes timeouts from `harness_error`: a held run lock is someone else's fault, but
an adapter that makes an agent slow is a real property of the adapter. Working as
designed.

### 14.7 Fifth task, and the wall-clock table

```
AdvancedExampleDruckerPrager   0.8542   success   1549s   55 tool calls
```

Measured rollout wall-clock on this pool, seed adapter, ox-alpha, 6-way parallel:

| task | seconds | tool calls | score |
|---|---|---|---|
| TutorialSneddon | 482 | 30 | 0.0925 |
| buckleyLeverettProblem | 617 | 36 | 0.7841 |
| ExampleIsothermalLeakyWell | 738 | 28 | 0.9802 |
| ExampleDPWellbore | 745 | 45 | 0.8824 |
| AdvancedExampleDruckerPrager | 1549 | 55 | 0.8542 |
| ExampleMandel | >1570 (running, 84 calls) | — | — |

**8–26+ minutes per rollout, and the spread is 3×.** Two planning consequences:

- **Budget by the slowest task, not the mean.** A 6-task slice at 1 seed is
  ~26 min of wall-clock when run 6-wide, because it finishes when ExampleMandel
  finishes. Adding parallelism past the slice width buys nothing on a single
  candidate; it only helps across candidates.
- **ExampleMandel is close to pathological here** — 84 tool calls and counting,
  and the 1800 s probe of the same task timed out at 90. It is the task most
  distorted by the timeout confound in §14.6, and it is the one to watch when
  interpreting any candidate that appears to "improve" on it.

---

## 15. BASELINE COMPLETE — the seed adapter on GEOS (14:35)

```
6 rollouts in 40.1 min (401 s each, 6-way parallel, 0 harness errors)

  AdvancedExampleDruckerPrager    0.8542   success
  ExampleDPWellbore               0.8824   success
  ExampleIsothermalLeakyWell      0.9802   success
  ExampleMandel                   0.3349   success
  TutorialSneddon                 0.0925   success
  buckleyLeverettProblem          0.7841   success

mean 0.6547   zero rate 0.000   n=6
```

Slice plan written to `/home/matt/src/sci-sim-op/.evolve/geos_search/slices.json`:
```
anchor: ExampleMandel [boundary], buckleyLeverettProblem [boundary],
        AdvancedExampleDruckerPrager [coverage], ExampleDPWellbore [fresh]
probe : ExampleIsothermalLeakyWell   (evidence only, never scored)
```

### 15.1 Reading it

**Zero rate is 0.000, and that is the most consequential number here.** The whole
reliability claim in the SIGA line is about preventing zero-score terminations —
"the gain is reliability, not quality", across-run sigma falling an order of
magnitude by removing catastrophic failures. **On this pool the seed adapter has
no catastrophic failures left to remove.** Six for six produced a scorable deck;
`TutorialSneddon` at 0.0925 is bad but it is not a zero.

That removes the mechanism through which the adapter's measured benefit was
supposed to operate. `core/acceptance.py`'s regression gate is built around
exactly this quantity — `require_zero_rate_non_increasing`, "a single such run is
worth ~0.08 of cell sigma" — and with a zero rate of 0.000 that clause **cannot
bind in either direction**. Combined with §14.5 (the stop policy never fires),
two of the search's instruments are measurably inert on this pool *before the
search starts*.

**The spread is the story, not the mean.** 0.09 → 0.98, and mean 0.6547 describes
none of the six tasks. Any mean-based comparison on this pool is mostly reporting
slice composition. This is the concrete case for GEPA per-task Pareto selection
and for paired per-task reporting, both of which are what is wired.

**ExampleMandel = 0.3349** here, at a 2400 s timeout, versus **0.3245** in the R3
probe at 1800 s where it timed out. Two different timeouts, near-identical scores —
weak evidence that the extra 10 minutes bought almost nothing on this task, which
slightly softens the §14.6 confound worry without dismissing it. n=1 each; not
conclusive.

### 15.2 The search is running

```
$ uv run python scripts/search_geos.py --stage search --budget 3 --seeds 1 \
    --screen-tasks 2 --parallel 6 --timeout 2400 --out .evolve/geos_search
```
launched 14:35, log at
`/tmp/claude-1009/-home-matt-src-sci-sim-op/c7aba9f2-a687-4523-ba3a-ed8001fa2522/scratchpad/logs/search.log`.

The seed's anchor scores **replay from the corpus for free** — the resume
machinery earning its keep on first use, not in a hypothetical crash. Expect
~6 rollouts per proposal (2 screen + 4 full) and ~25 min per full slice, so
budget 3 is roughly 1.5–2 hours.

**Pre-registered prediction, recorded before the result exists** (this is the
kill criterion from plan §7.1, and §14.5/§15.1 give it a mechanism):

> The search returns approximately its seed. Two of the four ingredients are
> already measured inert on this pool — the stop policy never fires, and the zero
> rate is already 0.000 so the regression gate's central clause cannot bind. What
> is left with any room to move is the `memory` / `primer` / `constraints` content,
> and the single failure mode with real headroom is TutorialSneddon's
> under-generation (221 of 252 elements absent). If the search moves anything, it
> should move that task and little else.

Whatever comes back, it gets reported. A null here is a first-class outcome with a
mechanism attached, which is a better paper than a leaderboard number.

---

## 16. SEARCH RESULT — and the reason it is not a result about searching (14:35–15:00)

```
=== search finished in 7.8 min, 5 rollouts ===
proposed 3, screened out 0, hygiene-blocked 3, proposer failures 0, probe rollouts 1
archive: 4 candidates, 1 accepted, 1 on the frontier
decisions: 3, accepted 0%, cycling 0%
proposer calibration: mean hit rate 0.00 over 3 predictions
edit types: add=3
rejections: hygiene=3
best cand_78856ef8131e: mean 0.7139     <- the seed
seed cand_78856ef8131e: mean 0.7139
total rollout cost: tool_calls 251, wall 3637 s, in 222 751 tok, out 110 115 tok, usd 0.00
```

**The search returned its seed exactly** — which is the pre-registered null from
§15.2. But it did **not** return its seed for the reason the null predicted, and
reporting it as a confirmation would have been wrong. All three proposals died at
the hygiene gate. Zero reached an evaluator.

### 16.1 Chasing it down found two bugs and one substantive discovery

**Bug 1 — the decision log named the wrong cause.** Every rejection read:
```
hygiene: Finding(source='path_component', severity='warn',
                 message="names ground-truth directory component 'inputs'",
                 location='PRIMER.md:6')
```
`PRIMER.md:6` is `- Write your final XML output to `/workspace/inputs/`.` — the
task's own required output directory, and a **`warn`**. Warnings never block. The
loop reported `findings[0]`, i.e. whichever rule happened to run first, so a run
blocked by a task-id leak was logged as a benign path warning **pointing at the
wrong file**. I lost ten minutes to it, and the decision log is supposed to be
the audit trail. Fixed in `core/search.py` to report the blocking `errors`; test
added (`tests/test_search.py`).

**Bug 2 — mine.** `Candidate.materialize()` needs `scaffolding_from`; the driver
crashed writing the winner out *after* the search completed. Results were already
on disk, nothing lost. Fixed.

**The discovery: the seed adapter is itself hygiene-blocked.**
```
$ check_candidate(Candidate.from_dir('.evolve/seed'), corpus)
SEED blocked = True
  warn  path_component     names ground-truth directory component 'inputs'      PRIMER.md:6
  error task_id            names evaluation task id 'kgdToughnessDominated'     memory/cheatsheet.md:31
  error rare_token_overlap 23 rare ground-truth identifier(s) (idf weight 105.2) memory/cheatsheet.md
  warn  near_miss_filename 'TriaxialDriver' is GT deck stem 'triaxialdriver' minus the extension
  warn  near_miss_filename 'kgdToughnessDominated' is GT deck stem, extension omitted
  warn  near_miss_filename 'ViscoExtendedDruckerPrager' near miss (0.88) for 'viscoexte...'
```

Every child inherits `memory/cheatsheet.md` from the seed, so **every child
inherits both errors, and the acceptance rate is structurally 0% no matter what
the proposer writes.** This search could not have accepted anything.

### 16.2 Why this matters more than the bug

**A null from this configuration is an artifact, not evidence.** Had I reported
"the search returned its seed, as predicted" without opening the decision log,
I would have confirmed a pre-registered prediction with a result that contains no
information about searching at all. The prediction being *right* is exactly what
made it dangerous. That is the campaign's own failure mode — a plausible number —
recurring at the level of my own analysis rather than in the code.

**And G3 did not catch it, for an interesting reason.** In §4.3 I audited this
same seed with repo3's `audit_lineage.py` and got **0 BLOCK, 1 warn**. The two
gates disagree because they check against different corpora:

| | corpus | verdict on the seed |
|---|---|---|
| `repo3/scripts/siga_evolve/audit_lineage.py` | the **17** task ids in `run_full_evolution.sh` | 0 BLOCK |
| `harness_evolve.hygiene.gate` | all **46** tasks in `experiments_gt` | **blocked**, 2 errors |

`kgdToughnessDominated` is a task id in the 46-task evaluation set but not in the
17-task lineage split, so repo3's audit had no reason to flag it. **Neither gate
is wrong; they answer different questions,** and I passed G3 on the narrower one.
Recorded as a correction to §4.3: the seed is clean *against the 17-task split*
and contaminated *against the full evaluation set*.

**Is this real contamination?** Partly, and it needs a human decision rather than
my judgement call:
- `task_id` naming `kgdToughnessDominated`: a genuine leak against the 46-task
  set. Not in tonight's 6-task pool, so it did not affect tonight's scores.
- `rare_token_overlap` (23 identifiers, idf 105.2): much weaker. The cheatsheet is
  *about* GEOS, so it will inevitably share vocabulary with GEOS decks. This rule
  may be over-firing on a domain cheatsheet, which is a tuning question about the
  rule, not evidence about the adapter.

This is the paper's own hand-designed M (`plugin/memory_primer_m1u.md`), so it is
a finding about the published artifact, not about anything built tonight.

### 16.3 What must happen before any search result is believed

1. **Decide the corpus the hygiene gate scores against** — the 17-task split or
   all 46. Tonight's disagreement comes entirely from that choice.
2. **Resolve the seed's two errors.** Either remove the `kgdToughnessDominated`
   line from the cheatsheet and re-seed, or make an explicit, recorded decision
   that the rule is over-firing. **Do not lower the gate to make the search run** —
   that is the failure this project exists to prevent.
3. **Re-run the search.** Until the seed passes its own gate, acceptance rate is
   0% by construction and the loop measures nothing.

The proposer is not the problem: 3 proposals, 3 parsed, 0 proposer failures, all
`edit_type=add`, calibration 0.00 over 3 predictions (meaningless at n=3 and with
no proposal ever evaluated).

```
$ uv run python -m pytest tests/ -q
573 passed, 2 skipped
```

---

## 17. The blocker is a false positive in the hygiene gate, and it is provable (15:00–15:20)

Added `--hygiene-scope {pool,all}` to the driver, plus a **refusal**: the search
now exits rather than running a loop whose acceptance rate is 0% by construction.

```
$ ... --stage search --hygiene-scope all
hygiene scope: all (all tasks); seed blocked = True
  SEED ERROR task_id            names evaluation task id 'kgdToughnessDominated'   memory/cheatsheet.md:31
  SEED ERROR rare_token_overlap 23 rare ground-truth identifier(s) (idf 105.2;
                                e.g. attribute, boundary, conditions, deadoilfluid,
                                injection, primary)                                memory/cheatsheet.md
the seed adapter does not pass its own hygiene gate, so no child can ...

$ ... --stage search --hygiene-scope pool
hygiene scope: pool (5 tasks); seed blocked = True
  SEED ERROR rare_token_overlap 15 rare ground-truth identifier(s) (idf 50.8;
                                e.g. compressiblesinglephasefluid, extendeddruckerprager,
                                interpolation, traction, viscodruckerprager,
                                viscoextendeddruckerprager)                        memory/cheatsheet.md
```

Scoping to the pool correctly clears the `task_id` leak (that task is not under
evaluation). **`rare_token_overlap` still blocks — and it should not.**

### 17.1 The flagged tokens are public GEOS API names

```
$ grep -c ExtendedDruckerPrager .../GEOS/src/coreComponents/schema/schema.xsd
24
CompressibleSinglePhaseFluid : 5 GEOS source files
ExtendedDruckerPrager        : 2 GEOS source files   (+24 hits in schema.xsd)
ViscoDruckerPrager           : 2 GEOS source files
Traction                     : 5 GEOS source files
```

And under `--hygiene-scope all` the list is worse: `attribute`, `boundary`,
`conditions`, `injection`, `primary` — ordinary English words that happen to be
rare *within the ground-truth corpus*.

**The decisive argument is about what the agent can already see.** `/geos_lib` is
mounted read-only into every rollout, the RAG MCP indexes it, and `geosx
--validate-input` *prints these very names* in its "All available tags are:"
table — the table §2.4 restored. So a cheatsheet naming `ExtendedDruckerPrager`
hands the agent nothing it could not obtain from the tools it already has. **It
cannot be leakage.** A leak is information about *the answer*; this is
information about *the API*.

### 17.2 What the rule is actually measuring

`rare_token_overlap` computes idf over the ground-truth deck corpus, so any token
appearing in few GT decks scores as rare — including a constitutive-model name
used by exactly one physics type. The rule cannot distinguish

- *"the cheatsheet names a GEOS constitutive model"* (vocabulary — necessary, and
  freely available to the agent), from
- *"the cheatsheet names the model **this task** needs"* (an answer),

because it never looks at whether the token is public. **Consequence: no useful
GEOS cheatsheet can pass this rule**, since a cheatsheet's whole job is to name
the right GEOS constructs. That is a blocker on the entire search programme, not
on tonight's run.

### 17.3 Recommended fix — for a human to approve, not for me to apply tonight

Subtract a **public-vocabulary allowlist** from the rare-token rule before
scoring: identifiers appearing in `schema.xsd` or the mounted GEOS source are
public API and cannot be leakage. What survives that subtraction — a task id, a
ground-truth filename stem, a numeric literal matching a specific deck — is real,
and those rules already exist separately and already fire correctly (the
`task_id` error caught a genuine leak here).

I have **not** applied it. Weakening a contamination gate to make a search run is
precisely the move that makes every downstream number unbelievable, and it is the
inverse of what the campaign is for. The refusal I added instead makes the
situation loud: the search will not run until someone decides, on the record,
either that the seed is fixed or that the rule is corrected.

**Note the shape of the night:** the gate that blocked everything and the hook
that read nothing are the same bug wearing opposite clothes. One passed
everything silently, one blocked everything silently, and **both produce a search
that completes, looks normal, and means nothing.**

---

## 18. Closing summary

### What passed
| gate | verdict | how it was proven |
|---|---|---|
| **G1** reward channel | **PASS** | hook event log diffed in the real container: 86 / 1212 / 3038 chars across shapes; control arm with the forwards stripped gives 151 identical chars. Confirmed again in a live rollout (`feedback_shape_source: "env"`). |
| **G2** provider layer | **PASS** | 24/24 live calls, $0.00, real failover, adaptive limit 8→10, 0 throttles at 12-way |
| **G3** quarantine | **PASS** (with a correction, §16.2) | v4 blocks; v0–v3 clean; seed clean *against the 17-task split*, **blocked against all 46** |

### What was measured
Seed adapter, 6 GEOS tasks, ox-alpha, 40 min at 6-way parallel, 0 harness errors:
```
ExampleIsothermalLeakyWell 0.9802   ExampleDPWellbore     0.8824
AdvancedExampleDruckerPrager 0.8542 buckleyLeverettProblem 0.7841
ExampleMandel              0.3349   TutorialSneddon        0.0925
mean 0.6547   zero rate 0.000   n=6
```

### The four findings that matter, in order
1. **The stop policy is inert on this pool.** Zero hook interventions across a
   0.09–0.98 score range, while being demonstrably delivered and read. Categorical
   evidence, so it does not need more n. Gives the pre-registered null a mechanism.
2. **The zero rate is already 0.000**, so the regression gate's central clause
   cannot bind. Two of the search's four instruments are measurably inert *before
   the search starts* — an ablation result obtained without spending a search rollout.
3. **The hygiene gate blocks the seed**, so acceptance was 0% by construction and
   the search's apparent confirmation of the null was an artifact. The blocking
   rule flags **public GEOS API names** (`ExtendedDruckerPrager`: 24 hits in
   `schema.xsd`) that the agent can already read from its own mounted tools.
4. **Three separate ways this stack scored infrastructure failure as model
   failure** — launcher exit 0 with failed tasks, non-zero exit, run-lock collision
   under concurrency. All produce a clean-looking `0.0`.

The through-line: **in a harness-evolution loop the dangerous bugs are not the
ones that crash, they are the ones that produce a plausible number.** R1 (a knob
nothing read), the banner regex (feedback that was stack frames), the harness
exit-0, and the hygiene gate (blocks everything) are four instances of one shape.
Each was found by *running the thing and reading what it actually produced*,
never by reading code.

### Honest accounting of what did NOT get done
- **No compute-matched baseline arms were run.** The harness is built
  (`run_matched_suite` wired, k derived from the ledger) and the command is in
  §13, but no rollouts were spent on it.
- **No ablation arms were run.** All four switches are implemented and exercised
  against the mock; none has been run against GEOS.
- **The search produced no evaluated candidate.** Three proposals, all
  hygiene-blocked before any rollout. So there is **no evidence tonight either for
  or against the search helping** — the null in §16 is an artifact and must not be
  cited as a result.
- **`checks/` was not vendored** into the plugin mount, so `required_sections` and
  `constraints` still cannot run in the container.
- **Only GEOS was touched.** OpenFOAM and LAMMPS were not run.

### The three things to do first tomorrow
1. **Decide the hygiene question on the record** (§17.3): add a public-vocabulary
   allowlist to `rare_token_overlap`, and remove the `kgdToughnessDominated` line
   from the seed cheatsheet. Until then the search cannot accept anything.
2. **Vendor `checks/` into the plugin mount** (§2.6). It is now the highest-value
   change available: `required_sections` is the instrument that detects
   TutorialSneddon's 221 missing elements, and `constraints` the one that detects
   Buckley-Leverett's wrong values — the two binding constraints actually measured.
3. **Then re-run** `--stage search`, and only then the baselines and ablations.
   The pipeline, the resume corpus, and the ablation switches are all in place;
   §13 has the exact commands.

**Total spend: $0.00.** Free-models-only held throughout; every route checked
`usage.cost == 0` on every call, and the hard stop never fired.

**Tests: 523 → 573 (sci-sim-op), 53 → 66 (repo3).**
---

## 19. Post-summary addendum: measuring the noise floor (15:25 →)

The search is blocked pending a human decision on hygiene (§17.3), but that
decision blocks *proposals*, not *measurement*. The most valuable thing still
available — and arguably the most valuable measurement in the whole campaign —
is unblocked, so I ran it rather than stopping.

**Everything in this log so far is n=1 per task.** Every number in §15, every
contrast in §14.4, the whole 0.09-to-0.98 spread — one rollout each. And
`SubprocessRunner.capabilities.deterministic` is **False** by design, with the
reason stated in the source: *"a frozen agent is still a sampler: same candidate,
same seed, different trajectory."*

So we currently cannot distinguish any of tonight's per-task differences from
run-to-run noise, and neither can anyone who runs a comparison tomorrow. **Until
the within-task variance of the seed adapter is known, no future search result is
interpretable** — a candidate that moves TutorialSneddon from 0.09 to 0.35 might
be a real rescue or might be Tuesday.

This matters especially given the campaign's own framing. The reliability claim in
this line of work is a claim *about variance*: across-run sigma falling roughly an
order of magnitude by removing zero-score terminations. §15.1 found the zero rate
is already 0.000, which removes that mechanism — but it says nothing about the
non-zero variance that remains, which is exactly the quantity a search would have
to beat.

```
$ uv run python scripts/search_geos.py --stage baseline --seeds 1,2,3 \
    --task-list <the same 6> --parallel 6 --timeout 2400 --out .evolve/geos_search
seed cand_78856ef8131e on 6 tasks x 3 seeds = 18 rollouts
    [all 6 seed-1 rollouts replayed instantly from the corpus, free]
```
12 new rollouts, 2 waves at 6-way, ~50–60 min expected. The resume corpus paid for
a third of the run before it started — the second time tonight that machinery has
earned its keep on real work rather than in a hypothetical crash.

**What this buys, concretely:** a per-task standard deviation for the seed adapter,
which turns every future comparison from "the number moved" into "the number moved
by more than N sigma". It also directly tests the §14.4 claim that TutorialSneddon
is a *structural* under-generation failure: if its variance is small, the 0.0925 is
a stable property of the task-plus-adapter and the under-generation reading holds;
if it swings wildly, that reading was one draw.

---

## 20. The hygiene fix, implemented but **off by default** (15:30–15:50)

§17.3 said the fix belongs to a person, not to me at 3am. That is still true of
the *decision*. It is not true of the *implementation*, and leaving tomorrow's
decision as a coding task rather than a one-line flip helps nobody.

So `GateConfig.public_vocabulary: frozenset[str] = frozenset()` now exists,
**empty by default — behaviour is unchanged, no result moves** — and
`rule_rare_token_overlap` subtracts it before scoring. Plus
`public_vocabulary_from(paths)` to build the set from a schema file or source
tree.

Turning it on for GEOS is one line:
```python
config = GateConfig(public_vocabulary=public_vocabulary_from([
    Path("/data/shared/geophysics_agent_data/data/GEOS/src/coreComponents/schema/schema.xsd"),
]))
```

Four tests, and the shape of them is the point:

| test | asserts |
|---|---|
| `..._blocks_a_domain_cheatsheet_by_default` | the **current** false positive, pinned so the default cannot drift silently |
| `public_api_names_can_be_exempted_on_purpose` | the exemption clears it |
| `the_exemption_does_not_hide_a_real_leak` | ground-truth-specific tokens (`kgdedgebased`, `mandelPrism6`) **still error** even with the exemption on |
| `public_vocabulary_is_extracted_from_real_sources` | extraction works, and respects `min_len` |

The third is the one that matters. A contamination exemption that also hides real
leaks would be strictly worse than the false positive it fixes, so it is tested
directly rather than argued for.

**Still not enabled anywhere.** The decision remains: (a) turn this on for GEOS,
and (b) remove the `kgdToughnessDominated` line from the seed cheatsheet — that
one is an unambiguous leak against the 46-task set and no exemption should cover
it. Both are recorded in §16.3 and §17.3.

```
$ uv run python -m pytest tests/ -q
577 passed, 2 skipped          # 523 at session start
```

---

## 21. **CORRECTION: my top recommendation was wrong.** Tested it; it fails (15:50–16:05)

§14.5, §16.3 and §17 all said the same thing: *vendor `checks/` into the plugin
mount, because `required_sections` is the instrument that detects
TutorialSneddon's 221 missing elements.* That is a testable claim and the
artifacts were already on disk, so I ran it against the real rollouts instead of
asserting it further.

**It is false.**

```
=== TutorialSneddon   [under-generating, scored 0.0925]
    files=1
    present_sections = Constitutive, ElementRegions, Events, FieldSpecifications,
                       Functions, Geometry, Mesh, NumericalMethods, Outputs,
                       Solvers, Tasks          <- all 11 present
    required         = Constitutive, ElementRegions, Events, Mesh
    (no findings)
    -> hook would block: no
```

`Sneddon_embeddedFrac.xml` has **38 elements against a 252-element ground truth**
and yet contains **every required section, and all 11 optional ones**. The deck is
a complete skeleton and an empty body.

`required_sections` is a **section-presence** check. Under-generation at this
scale is an **element-count** failure *inside* present sections. The check cannot
see it. `constraints` also produced nothing (the seed ships an intentionally
empty `constraints.yaml`). So vendoring `checks/` would **not** have bought the
benefit I claimed for it, on the exact task I claimed it for.

### 21.1 And it would have made things worse

The same test on the pool's best task:

```
=== ExampleIsothermalLeakyWell   [scored 0.9802, the best in the pool]
    error parse  file does not parse: syntax error: line 1, column 0   x4
    -> hook would block: YES
```

The four files are `pressure.geos`, `xlin.geos`, `ylin.geos`, `zlin.geos` —
GEOS **table data**, not XML:
```
$ head -1 pressure.geos
3.086e7
```
`GeosSpec.parse()` deliberately collects `.geos` files ("a hygiene check that
cannot see them cannot flag them"), and `check_parse` then tries to XML-parse
them and errors. **Vendoring `checks/` as-is would have blocked the
highest-scoring rollout in the pool, four times, on legitimate output.**

So the honest version of the recommendation is:

> Vendoring `checks/` is **not** the top follow-up. As it stands it would fix
> nothing measured tonight and would introduce a false block on valid table data.
> Two prerequisites first: (a) `check_parse` must only XML-parse files the
> simulator says are XML — a one-line fix with a clear test; (b) a check that
> actually detects under-generation has to be **written**, because none exists.
> Something like "element count is implausibly low for the requested physics" or
> a per-section minimum. That is new work, not integration work.

### 21.2 Why I am writing this up so prominently

I had this recommendation in three separate sections, stated with confidence, and
it was wrong. It survived because it was *plausible* — "the check named
`required_sections` detects missing sections" is true, it just is not the failure
mode present. One command against artifacts already on disk falsified it.

That is the same failure this entire campaign is about, occurring in my own
analysis: **a plausible claim that nothing had actually checked.** R1 was a knob
nothing read; the banner regex was feedback nobody had looked at; the hygiene
gate blocked everything and reported a warning; and my recommendation was a fix
nobody had run. Four instances, one shape.

The standing instruction in the reconciliation doc — *prefer measuring over
asserting* — is the correct response, and I should have applied it before writing
the recommendation down three times, not after.

**Superseding the "do first tomorrow" list in §18:**
1. **Decide the hygiene question** (§17.3, §20) — unchanged, still first; the
   search cannot accept anything until it is settled.
2. **Fix `check_parse` to respect the simulator's XML extensions**, and **write a
   check that detects under-generation**. Only then is vendoring worthwhile.
3. **Re-run the search**, then baselines, then ablations.

### 21.3 Prerequisite (a) done: `.geos` table data is no longer XML-parsed

Unlike the hygiene exemption in §20, this one is a plain defect rather than a
policy decision, so I fixed it rather than leaving it.

`GeosSpec.parse()` walked `("xml", "geos")` and ran `ET.parse` on both.
`.geos` is GEOS **table data** — a column of numbers referenced by
`<TableFunction>`:
```
$ head -1 pressure.geos
3.086e7
```
so every one produced `syntax error: line 1, column 0`, landed in
`artifact.parse_errors`, and `check_parse` reported it as an error. It is now
collected but not XML-parsed. Collecting and parsing are different jobs, and the
original comment ("a hygiene check that cannot see them cannot flag them")
justifies the first, not the second.

Three tests, including one end-to-end through `run_checks` — and one asserting a
genuinely broken deck **still** errors, so the fix cannot be a blanket silencing.

Re-running §21's falsification against the real artifacts, post-fix:
```
TutorialSneddon             [0.0925 under-generating]  findings=0  blocks=no
ExampleIsothermalLeakyWell  [0.9802 near-complete]     findings=0  blocks=no
buckleyLeverettProblem      [0.7841 wrong values]      findings=0  blocks=no
```
The false block on the best rollout is gone. **And the substance of §21 stands
unchanged: zero findings on the 0.0925 deck.** The vendored check set still
cannot see under-generation, so prerequisite (b) — *write* a check that can —
remains the real work, and it remains unwritten.

Note what this now says: `parse`, `required_sections` and `constraints` **all
pass** on a deck scoring 0.0925 and on one scoring 0.9802 alike. That extends
§14.5's inertness result from the two checks the hook implements to **all five
registered checks**. The gap is not which checks are wired up; it is that no
check in the registry measures completeness.

```
$ uv run python -m pytest tests/ -q
580 passed, 2 skipped
```

### 21.4 Prerequisite (b): why I did NOT write the completeness check

The obvious next move is to write the missing check — "this deck is implausibly
small for the requested physics". I deliberately did not, because **every cheap
way to write it is a contamination leak**, and shipping a leaky check into the
gate that exists to prevent contamination would be a bad trade at any speed.

The hazard, concretely. A completeness check needs a notion of *expected* size or
*expected* content. Where that comes from decides whether it is a check or a leak:

| source of the expectation | verdict |
|---|---|
| ground-truth element count for this task | **leak.** This is the answer, handed to the agent through the feedback channel. It would inflate every score and the inflation would be invisible. |
| ground-truth element *types* (`missing_element_types` from the scorer) | **leak**, same thing, more specific. Note `TutorialSneddon`'s score detail already lists all 16 — it is *right there*, which is exactly what makes this tempting. |
| a global constant ("decks have >100 elements") | not a leak, but close to useless: real GT decks in this pool run from ~41 to ~252 elements. A threshold that clears the small ones cannot flag a 38-element deck that should be 252. |
| the task's own specification text | **legitimate** — the agent is given it. Requires parsing intent out of prose. |
| the reference decks the agent can already read via RAG / `/geos_lib` | **legitimate** — the agent can reach them, so nothing is added that it could not obtain. Probably the right basis. |

The last row is the promising one and it is real work: pick the structurally
nearest reference deck the agent has access to, and compare element counts per
section against *that*. It is defensible precisely because it uses only what the
agent could have looked up itself — the same argument that makes the public-vocabulary
exemption in §20 correct.

**It also needs the hygiene gate pointed at it before it is trusted.** A check
whose feedback text quotes ground-truth-derived content would leak through the
*feedback channel* rather than through the adapter, and nothing currently audits
that path. That is worth noticing on its own: **the hygiene gate audits the
adapter, not the hook's feedback.** Tonight the feedback is validator output, which
is safe; a completeness check would be the first thing to make that path
interesting.

Left for a person, with the design constraint written down rather than discovered
later.

---

## 22. The noise floor overturns two of my own claims (16:20–16:40)

Running the seed at three seeds was the right call: it falsified two things I had
stated with more confidence than n=1 justified.

### 22.1 CORRECTION — the zero rate is **not** 0.000

§15.1 said "zero rate 0.000, and that is the most consequential number here",
and concluded the regression gate's `require_zero_rate_non_increasing` clause
cannot bind. That was six rollouts, one per task.

At three seeds, **ExampleMandel seed 2 scored 0.0000, status `parse_error`.**
Catastrophic terminations do occur on this pool; n=1 per task simply missed them.
Zero rate is ~1/18 overall and 1/3 on that task. **The regression gate's central
clause has something to bind on after all, and §15.1's inference from it is
withdrawn.**

### 22.2 …and the cause reverses my "the stop policy is inert" claim, partially

I first assumed the timeout truncated the file mid-write. **Wrong** — the deck is
complete: 670 lines, closing `</Problem>`. The actual defect:

```xml
<!-- ==========================================================================
     Mandel's 2D consolidation problem -- coupled poroelasticity benchmark
```
**`--` inside an XML comment**, which XML forbids. `not well-formed (invalid
token): line 4, column 41`. One of the oldest traps in XML, in a decorative
banner, 666 lines away from anything the model was reasoning about.

And the decisive part:

```
$ run_checks(artifact, ctx, ["parse"])
findings: [error 'file does not parse: not well-formed (invalid token): line 4, column 41']
would block: True
```

**The `parse` check catches this exactly.** It is precisely the right instrument.
It never ran — because the rollout **timed out** (2365 s of 2400, 114 tool calls,
`process_status: running`), the agent never ended its turn, and **the Stop hook
only fires on turn end.** The rollout has *no* `.verify_hook_events.jsonl` at all.

So §14.5 needs splitting into two claims, only one of which survives:

| | claim | status |
|---|---|---|
| A | On rollouts where the agent ends its turn, the stop policy fires and has nothing to say (5/5 `allow`, 0 retries, scores 0.09–0.98) | **stands** |
| B | Therefore the stop policy cannot affect the score on this pool | **withdrawn** |

B is wrong. On the one rollout that produced a zero, the stop policy was the
right instrument and was **structurally prevented from running**. That is not
inertness; it is a delivery failure, and a fixable one.

### 22.3 What this actually means — the timeout is not a nuisance, it is a mechanism

§14.6 called the timeout a confound because it truncates work and depresses
scores. It is worse than that:

> **A timeout does not merely lower a score. It disables the entire stop-policy
> mechanism for that rollout, and the failure mode it disables the defence
> against — unparseable XML — is the largest block category in the run7/run9
> lineage and produces a hard zero rather than a low score.**

The causal chain: long task → timeout → agent never ends its turn → Stop hook
never fires → `parse` never runs → an `--`-in-a-comment typo that one hook
invocation would have caught and fed back becomes a 0.0000.

Three consequences, in order of importance:

1. **The measured "adapter prevents zero-score terminations" effect is partly a
   statement about timeout headroom.** Give the agent enough time to end its turn
   and the hook gets to fire; do not and the guard is absent regardless of what
   the stop policy says. Any cross-condition comparison must hold the timeout
   fixed *and* report the rate of rollouts that hit it — otherwise the guard's
   availability varies silently between arms.
2. **A PostToolUse hook would close this hole**, and one already exists —
   `repo3/plugin/hooks/verify_xml_post_write.py`, described as catching XML parse
   errors "immediately after each Write|Edit|MultiEdit so the agent gets feedback
   within seconds instead of after end-of-turn". That is exactly this failure. Whether
   it was active in these runs is **not** something I verified; it should be the
   first thing checked tomorrow, because if it was active and did not catch this,
   that is its own bug.
3. **`ExampleMandel` timed out on both seeds** (2400 s, 84–114 tool calls). It is
   not a hard task so much as a *long* one, and it is the only task in the pool
   generating zeros. Either raise its timeout or record it as timeout-censored;
   pooling it with the other five at face value mixes two different measurements.

### 22.4 On the pattern of tonight's errors

That is the third claim I have had to withdraw or correct today — the
`required_sections` recommendation (§21), the truncation hypothesis above, and
the zero-rate inference. Each was plausible, each came from reasoning rather than
from running something, and each took one command to falsify once I actually
looked.

The reconciliation doc's instruction — *prefer measuring over asserting* — is
not a style note. On this project, the plausible-but-unchecked claim is the
characteristic failure mode, and it applies to the analyst exactly as much as to
the code.

---

## 23. The PostToolUse hook was shipped and switched off — and it is the fix (16:40–16:55)

§22.3 flagged `verify_xml_post_write.py` as a possible remedy and said I had not
checked whether it was active. Checked. **It was not.**

```
$ cat <rollout>/claude_settings.json
{"hooks": {"Stop": [{"hooks": [{"command": "python3 /plugins/repo3/hooks/verify_outputs.py", ...}]}]}}
```
Only `Stop`. Meanwhile the adapter directory materialised for every rollout does
contain the file:
```
$ ls .evolve/geos_search/rollouts/adapters/*/hooks/
hooks.json  verify_outputs.py  verify_xml_post_write.py
```

`repo3/src/runner/claude_settings.py:write_claude_settings` explains it: the
PostToolUse hook is registered **only when `GEOS_HOOK_POSTTOOLUSE` is truthy**,
and it is off by default *deliberately*, "to preserve parity with the
autocamp-experiment-state harness". `GEOS_HOOK_POSTTOOLUSE` was unset in every
run tonight (`env | grep -c` → 0).

Its own docstring describes precisely the failure that produced tonight's only
zero:

> *Catches the `<<TagTag>` failure mode within seconds so the agent can fix via
> Edit instead of discovering it at end_turn and rewriting whole files under the
> 40-min budget. Cheap (~50 ms per check).*

The ExampleMandel zero was an `--` inside an XML comment in a decorative banner.
A per-write parse check would have caught it **seconds after the Write**, with
~35 minutes of budget left — instead of never, because end_turn never came.

**So the fix for the only catastrophic failure in 18 rollouts is a flag that
already exists, costs ~50 ms per write, and is off for backwards-compatibility
with a historical experiment.**

### 23.1 The concrete recommendation this yields

**Add `post_tool_use: bool` to `StopPolicy` and make it searchable.**

Unlike my `required_sections` recommendation — which I asserted three times and
then falsified in §21 — this one has direct evidence behind it:

- the only zero in 18 rollouts was caused by a malformed-XML defect;
- the `parse` check catches that defect (verified, §22.2), and the Stop hook could
  not run it because the turn never ended;
- a PostToolUse check runs *per write*, so it does not depend on turn end;
- the mechanism is already implemented, already shipped into every adapter, and
  gated behind one env var.

It also fits the campaign's framing exactly. The paper's claim is *"static gates
raise the floor, closed-loop retries driven by validator output raise the
ceiling"* — and **when the gate fires** turns out to matter as much as **what it
checks**. That is a searchable, testable, mechanistic hypothesis, and the search
space currently does not contain it.

**Caveat I am not going to paper over:** `GEOS_HOOK_POSTTOOLUSE` also un-gates
`_doubled_bracket_hint` in `verify_outputs.py`, so the flag changes two things at
once. If it enters the search space it should be split into two fields, or the
confound recorded.

## 24. Noise floor — the full table

Seed adapter, 3 seeds, 6 tasks (17 rollouts; ExampleMandel seed 3 outstanding):

| task | s1 | s2 | s3 | spread | reading |
|---|---|---|---|---|---|
| ExampleIsothermalLeakyWell | 0.9802 | 0.9695 | 0.9741 | **0.011** | stable, near ceiling |
| buckleyLeverettProblem | 0.7841 | 0.7788 | 0.7774 | **0.007** | stable |
| TutorialSneddon | 0.0925 | 0.0759 | 0.0953 | **0.019** | **stable, near floor** |
| AdvancedExampleDruckerPrager | 0.8542 | 0.8639 | 1.0000 | **0.146** | occasional jackpot |
| ExampleDPWellbore | 0.8824 | 0.9100 | **0.3438** | **0.566** | occasional collapse |
| ExampleMandel | 0.3349 | **0.0000** | — | **0.335** | timeout-censored, 1 zero |

### 24.1 This is the single most important table in the log

**Per-task variance is wildly heterogeneous — 0.007 to 0.566 — and that changes
how every other number here must be read.**

1. **Three tasks are quiet** (σ-range ≤ 0.02). For these, a candidate that moves
   the score by 0.05 is real.
2. **Three are violent** (0.15–0.57). `ExampleDPWellbore` swung from 0.91 to
   **0.34** with nothing changed but the seed. **Any single-seed comparison
   involving these tasks is uninterpretable.** A search that "improved"
   DPWellbore by 0.3 at n=1 would be reporting a coin flip.
3. **§15.1's "the spread is the story" now has a floor under it.** The
   *between-task* spread (0.09 → 0.98) is far larger than any within-task spread,
   so the per-task differences are real signal — but the per-task *movements* a
   search would chase are not, on half the pool.
4. **This retroactively justifies the Pareto archive on measurement grounds, not
   just design ones.** Mean hill-climbing over this pool would be dominated by
   whichever violent task happened to draw well that round.

**Minimum seeds for a believable comparison on this pool: 3, and more like 5 for
the violent tasks.** Tonight's search config used `--seeds 1`. That was the right
call for getting *something* measured in the window, and it is the wrong call for
any comparison anyone reports. Recorded so nobody inherits the default by
accident.

### 24.2 FINAL noise floor — 18 rollouts, 6 tasks x 3 seeds

```
$ uv run python scripts/report_geos.py --out .evolve/geos_search
18 rollouts (18 scored, 0 harness errors)

== cand_78856ef8131e  n=18
   mean 0.6127   zero rate 0.056   min 0.0000   max 1.0000
     ExampleIsothermalLeakyWell    0.9746 +/- 0.0054   n=3
     AdvancedExampleDruckerPrager  0.9060 +/- 0.0815   n=3
     buckleyLeverettProblem        0.7801 +/- 0.0035   n=3
     ExampleDPWellbore             0.7121 +/- 0.3192   n=3
     ExampleMandel                 0.2155 +/- 0.1870   n=3
     TutorialSneddon               0.0879 +/- 0.0105   n=3
   statuses: {'success': 17, 'parse_error': 1}
```
(`18 rollout(s): 12 executed, 6 replayed from the corpus` — the resume path again.)

ExampleMandel's third seed came in at **0.3115**, so its three are
0.3349 / 0.0000 / 0.3115: two consistent runs and one catastrophic parse failure,
which is the §22 story exactly — the failure is a discrete event, not a wobble.

**Per-task σ spans two orders of magnitude: 0.0035 to 0.3192.**

| σ | tasks | what a comparison can detect |
|---|---|---|
| ≤ 0.011 | buckleyLeverett (0.0035), IsothermalLeakyWell (0.0054), TutorialSneddon (0.0105) | a 0.02 move is ~2σ. **Sensitive.** |
| ~0.08–0.19 | DruckerPrager (0.0815), Mandel (0.1870) | needs ~0.2–0.4 to clear 2σ at n=3 |
| 0.32 | **ExampleDPWellbore** | at n=3, the 95% interval on its mean is roughly **±0.36**. Nothing a search could plausibly do is detectable here. |

**Headline for the morning: `zero rate 0.056`, not 0.000.** One rollout in
eighteen terminated catastrophically. §15.1 said 0.000 and drew a conclusion from
it; that conclusion is withdrawn (§22.1). The reliability mechanism the whole
SIGA line is about *is* live on this pool — it is just rare enough that six
rollouts could not see it, which is a lesson about the measurement, not the
adapter.

And the one zero has a named cause (`--` in an XML comment), a check that catches
it (`parse`), a reason that check could not run (no end_turn after a timeout),
and an existing off-by-default mitigation (`GEOS_HOOK_POSTTOOLUSE`). That is a
complete causal chain from a single observed failure to a one-flag intervention —
which is worth more than the aggregate it sits inside.

### 24.3 Slice plan changed once the variance was visible

With 3 seeds, `build_slices` reassigned the anchor:
```
anchor: ExampleMandel [boundary]     mean 0.22, spread 0.15, zero rate 33%
        ExampleDPWellbore [boundary] mean 0.71, spread 0.26, zero rate 0%
        AdvancedExampleDruckerPrager [coverage]
        buckleyLeverettProblem [fresh]
probe : ExampleIsothermalLeakyWell
```
It now selects the two highest-variance tasks as "boundary" — tasks in play,
where movement is possible. That is defensible on its own terms and **directly at
odds with detectability**: these are exactly the two tasks whose σ (0.19, 0.32)
makes movement unmeasurable at n=3. Anyone running the search should know the
anchor is currently composed of the noisiest tasks in the pool. Either raise
seeds substantially or weight slice selection by σ as well as by headroom.

---

## 25. **THE FREE WINDOW CLOSED MID-SESSION** (16:27)

The event the whole campaign was racing happened while it was running.

```
$ python3 scripts/provider_watch.py
openrouter/stealth/ox-alpha  NO  http_404
  -> "Thank you for participating in the Stealth Ox Alpha testing period.
      This model was ZAI's GLM-5.3 Fl..."
nous/stealth/ox-alpha        NO  http_404
  -> {"status":404,"message":"This model free period has ended. Please select a
      different model or upgrade your subscription"}
```

Both providers, explicit end-of-period messages, not capacity errors. **`stealth/ox-alpha`
was ZAI's GLM-5.3 behind the stealth badge**, which is worth recording: the
"stealth" slug was a pre-release channel, and stealth channels end.

### 25.1 What it cost

The 17-task x 3-seed expansion (33 new rollouts) launched at 16:12 and **all 33
returned as harness errors in 1.6 minutes** — instant 404s. Per-rollout artifacts
show `"error": "model_not_found"`, `api_error_status: 404`, *"There's an issue
with the selected model (stealth/ox-alpha)"*.

**The infrastructure handled this correctly and that is worth noting.** All 33
were classified `status="harness_error"` and **excluded from every average** by
the detection added in §5.3/§8.3. Without it, this would have entered the corpus
as 33 rollouts scoring 0.0 — a catastrophic-looking collapse in adapter
performance, on the day the model changed, with no signal anywhere that the cause
was a vendor 404. It would have looked like a real result.

That is the single best validation of the "infrastructure failure is not model
failure" work, and it arrived unprompted.

### 25.2 The 18 ox-alpha rollouts are now a frozen dataset

No more can ever be added. Everything measured in §14-§24 — the noise floor, the
per-task sigmas, the inertness result, the zero-rate — is **ox-alpha-specific and
final**. It is still valid; it just cannot be extended, and **nothing measured on
a different model may be pooled with it**.

### 25.3 Replacement: `z-ai/glm-5.2:free`

Re-screened everything immediately. The 429 storm on the remaining free slugs is
almost certainly everyone else's ox-alpha jobs failing over at once, so patient
retry (the jittered backoff from G2) was the right instrument:

| model | AA index | result |
|---|---|---|
| **`z-ai/glm-5.2:free`** | **51** | **cost=0, 14 s latency** — adopted |
| `minimax/minimax-m3:free` | 44 | cost=0, 126 s latency — viable fallback |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | 48 | "Upstream error from Nvidia: Service temporarily overloaded" |
| `qwen/qwen3-max-thinking:free` | — | 404, free period ended |
| `moonshotai/kimi-k2.5:free` | — | 404, free period ended |
| `thinkingmachines/inkling:free` | 41-42 | 403, "only available on agentic harnesses" |

**glm-5.2 is a better workhorse than what we lost**: AA index 51 versus the
bar of 42, and ~14 s latency against ox-alpha's ~50 s — which, since latency and
not rate limit was the bottleneck (§8.1), should raise rollout throughput
substantially. Cost verified `0` on a real completion.

`scripts/_geos.py` now reads `HARNESS_EVOLVE_MODEL`, defaulting to glm-5.2, so
the next window closing costs one env var rather than an edit.

**Two more free periods ended today** (`qwen3-max-thinking`, `kimi-k2.5`) on top
of `deepseek-v4-flash` earlier and `tencent/hy3` before the campaign began. That
is five closures observed inside one session. The kickoff's premise that the
window is "demonstrably closing" is now overwhelming rather than suggestive.

### 25.4 Consequence for the plan

The noise floor must be **re-measured on glm-5.2** before any glm-5.2 comparison
is believable — per-task sigma is a property of model x task, not of the task.
That is a real cost, and it is also the cross-model panel arXiv:2605.30621 argues
for, arriving by accident: we now have one model's per-task variance profile and
will shortly have a second.

---

## 26. **CORRECTION to §14.5: `stop_policy` and `checks` are not in the search space at all**

A design-review subagent found this and I verified it directly:

```
$ grep -rn "stop_policy" src/harness_evolve/evolvers/ src/harness_evolve/core/search.py | wc -l
0

$ sed -n '314,321p' src/harness_evolve/proposers/llm.py
        if spec.kind == "config":
            raise ProposerError(
                "config components are edited through the manifest, not an "
                "<edit> block"
            )
        if not spec.path:
            raise ProposerError(f"component {edit.component!r} has no file path")

$ sed -n '80,86p' src/harness_evolve/proposers/scripted.py
        text_components = [
            (n, s) for n, s in parent.manifest.components.items()
            if s.is_text and s.path
        ]
```

**No proposer can edit `stop_policy` or `checks`.** `llm.py` refuses `kind="config"`
outright and refuses `checks` because `kind="code"` has no `path`; `scripted.py`
samples only text components. Nothing in `evolvers/` or `core/search.py` mentions
`stop_policy` at all.

So the effective search space is **three text files**: `PRIMER.md` (270 B),
`memory/cheatsheet.md` (2970 B), and `memory/constraints.yaml` (431 B, contents
`constraints: []`). That is a **prose-only search space** — precisely the thing
the method-adoption plan §1.5 diagnoses as v1's error and §3.1 claims to have
fixed.

**What this does to §14.5.** My finding was "the stop policy was delivered,
read, and had nothing to say." That stands as an observation. But I framed it as
a discovery about the *mechanism*, when the more basic fact is that **nothing
would have varied it anyway**. R1 made the stop policy *observable*; it did not
make it *searchable*, and I conflated the two.

The plan's headline design justification — §3.1, *"`stop_policy` and `checks` are
the point... they put S inside the search space for the first time"* — **is not
true of the running code.** That needs correcting in the plan, because the
"v1 searched the wrong space" narrative currently repeats v1's error one layer up.

The restriction is one line: `core/manifest.py:198-203` hard-codes `kind="config"`
as legal only for a component literally named `stop_policy`. So the
best-evidenced intervention available — `post_tool_use` (§23.1) — is **not
expressible in the manifest at all**.

---

## 27. PIVOT: free-only abandoned, cheap-paid adopted (17:10)

Free inference is over as a strategy — five free periods ended inside one session.
Direction from the user: use the cheapest models on the cost/performance Pareto
frontier, measure real costs at very small scale, and produce a budget plan.

OpenRouter list pricing, fetched 2026-08-26:

| model | input /M | output /M | ctx |
|---|---|---|---|
| **`z-ai/glm-5.3-flash`** | **$0.075** | **$0.25** | 1M |
| **`openai/gpt-5.6-luna`** | **$0.20** | **$1.20** | 1.05M |
| `openai/gpt-5.6-luna:batch` | $0.10 | $0.60 | 1.05M |
| `minimax/minimax-m3` | $0.30 | $1.20 | 1M |
| `z-ai/glm-5.2` (tonight's free model, paid rate) | $1.19 | $3.74 | 1M |

`scripts/cost_probe.py` (new) brackets real rollouts with OpenRouter's **own
account usage counter** rather than multiplying tokens by a rate card. An agent
rollout's spend is dominated by turn count and cache-hit rate, neither of which
is on the rate card, and a budget an advisor will act on should not rest on an
estimate when the true number is one API call away.

### 27.1 A capability that was silently unavailable: reasoning effort

`claude --effort <level>` and `CLAUDE_EFFORT` both exist, but **`docker_cmd.py`
forwarded neither**, so "max effort" was unattainable through the rollout path
and would have been silently ignored. Added `CLAUDE_EFFORT` to the forwarded
allowlist — the same additive class as the R1 forwards, and `test_container_spec.py`
(which pins the rendering byte-for-byte) still passes.

This matters for the budget specifically: effort drives output tokens, and output
tokens are most of the bill at luna's $1.20/M. Any luna number measured before
this fix is a **lower bound**.

## 28. Verified findings from the two design subagents

I checked the load-bearing claims rather than relaying them.

### 28.1 The predecessor optimized on more than half its own test set — **verified**

```
$ python3 - <<< "read repo3/data/eval/split.json"
train=26 test=20
val-17 tasks that sit in split.json TEST: 11 / 17
  AdvancedExampleCasedContactThermoElasticWellbore, AdvancedExampleDruckerPrager,
  AdvancedExampleExtendedDruckerPrager, AdvancedExampleModifiedCamClay,
  ExampleDPWellbore, ExampleEDPWellbore, ExampleIsothermalLeakyWell,
  ExampleThermoporoelasticConsolidation, TutorialPoroelasticity,
  buckleyLeverettProblem, pknViscosityDominated
```

The 17-task set the v1 self-evolution loop ran on is **11/17 inside the
designated test split**. This is a contamination fact entirely independent of the
v4 cheatsheet, and it means held-out numbers from that lineage were computed on
tasks the loop had been optimising against. **4 of the 6 tasks measured last
night** are in that test split too.

### 28.2 The 46 tasks are ~27 families, and the existing split straddles them

Clustering ground-truth decks by token/tag Jaccard at >= 0.60 gives **27
families**; three pairs are identical (Jaccard 1.00) and the Drucker-Prager
family's six members are 0.96-0.98 pairwise. `split.json` breaks **6 of 8**
multi-task families across the boundary, so a cheatsheet line for
`ViscoDruckerPrager` (train) transfers nearly verbatim to `DruckerPrager` (test).
**Splits must be family-wise, not task-wise.**

### 28.3 The token cap does not prevent memorisation — **verified, and worse than reported**

```
seed cheatsheet     :  823 tokens   (budget 900)  -> 77 tokens slack ~ 3 lookup rows
v4 full cheatsheet  : 2383 tokens   -> REJECTED by the budget gate
per-row cost        : ~24 tokens    -> a 17-task lookup table is ~400 tokens
```
A full task->answer table for the 17-task val set costs **~400 tokens and fits
comfortably under the 900 cap** — the seed prose is the only thing occupying the
space. **The cap is drift control, not an anti-memorisation device**, and it is
binding today only by accident.

### 28.4 The literature check (subagent re-verified the two decisive papers itself)

- **arXiv:2607.12227** §4.4 verbatim: *"45 training tasks, 10 validation tasks,
  and 34 held-out test tasks"*, and *"the revisions discovered during evolution
  encode **task-specific shortcuts** rather than genuinely better harness design
  principles… prone to **severe overfitting to the training tasks**"*. On the
  disjoint split: **+1.2 / +0.0**. Table 1: initial harness 68.2, parallel
  sampling 72.3, **harness evolution 67.4** — *below its own seed*, and losing to
  plain sampling at matched budget. With unit tests it still loses 75.8 vs 86.0.
- **GEPA** Alg. 1: `D_pareto` is carved out of train and is the selection set.
  The permission rule to copy verbatim: *"Optimizers have full access to the
  train split, including text and labels… **direct access to the content of
  validation instances is restricted**"* — scores yes, content no.
- **The sharpest single quote**, GEPA's own meta-prompt: *"**Identify all niche
  and domain specific factual information about the task and include it in the
  instruction**"*. The field's leading prompt optimiser *instructs* its proposer
  to bake task-specific facts into the always-on artifact. Memorisation is not an
  accident there; it is the design. That is strong support for the reframing:
  **the lever is the split and the capacity budget, not policing the artifact.**
- Of six methods surveyed, **one** (GEPA) has a genuine three-way split. AHE has
  none. ACE's online setting adapts on the test stream. Self-Harness's "held-out"
  is read by the promotion gate every round.
- **None of AHE, Self-Harness or 2607.12227 reports any dispersion statistic or
  significance test.** Every published delta in that literature is a point
  estimate over <=2 repeats. Last night's noise-floor work is already more careful
  than the papers being adopted from.
- Reported-not-verified (flagged by the subagent): the AHE, Self-Harness, ACE,
  Weng-blog and DSPy rows.

---

## 29. Cost measurement, and a cost/validity leak (17:30–18:00)

Full write-up for the advisor: `/home/matt/src/sci-sim-op/docs/2026-08-26_BUDGET_PLAN.md`.
New tooling: `scripts/cost_probe.py`; raw attribution in
`/home/matt/src/sci-sim-op/.evolve/cost_probe/attribution.json`.

### 29.1 Measured, not estimated

| model | $/rollout | wall-clock | tool calls | probe scores |
|---|---|---|---|---|
| **`z-ai/glm-5.3-flash`** | **$0.0381** | 12.6 min | 39 | 0.757 / 0.077 |
| `openai/gpt-5.6-luna` (corrected) | $0.0507 | 3.4 min | 77 | 0.727 / 0.091 |

Near-identical scores; glm-5.3-flash is cheaper and produced no side-model spend.
**Programme total: 560 rollouts ≈ $21.** Money is not the constraint; wall-clock
is (~28 h at 8-way).

### 29.2 My first measurement was wrong, and the cross-check is what caught it

`cost_probe.py` bracketed rollouts with the **global** account usage counter — and
I ran both models **concurrently**, so each attributed the other's spend to
itself: $0.572 and $0.549. Both were ~20-70x what the rate card implied for the
observed token counts, which is what exposed it.

Fix without re-spending: rollout logs carry OpenRouter generation ids
(`gen-…`), and `/api/v1/generation?id=` returns the exact billed amount per call.
Aggregating those gives per-model attribution from data already paid for.
**Lesson for the harness: never attribute cost from a shared counter across
concurrent runs.** `cost_probe.py` should be switched to generation-id
aggregation as its primary method; it currently records the (unreliable) delta.

### 29.3 The finding: a rollout "on luna" was 85% Claude Sonnet 5

```
anthropic/claude-sonnet-5      $0.9020  n=40   <- 85% of the bill
openai/gpt-5.6-luna            $0.1014  n=64   <- the model actually requested
anthropic/claude-4.5-haiku     $0.0614  n=15
```
Events confirm it: `models seen in events: [('openai/gpt-5.6-luna', 57),
('anthropic/claude-sonnet-5', 31)]`, and the tool list includes `Agent` and
`TaskCreate`. **The agent spawned a subagent, and that subagent ran on Sonnet 5.**

`NATIVE_CLAUDE_DISALLOWED_TOOLS` blocked `Skill` and `AskUserQuestion` but not
`Task`/`Agent`. Now blocked.

**This is a validity problem before it is a cost problem.** A rollout labelled
"gpt-5.6-luna" was partly executed by a different, stronger model — so any
cross-model comparison built on it measures an uncontrolled mixture, and the
frozen-agent premise the whole evaluation rests on does not hold. It is the same
shape as every other defect this session: a number that looks fine and means
something other than its label.

Note glm-5.3-flash spawned no subagent, so its figure was clean — which is
exactly why a single-model measurement would not have revealed this.

### 29.4 Spend to date

**$1.27 total on the OpenRouter key** ($0.125 of that predates the campaign — the
hy3 probe). $8.73 remaining on a $10 key.

