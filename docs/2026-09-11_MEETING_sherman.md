# Meeting prep — Dr. Sherman (LLNL, GEOS)

**When:** 2026-09-11 · **Length:** ~60 min · **Owner:** Matt Ho
**Purpose:** (1) define what the collaboration actually is, (2) settle how we use LLNL
resources, (3) **elicit the real computational-geoscience workflow** so we can design and
evaluate an agent that owns more than deck authoring.

Context for this doc: [`PROJECT_PRIMER.md`](PROJECT_PRIMER.md) §6 item 1 (scope
expansion), [`2026-08-26_followup-goals.md`](2026-08-26_followup-goals.md) Goal 2.
Both record this direction as **blocked on exactly this conversation.**

---

## 0. Time budget

| min | block | why it's in this order |
|---:|---|---|
| 0–5 | Where the project is, in 3 sentences | he needs the frame, not the history |
| 5–30 | **§3 Workflow elicitation** | the irreplaceable part — only he can answer it |
| 30–40 | §4 What "correct" means / who grades | determines whether the benchmark is buildable |
| 40–50 | §5 LLNL resources: compute, data, review | long lead times, so start the clock today |
| 50–60 | §6 Shape of the collaboration + next step | leave with one dated commitment |

**If the meeting collapses to 15 minutes, ask:** Q3.1 (where does the time go),
Q4.1 (how do you know a deck is right when there's no reference), Q5.1 (can an
external LLM API be reached from LC), Q6.3 (one dated follow-up).

---

## 1. Opening frame — say this, then stop talking

> We've built an agent that turns a described simulation into a working GEOS input
> deck, and we can measure it honestly. That's a narrow slice of your job. We want to
> push it up the stack — but if we guess at what the rest of your workflow is, we'll
> build a benchmark no geoscientist wants. That's what I want your help with.

Two things to be honest about up front, because they set expectations correctly:

- **We have no training budget.** Everything is optimization *around* a frozen model.
  This is why our compute ask is small and why our timeline is short.
- **The methods are meant to be general** (geoscience is the first and primary
  demonstration domain, not the identity of the work). Worth saying plainly so he
  isn't surprised later when LAMMPS/OpenFOAM appear in a paper.

**One number worth quoting, because it buys credibility fast:** our current GEOS
result is a *null* — champion vs seed +0.116 with a 95% CI of [−0.083, +0.314], and
the single cell carrying 89% of that estimate failed to replicate. We say so. That
tends to land well with people who have been burned by AI demos.

---

## 2. What the collaboration is — propose a shape, don't ask open-ended

Ask him to pick a tier rather than "would you like to collaborate?"

| tier | his commitment | what he gets |
|---|---|---|
| **A — Advisor** | ~1 hr/month, answers questions, reviews the task list once | acknowledgement; early access to the tool |
| **B — Domain co-author** | ~2–4 hr/month, defines the task ladder, adjudicates scientific plausibility on a sample | co-authorship; the benchmark carries his design |
| **C — Embedded** | B + a postdoc/student who grades and supplies tasks | above + a tool tuned to his group's actual decks |

**Questions:**
- **Q2.1** Which tier is realistic for you this year, given your other commitments?
- **Q2.2** Is there anyone in your group — postdoc, student — for whom being the
  domain grader on this is a *useful* thing to have done, rather than a favor?
- **Q2.3** Does any of this map to a deliverable or milestone already on the
  UCI-helmed Geoscience+AI grant? If it does, we should say so in the same words
  the grant uses.
- **Q2.4** What would make this *useful to you*, not just to us? (Honest version: if
  the answer is "nothing, this doesn't help me," we should know that now.)

---

## 3. ★ The core block — what the broader workflow actually is

This is the part of the meeting that cannot be recovered later. Budget 25 minutes and
protect it.

### 3.1 Open the block with a strawman, not a question

Experts correct a wrong map far more readily than they draw a blank one. Put this
ladder in front of him and ask him to **move the rungs around**:

| rung | what the agent is handed | what it must produce | where we are |
|---|---|---|---|
| **L0** | complete physical spec, in English | valid GEOS deck | **today** |
| **L1** | *partial* spec — inferable parameters masked | deck + the inferred values, justified | started |
| **L2** | scientific goal + site/material data | choice of physics, BCs, in-situ stress, mesh resolution, solver settings | — |
| **L3** | L2, plus the agent runs it | a *converged* run: diagnose non-convergence, adjust, re-run | — |
| **L4** | L3, plus a study | mesh-convergence / sensitivity sweep / calibration against data | — |
| **L5** | L4, plus interpretation | "here's what the result means and what to run next" | — |

**Q3.1 — the single most important question of the meeting:**
> Walk me through your last real GEOS study, start to finish. Where did the *hours*
> actually go? Not where the intellectual difficulty was — where the clock went.

Listen for the gap between the two. Our thesis is that agents should absorb the
clock-consuming low-level work so researcher time moves to the high-level thinking;
this question tests that thesis against one real project.

**Q3.2** Rank those rungs by *annoyance* and separately by *value if automated*.
They will not be the same ranking, and the disagreement is informative.

**Q3.3** What's missing from the ladder entirely? What did I not think to put on it?

### 3.2 Specific pieces we suspect are the real work (ask, don't assert)

These are guesses. Say they're guesses and let him correct them — a correction here
is worth more than a confirmation.

- **Q3.4 — Mesh & geometry.** How much of a study is mesh generation and conditioning
  (geometry, VTK/gmsh, refinement, fracture/fault representation)? Is that upstream of
  GEOS in a separate toolchain, or entangled with the deck? Is it human-in-the-loop by
  necessity or by habit?
- **Q3.5 — Material properties and in-situ state.** Where do constitutive parameters
  and initial stress actually come from — lab data, literature, calibration, judgment?
  How much of that is lookup vs. reasoning? (This is the heart of L1/L2: it tells us
  whether "inferable parameters" is a real task or an artificial one.)
- **Q3.6 — Numerics.** Timestep, nonlinear tolerances, linear solver/preconditioner
  choice. Is picking these craft knowledge, folklore, or written down anywhere? **If
  it's folklore, it is exactly what the agent should be studying** — and it's the kind
  of thing that never appears in documentation.
- **Q3.7 — The debug loop.** *What are the top five ways a GEOS run goes wrong, and how
  do you diagnose each?* Ask him to be concrete about the symptom→cause→fix chain.
  This is the highest-value single answer for our T1 "open-book exam" thread: procedural
  know-how, not facts, and no documentation contains it.
- **Q3.8 — Post-processing & V&V.** What does establishing that a result is *trustworthy*
  involve — mesh convergence, analytical benchmarks, comparison to a prior study?
  Is that a checklist (automatable, gradeable) or a judgment call?
- **Q3.9 — Sweeps and UQ.** How often is one run the deliverable vs. a parameter study?
  Who manages the sweep, and is that bookkeeping painful?
- **Q3.10 — The Python surface.** How much is driven through GEOS's Python interface vs.
  hand-edited XML? If real work happens in Python, our task format is looking at the
  wrong artifact.

### 3.3 The question nobody in this literature has asked

- **Q3.11** Would you be willing to have a study **recorded** — screen, terminal
  history, and browser history — while you do it? Even one session.

Why it matters, and worth explaining to him: the derived quantity is *what the expert
looked up that the agent never did*. That gives us a principled, contamination-auditable
generator for whatever "studying" should produce, instead of us guessing. Nobody has
paired expert and agent traces on the same task. It's also the kind of artifact that
could be its own contribution.

Expect friction (proprietary data, machine policy, self-consciousness). Offer:
a synthetic/public problem, redaction rights, and he reviews before we use anything.

---

## 4. What "correct" means — the block that decides if this is buildable

Our current GEOS score is **structural similarity to a reference deck (TreeSim)**. That
works at L0 because a reference deck exists. **At L2 and above it stops working — there
is no single right answer.** If we can't replace the reward signal, we can't climb the
ladder, no matter how good the agent is.

- **Q4.1** When there's no reference deck, how do *you* know a configuration is right?
  What's the first thing you look at? Second?
- **Q4.2** Is there a cheap proxy that is *usually* right — converges, mass/energy
  conserved, fields in a plausible range, matches a known analytical solution in a limit?
  We'd rather have an imperfect executable check than a perfect unavailable one.
- **Q4.3** Could you look at a generated deck + its output and give a 1–5
  "scientifically sensible" rating? **How long would one take you, honestly?** (We need
  this number to know if expert-graded evaluation is affordable at all — if it's 20
  minutes a deck, the benchmark has to be ~30 items, not 300.)
- **Q4.4** Would you and a colleague agree on that rating? If two experts disagree, we
  need to measure that and report it — inter-rater agreement is part of the result.
- **Q4.5 — contamination.** Public GEOS examples and `integratedTests` are on GitHub and
  almost certainly in the models' training data. **Do you have unpublished or internal
  decks — real project work — that could seed a held-out set?** Even 10–15 would change
  what we can claim. What would it take to clear them for use?
- **Q4.6** Do you have archived project directories with *the whole history* — the
  broken intermediate decks, not just the final one? The failures are more valuable to
  us than the successes, and nobody archives them deliberately.

---

## 5. LLNL resources

### 5.1 Compute — and why it's a research unlock, not a budget line

**Say this explicitly, it's the strongest ask in the meeting:** we currently *forbid*
the agent from executing GEOS. Not for safety — because solves dominated our cost
(instruction-only $0.134/rollout vs. $0.213 with solves, and they were the single
largest cost driver in the August campaign). That restriction is what pins us at
structural scoring. **If simulation execution is effectively free on LC, we can score on
outcomes instead of deck similarity — which is precisely what rungs L3–L5 require.**

Our own LLM-inference ask is tiny (~$400 total, no training). The compute we want is
*CPU hours to run GEOS*, which is the thing LLNL has and we don't.

- **Q5.1 — the blocker to check first.** Can a process on an LC compute node reach an
  **external LLM API**? Assume not. If not, what are the options — an internally hosted
  model service, open-weights on LC GPUs, or a split architecture (agent outside, solver
  inside, over a file/queue boundary)? *Everything else in this section depends on the
  answer.*
- **Q5.2** What does getting an account for an external collaborator involve, and what's
  the realistic lead time — weeks or months? Any citizenship/foreign-national
  restrictions we should surface now rather than discover later?
- **Q5.3** Which machine and which bank? What does a typical GEOS run for our task sizes
  cost in node-hours, and what allocation would ~500–2000 short runs need?
- **Q5.4** Is there a containerized/portable GEOS build we could run on our own hardware
  instead? (Cheaper for everyone if our tasks are small.)
- **Q5.5** Batch policy: is many-small-jobs acceptable, or would an agent submitting
  hundreds of short jobs be antisocial on that system?

### 5.2 Data, export control, and publication — raise early, not at submission

- **Q5.6** Of the decks/data we've discussed, what's public, what's OUO/proprietary,
  what's export-controlled? What's the process to use any of it externally?
- **Q5.7** If LLNL data or LLNL-authored decks appear in a paper, does it need release
  review? What's the turnaround, and who initiates it? **Ask now** — discovering a
  multi-week review two days before a deadline is a preventable disaster.
- **Q5.8** Does LLNL co-authorship carry its own review/approval path?
- **Q5.9** Any restriction on the *agent transcripts* — if a rollout reads an internal
  deck and we publish the trace, is that a problem?

---

## 6. Close — leave with something dated

- **Q6.1** What's the next concrete artifact? Candidates, in order of value to us:
  1. a recorded or narrated walkthrough of one real study (§3.11)
  2. 10–15 internal/unpublished decks for a held-out set (§4.5)
  3. his edit of the L0–L5 ladder (§3.1)
  4. a written symptom→cause→fix list for common GEOS failures (§3.7)
- **Q6.2** Meeting cadence — monthly? And is email or something else the right channel
  for short questions between meetings?
- **Q6.3** **Put one date on the calendar before leaving the call.** If nothing else
  lands, this does.

---

## Things to be careful about in the room

- **Don't pitch automation-replaces-scientist.** Frame: agents absorb the low-level work,
  in parallel and without sleep, so his time goes to the thinking. He owns the science.
- **Let him talk.** §3 is elicitation. If we're talking more than a third of that block,
  it's going wrong.
- **Don't oversell the current system.** Our headline result is a null. Saying so is the
  cheapest credibility available, and he will find out anyway.
- **Write down his exact words**, especially for the failure taxonomy (Q3.7) and the
  "how do I know it's right" answer (Q4.1). Paraphrase loses the procedural detail, and
  the procedural detail is the research object.
- **Resist designing the benchmark live.** Collect, then design. If he proposes a task
  format, capture it; don't negotiate it in the meeting.

---

## After the meeting — write these four things while it's fresh

1. The **corrected ladder** (his version of L0–L5), into `PROJECT_PRIMER.md` §6 item 1.
2. The **failure taxonomy** — the symptom→cause→fix list, verbatim. This seeds T1.
3. **What reward signal is achievable** at the rung we pick, into `RESEARCH_PROGRAM.md`.
4. **The LC decision tree** — what compute we can have, by when, and whether the agent
   can run there at all. This gates whether execution-based scoring is on the table.
