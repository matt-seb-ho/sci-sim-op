# Adding a simulator

The architecture claims that adding a simulator is "implementing one class". Four
implementations now exist, so that claim can be measured rather than asserted.
It turns out to be **true about the interface and misleading about the cost**,
and the difference matters for planning.

## What it actually cost

Measured with `ast` over the shipped implementations: lines inside the
`SimulatorSpec` subclass, versus supporting machinery in the same module.

| simulator | total | spec class | support | scoring |
|---|---:|---:|---:|---|
| OpenFOAM | 268 | **153** | 115 | file coverage only; `validate` raises |
| LAMMPS | 339 | **196** | 143 | `score` raises — see below |
| mock | 489 | **294** | 195 | synthetic, exact |
| GEOS | 1149 | **244** | **905** | TreeSim |

**The interface cost is flat: 150–300 lines, whatever the simulator.** That part
of the claim holds, and it is the part that matters for not forking the loop —
every one of these plugs into the same search, the same gate, the same hygiene
rules, the same protocol, with no changes anywhere else.

**The variable cost is entirely the scorer.** GEOS's 905 lines of support is
TreeSim and nothing else. OpenFOAM and LAMMPS are cheap *because they decline to
score*, not because their interfaces are simpler.

So the honest statement is:

> Porting the *harness* to a new simulator is about a day. Deciding what
> "correct" means for that simulator is the actual project, and this
> architecture does not make it cheaper — it only stops that question from
> contaminating everything else.

That is a better claim than the naive one, because it localizes the cost. It also
says something about sequencing: a new simulator is worth adding as soon as you
can *validate* on it, even before you can score it, because validation alone
supports the completeness gate and the derived-constraint mechanism.

## The refusals are the interesting part

`LAMMPS.score` raises. That was deliberate and it is the right call.

On LAMMPS the binding constraint is parameter *values*, not structure — agents
already emit complete, structurally valid scripts. Every cheap structural proxy
therefore measures the wrong thing. The implementation includes a test showing
directive coverage scoring **1.0 for a physically wrong script**, which is
exactly why a placeholder would be worse than a refusal: a number that looks like
a score will get optimised, and the search would spend its whole budget climbing
a metric that cannot distinguish right from wrong.

`SimulatorCapabilities` exists so that refusal is *representable*:

```python
def capabilities(self) -> SimulatorCapabilities:
    return SimulatorCapabilities(can_score=False,
                                 scoring_note="value-correctness binds here")
```

`preflight()` reports what the *environment* is missing; `capabilities()` reports
what is *not implemented*. Conflating them produces callers that "degrade
gracefully" past a capability that is never coming back.

## The checklist

1. **`name`, `leaky_extensions`, `leaky_names`, `leaky_prefixes`.** The leak
   surface is the first thing to get right, not the last. OpenFOAM names
   artifacts with no extension (`controlDict`), LAMMPS by prefix (`in.melt`); an
   extension list alone silently omits a simulator's most common filenames while
   reading as coverage.
2. **`parse`** — workspace to `Artifact`. Populate `parse_errors` rather than
   raising; an unparseable output is a *result* under failures-as-zero, and the
   most informative one there is.
3. **`required_sections` and `present_sections`** — enough for the default
   completeness gate, which is schema-free on purpose so it transfers to any
   simulator with a notion of required structure.
4. **`validate`** — shell out to the simulator's own checker. **Return its output
   verbatim in the message.** This is the single highest-value thing in the whole
   contract: a validator that enumerates legal alternatives lets
   `evidence/directives.py` derive constraints at zero rollout cost. Summarising
   it away throws that away.
5. **`score`** — or refuse, and say why in `capabilities()`.
6. **`diagnose`** — optional, but it is what the proposer reasons over.
7. **`contamination_policy`** — override if the simulator has variant-sibling
   conventions. GEOS does: a ground-truth `Foo_base.xml` implies `Foo_benchmark.xml`
   and `Foo_smoke.xml` share nearly all parameters.
8. **Register it** with `SimulatorRegistry`, and add tests that run **offline** —
   skip, do not fail, when the binary is absent.

## What to verify before trusting it

```bash
python3 scripts/evolve.py preflight --simulator <name> \
    --ground-truth-dir /path/to/ground_truth
```

Then, separately, the thing preflight cannot check — that the validator emits
*repair directives* and not merely verdicts:

```bash
<simulator> --validate broken_input 2>&1 | tee /tmp/v.txt
python3 -c "
import sys; sys.path.insert(0,'src')
from harness_evolve.evidence.directives import parse_validator_output, summarize
print(summarize(parse_validator_output(open('/tmp/v.txt').read())))"
```

A reported `actionable_fraction` of 0% means the derived-constraint mechanism
does not apply to this simulator. That is a fine answer — most verifiers only
emit verdicts — but it must be *known*, because the mechanism is one of the
things this project claims and it should not be claimed where it does not hold.

## Sequencing advice for a new simulator

1. `parse` + `leaky_*` + `required_sections` — an afternoon, and it already
   supports the hygiene gate and the completeness check.
2. `validate` — usually another afternoon, and it unlocks the derived-constraint
   mechanism *and* the stop-policy search, which are two of the three components
   the ablation found dominant.
3. `score` — the real work. Budget separately, and expect to argue about it.
4. `diagnose` — last, and only once scoring is settled, since it is a
   decomposition of the score.

Steps 1–2 are enough to run the completeness half of the system honestly. Do not
block them on step 3.
