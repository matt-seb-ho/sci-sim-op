# W1 — core search machinery

Owner: integrator (me). Scope: `src/harness_evolve/core/`, `proposers/`.

## Built

| File | What |
|---|---|
| `core/manifest.py` | typed component set; stop policy (retries, feedback shape, active checks) is a searchable component |
| `core/candidate.py` | content-addressed, hard token budgets, deletion-as-edit, GEPA component view, scaffolding resolved at materialize time |
| `core/archive.py` | Pareto frontier over per-task scores; domination pruning; GEPA-deferring parent selection |
| `core/acceptance.py` | regression gate: no per-task cliff, no new failures-as-zero, no aggregate drop, no cost inflation |
| `core/decision.py` | decision log, prediction contracts, edit-type taxonomy, calibration / cycling / unearned-edit diagnostics |
| `core/search.py` | the loop |
| `proposers/base.py` | `Proposer` protocol + `Demonstration` |
| `proposers/scripted.py` | `ScriptedProposer` (tests), `RandomEditProposer` (control condition) |

## Decisions

**Free gates before paid gates, in cost order.** Manifest validity → token
budgets → hygiene → gated screening → full evaluation. A rollout costs ~25
minutes; anything that can reject a proposal for free must run first.
`test_hygiene_block_costs_no_rollouts` asserts a contaminated proposal spends
nothing.

**Gated screening on the parent's weakest tasks** (arXiv:2607.13683), not a
random subset. Weakest tasks are where a real improvement should surface first
and where a regression matters most. Margin is deliberately loose (0.15) — at
one seed the noise is large and a tight margin discards good candidates on a
coin flip. `test_screening_saves_rollouts` asserts it actually reduces spend.

**Stagnation widens the parent draw** (arXiv:2605.13941's explore-on-stagnation).
With a strict gate, "nothing accepted" is the *expected* steady state, not an
anomaly — so the loop needs an escape that is not "loosen the gate".

**Evidence is injected as a callable, not imported.** The loop does not depend
on the evidence module's shape, so it runs against mock, cached, or real
evidence identically. Also keeps W1 and W3 decoupled during parallel work.

**A random-edit proposer as a first-class control.** arXiv:2605.30621 finds
harness-*updating* capability is roughly flat across model tiers, measured on
general benchmarks. If a real proposer does no better than random edits under
the same gate, the search is measuring selection pressure rather than
reasoning — and we should want to know that.

**Edit-type accounting from arXiv:2605.20086.** That paper finds ~30% of lines
added during evolutionary search are byte-identical re-introductions of
previously deleted lines. Detecting it costs nothing once the log stores content
hashes, and it is invisible in a score curve — a plateau looks identical whether
the search is stuck or two edits are undoing each other every round.

## What I deliberately did not do

- **No GEPA hard dependency.** `archive.select_parent_via_gepa` defers to GEPA
  when installed and falls back to an exact local implementation otherwise. The
  package must be usable and testable with zero third-party deps.
- **No LLM proposer yet.** Written after the evidence layer (W3) lands, so it
  can be built against the real corpus shape rather than a guess.
- **No merge/recombination operator.** HarnessBank recombines gene-bank entries;
  worth doing, but not before we know single-parent mutation produces anything
  worth recombining.

## Open questions

1. **Screening margin and subset size are unvalidated.** They should be tuned
   against real score variance, which needs the runner. Currently a guess with a
   stated rationale.
2. **The anchor slice is still hand-picked.** Janus (arXiv:2606.31121) proposes
   a principled construction — coverage / boundary / fresh — which is likely
   better than my 8-task spread. Adopt once W7's sweep confirms the details.
3. **`_select_parent` exploratory mode is crude** (uniform over accepted). A
   proper novelty or coverage term would be better.
4. **The gate has no notion of seed noise.** With n=2 during search, a -0.05
   per-task threshold may be inside noise. The right fix is probably to require
   the regression to hold across seeds, not on the seed mean.

## Tests

`tests/test_search.py`, 13 tests, all passing offline in ~0.1s. They exercise
the loop end-to-end against a synthetic problem with a known optimum, including:
a mean-improving candidate correctly rejected for a tail regression, screening
demonstrably reducing rollout count, hygiene blocking before any spend, budget
protection against a failing proposer, stagnation detection, cost accounting,
and unearned-edit detection.

This is the specific gap that let the predecessor fail silently: it had no
end-to-end test, so a reward channel that returned `None` for every task ran for
three rounds unnoticed.

---

## Session 1, later: proposer and integration

### The proposer emits bounded edits, not whole files

`proposers/edits.py` + `proposers/llm.py`. One `<edit>` per proposal, over
`add` / `delete` / `replace` of a single line, following SkillOpt
(arXiv:2605.23904)'s bounded edit model for a single skill document under a
frozen agent.

Two predecessor failures this fixes structurally rather than by instruction:

- **Attribution.** A rewritten cheatsheet differs from its parent in a dozen
  ways, so an accept/reject verdict cannot say which mattered. After three rounds
  nobody could name what any change had done.
- **Monotone growth.** A model asked to "produce the new cheatsheet" produces the
  old one plus something. 270 B to 3159 B in three rounds. With a bounded
  vocabulary, deletion is a first-class move rather than something the model has
  to volunteer.

Anchor matching is deliberately lenient — exact, then normalised, then fuzzy
above 0.82 — because a model quoting a line back will re-wrap or re-punctuate it,
and failing the whole proposal over a stray space wastes a call. It will not
match a merely similar line, which would silently edit the wrong assertion. A
missing anchor **raises** rather than no-opping: a silent no-op would be
evaluated and gated as a real proposal, spending a full round to discover the
artifact never changed.

### Derived constraints are handed over, not guessed

The proposer prompt has a section for constraints the validator has already
stated (`evidence/directives.py`), presented as settled, with an instruction not
to spend an edit rediscovering them. This is the whole point of the directive
mining: the expensive thing is not writing a constraint, it is finding out
whether one is true. When the simulator has already enumerated the legal action
space, that costs nothing.

### Integration items closed

- **`KNOWN_CHECKS` was a snapshot of a registry.** Four hardcoded names, so a
  stop policy naming `cross_section_refs` — a real, shipped check — failed
  validation. The search space silently excluded every check beyond that list.
  Now resolved from the live registry via `resolve_known_checks()`, with a lazy
  failure-tolerant import so `core` stays standalone.
- **Budget ledger wired.** Every rollout is recorded including screened-out,
  rejected, and probe rollouts. A search that counts only its successes
  understates its own budget, which is the accounting error that lets "evolution
  beat the baseline" mean "evolution had more inference compute".
- **`docs/INTEGRATION_REQUIREMENTS.md`** records R1, which is blocking and lives
  in repo3: `docker_cmd.py`'s fixed `GEOS_HOOK_*` allowlist drops the two
  `GEOS_EVOLVE_*` variables at the container boundary, so the search would vary
  feedback shape while the hook saw a constant. Same failure class as the dead
  reward channel, and equally invisible in logs. The doc gives the test that
  settles it: run one task at each feedback shape and diff the hook's event log.

### Still open

1. Screening margin and probe cadence are unvalidated against real variance.
2. The anchor slice is still hand-picked; Janus's coverage/boundary/fresh
   construction is likely better.
3. The gate has no notion of seed noise — a -0.05 per-task threshold may be
   inside noise at n=2. The right fix is probably to require the regression to
   hold across seeds rather than on the seed mean.
4. `RandomEditProposer` should be run as a real arm, not just a test fixture.
   Given that harness-updating capability is reported flat across model tiers,
   "does an LLM proposer beat random edits under the same gate" is a result
   either way.
