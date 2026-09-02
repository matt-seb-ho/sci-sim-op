# SIGA follow-up: what we are trying to do, and what we do first

**Date:** 2026-08-26
**Status:** goals document. The technical basis is
[`repo3/docs/2026-08-19_method-adoption-plan.md`](../../repo3/docs/2026-08-19_method-adoption-plan.md);
the machine state is `repo3/docs/2026-08-26_migration-reconciliation.md`.
This file says *what we are aiming at and in what order*, not how each piece is built.

---

## 0. The one-paragraph version

SIGA showed that a small, always-visible adapter wrapped around a frozen coding agent
lets it configure a scientific simulator far more reliably. The paper also claimed a
self-evolution loop improved that adapter. On re-examination that claim does not hold:
the loop never received a reward signal, and the paper's own held-out table shows the
self-evolved cell is indistinguishable from the hand-designed one. The follow-up is
therefore not "more self-evolution" — it is **building a self-evolution loop that
actually closes, using the methods the field produced in 2026, and measuring honestly
which of their ingredients matter for scientific-simulator configuration specifically.**

Three directions follow. Only one of them is unblocked today, and it is the one that
carries the other two.

---

## Goal 1 — Modernize the self-evolution stack, and build intuition for what helps

**This is the immediate goal and everything below depends on it.** It runs against the
three simulator setups we already have — **GEOS** (geoscience), **OpenFOAM** (fluid
dynamics), **LAMMPS** (molecular dynamics) — because those are the only places we can
get a real number this month.

### 1.1 Close the reward channel before anything else

The predecessor loop failed for one diagnosable reason: `reflect.py` proposed and
overwrote the adapter with no scoring step in between. Every `.reflection_meta.json`
in `plugin_evolving/v1..v3` records `round_mean_treesim: 0`; the proposer's prompt
literally read *"mean treesim 0.0000"* with every task line rendered `(treesim N/A)`.
Three rounds of "self-evolution" were three unconditioned rewrites.

**The same failure class is live right now.** `INTEGRATION_REQUIREMENTS` R1 requires
that `GEOS_EVOLVE_FEEDBACK_SHAPE` and `GEOS_EVOLVE_CHECKS` reach the hook that consumes
them. They are now forwarded across the container boundary
(`repo3/src/runner/docker_cmd.py:195-196`) — but `repo3/plugin/hooks/verify_outputs.py`
**does not read either name**. So the stop policy is a searchable component that nothing
downstream observes. A search over it would propose, evaluate, accept and reject
candidates differing only in a setting no consumer reads, and it would look entirely
normal in the logs, because the candidates really are different and the scores really
do differ.

R1 is satisfied when the *hook event log differs* between a `feedback_shape=minimal`
run and an `errors_plus_tables` run on the same task. Not when the config says so.

### 1.2 Implement the adopted methods

Four, chosen because each answers a specific measured pathology rather than because it
is recent. Detail and rationale in the method-adoption plan §2.

| Method | What we take | The pathology it answers |
|---|---|---|
| **Self-Harness** (2606.09498) | minimal proposals + a **regression gate** | unconditioned rewriting; 12× monotone adapter growth |
| **AHE** (2604.25850) | component / experience / **decision** observability | proposer saw almost no evidence; no audit trail |
| **GEPA** (2507.19457) | outer loop as a *library* — Pareto over per-task scores | no archive, no selection, and we are sample-starved |
| **ACE** (2510.04618) | itemized **delta** updates under a hard token cap | context inflation in an always-on 775-token artifact |

Much of this already exists in `sci-sim-op` (`core/`, `evidence/`, `evolvers/`,
`hygiene/`, 523 tests passing). The work is less "write the methods" than "connect them
to a real evaluator and find out where they break."

### 1.3 Build the intuition — which is the actual deliverable

The point is not to report a win. It is to answer, with paired per-task evidence:

- **Which ingredient carries the gain?** Regression gate, evidence richness, Pareto
  archive, delta updates — ablate them individually. AHE's own ablation localizes gains
  to tools/middleware/memory rather than the system prompt, which predicts SIGA's
  prose-only search space was the wrong space. We can test that directly.
- **Which component *binds*, per simulator?** Structural completeness binds on some
  simulators, value-correctness on others. Three simulators is enough to see whether
  the loop *discovers* what binds or has to be told. This is the most likely source of
  a genuinely novel contribution (plan §5.1).
- **Does any of it beat simple test-time scaling?** arXiv:2607.12227 finds automatic
  harness evolution does *not* consistently beat best-of-k even where sampling is cheap.
  **Compute-matched baselines are mandatory, not optional.** A win we cannot match on
  budget is not a win.

**The null result is a first-class outcome.** Published evidence predicts a search in
this regime returns its seed. That is pre-registered as a kill criterion. "A loop with a
broken reward channel produces nothing measurable, and here is what fixing it does or
does not buy" is a stronger and more honest paper than "we self-evolved an adapter."

---

## Goal 2 — Expand the scope of what the agent handles

SIGA covers a narrow slice: author a valid input deck. The scientific process around it
— choosing what to simulate, designing the study, interpreting output, deciding what to
run next — is where the value is.

**Blocked on:** our LLNL geoscience partner. We need their account of which steps
actually consume researcher time before we choose which to automate; guessing produces a
benchmark nobody wants.

**What Goal 1 contributes:** the manifest-based candidate is the piece that carries this.
A wider scope is a larger manifest with more component types, not a new codebase.

---

## Goal 3 — Expand the set of domains

Today: GEOS, OpenFOAM, LAMMPS. The portability claim is only as strong as the number of
independent simulators it survives.

**Blocked on:** domain experts for the new simulators — for ground truth and for judging
whether a generated configuration is scientifically sensible, which no automatic metric
we have can decide.

**What Goal 1 contributes:** `SimulatorSpec` is measured at a flat 150–300 lines across
four implementations; the variable cost is entirely the scoring function. So the cost of
a new domain is mostly *the cost of deciding what a good configuration is* — which is
exactly the part that needs the expert, and exactly why this is sequenced third.

---

## Why now: the free-inference window

Self-evolution pipelines are inference-heavy in a way that usually caps how much
intuition you can afford to buy. Right now two strong models are being served free, so
the ablations in §1.3 — which are the expensive part — are affordable in a way they will
not stay.

**Measured on 2026-08-26, not assumed:**

| Provider | `stealth/ox-alpha` | `tencent/hy3` |
|---|---|---|
| **OpenRouter** | **free** (`cost=0`), 1M ctx | **free window already closed** — *"unavailable for free, use the paid slug"*. Paid: $0.13/$0.53 per M |
| **Nous portal** | **free** (`cost=0`) — the workhorse | `tencent/hy3:free` serves, but **bills** ≈$5e-5/call |
| **Venice** | listed at $0, but **refuses all calls** on a $0 balance (`accessPermitted: false`) | not offered |

Three consequences that change the plan:

1. **hy3 is already half-gone.** The user's read was right to deprioritize it: OpenRouter
   reclassified it before we started. Nous still serves it but not for free. Treat hy3 as
   a cheap paid model, not a free one.
2. **Nous requires a `User-Agent` header.** Without one, *every* request returns 403 —
   indistinguishable from an auth failure. With one, 24/32 concurrent succeed.
3. **"As hard as we can" has a measured ceiling, and it is upstream.** Both Nous and
   OpenRouter report `provider: "Stealth"` for ox-alpha — they proxy the **same upstream
   pool**, so running both does not double capacity. Measured at concurrency 8:
   **536 completions/hr, 0.88 M tokens/hr, $0.00, with 13 of 32 requests 429ing.**
   Beyond that point additional concurrency converts directly into 429s.

   So the goal is **maximum goodput, not maximum request rate**: adaptive concurrency
   that backs off on 429, durable resume so a multi-hour search survives throttling, and
   a recording runner that turns every rollout into a corpus later statistics can be
   recomputed from for free. Our per-account quota (180 rpm / 720k tpm on Nous) is not
   the binding constraint and there is no point tuning against it.

**Watchdog:** `scripts/provider_watch.py` probes every (provider, slug) pair with a real
completion and reads back `usage.cost`, because a catalogue price of `0` is evidence
about the listing, not about what the next call costs — Venice advertises $0 and refuses
to serve; Nous serves `:free` and bills. It exits 2 when a pair stops being free, and
deliberately treats 429 as *unknown* rather than *not free*, so our own saturation does
not cry wolf. Run it on a cron beside any long search.

---

## What we actually do first

In order. Items 1–3 are gates: nothing downstream is believable until they pass.

1. **Fix and verify R1** — make `verify_outputs.py` read `GEOS_EVOLVE_FEEDBACK_SHAPE` and
   `GEOS_EVOLVE_CHECKS`, then prove it by diffing the hook event log across two feedback
   shapes. *Nothing else runs until this diff is non-empty.*
2. **Harden the provider layer** — `User-Agent`, 429 backoff, and cost accounting from
   `usage`, so a search can run for hours and so we notice the moment free ends.
3. **Confirm the quarantine holds** — `plugin_evolving/_quarantine/v4` stays quarantined;
   its cheatsheet is a task→ground-truth lookup table for all 17 val tasks. Hygiene gate
   blocking, before any rollout is spent.
4. **Run the de-risk experiment** (plan item 0) — S+X+M vs SE, paired, n=5 on `X_eval`.
   ~2h, and it settles the framing of everything else. Prediction on record: the paired
   CI spans zero.
5. **Then the search**, with compute-matched baselines budgeted in from the start.

**Decide deliberately, once:** `sci-sim-op` and `repo3/src/evolve/` are two implementations
of the same search. The reconciliation flagged the overlap and it has not been resolved.
Maintaining both is how they silently diverge. `sci-sim-op` is the cleaner line and is the
recommendation; repo3 remains the evaluation and runner infrastructure it calls.
