# Experiment 03 — does the proposer prompt actually work?

**Date:** 2026-08-19 · **Cost:** one `claude-opus-5` call, ≈$0.05 ·
**Script:** `scripts/smoke_llm_proposer.py`

Every other test of the proposer injects a canned response. That verifies the
parsing and the guards and says nothing about the part most likely to be wrong:
whether a real model, given this prompt, produces a compliant edit at all. That
question cannot be answered for free, so it was answered once.

## Setup

A realistic round: a four-line cheatsheet, two tasks scoring 0.61 and 0.44 with
`Constitutive` as the weakest section, `extra_element_types` of
`ElasticIsotropic` and `BiotPorosity`, categories `extra_block` and
`hallucinated_extras`, one expert demonstration, and one constraint **derived**
from repeated validator output (`gravityVector` is not a valid attribute here).

## Result — first call, no retries

```
component      memory
targets        hallucinated_extras
beneficiaries  ['proppant_transport', 'wellbore_thermo']
predicted Δ    +0.040
```

The edit, a single `replace`:

> ~~Poroelastic problems need a coupled solver plus a matching constitutive block.~~
> **Do not add solid-mechanics or porosity-evolution constitutive models unless a
> mechanics solver is actually in the deck; flow-only or transport-only physics
> gets no stress/Biot models.**

Its stated rationale:

> Both tasks lost most points in Constitutive with surplus elastic/Biot element
> types; the removed memory line invited a mechanics constitutive block
> unconditionally, so replacing it with a negative bound should suppress those
> extras without touching the flow/transport models.

## Why this is the right answer and not merely a passing one

Six properties, each corresponding to something the design asks for:

1. **One bounded edit.** A single `<edit op="replace">`, on one component.
2. **Diagnosed, not guessed.** It located the failure in the evidence — the
   weakest section and the specific surplus element types — and its rationale
   names both.
3. **It replaced a positive assertion with a negative constraint.** This is
   exactly recommendation (iii) from the prior work: cheatsheets enumerating
   "for physics X use solver Y" must be paired with explicit negative
   constraints, because without them adapters trade `missing_block` for
   `extra_block` and `hallucinated_extras`. The model was not told which line to
   change; it identified that the *positive* line was the one causing the
   surplus.
4. **No inflation.** Four lines before, four after. A whole-file rewrite would
   almost certainly have added rather than replaced.
5. **It did not restate the derived constraint.** The `gravityVector` bound was
   presented as settled, and the model spent its edit elsewhere — which is the
   entire economic argument for deriving constraints from validator output.
6. **A falsifiable prediction**, naming both tasks and a magnitude, verifiable
   next round.

## What this does and does not establish

**Does:** the contract is followable. A capable model reading this prompt
produces a compliant, well-targeted edit without coaxing, and the parser, budget
gate, and prediction contract all accept real output.

**Does not:** anything about frequency, or about a weaker model. n=1 by design —
the question was whether the contract is followable at all, and asking how often
is only worth paying for once that is settled. The proposer model is also a
choice we have argued should *not* be the inference model, so this call says
nothing about the configuration a real run would use.

Worth noting against expectations: harness-*updating* capability is reported
roughly flat across model tiers on general benchmarks. If that holds on a
domain-knowledge-bound task, a much cheaper proposer should produce a comparably
good edit here — which is a cheap and interesting thing to test, and the
`--model` flag exists for it.

## Reproduce

```bash
python3 scripts/smoke_llm_proposer.py               # claude-opus-5, effort=high
python3 scripts/smoke_llm_proposer.py --model claude-haiku-4-5 --effort low
```
