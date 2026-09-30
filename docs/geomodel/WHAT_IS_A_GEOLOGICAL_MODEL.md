# What a geological model is, how it's built, how it's judged

**Written:** 2026-09-23. It draws on the 5 papers Sherman sent (summaries in [`papers/`](papers/)) and the 2026-09-11 meeting.
**Reading time:** ~8 min.

---

## 1. The short answer

A **geological model** is a 3D description of the subsurface at one site, detailed enough
to simulate. It answers four questions about each point underground:

| # | question | component | typical content |
|---|---|---|---|
| 1 | **What rock is here?** | *structural framework* | surfaces between rock units, fault surfaces, the model's extent |
| 2 | **How does that rock behave?** | *property model* | stiffness (E, ν), permeability, porosity, density, thermal conductivity, per unit or per cell |
| 3 | **Where are the cracks?** | *fracture model* (a DFN, "discrete fracture network") | natural fracture sets (orientation, size, density), or specific planes such as mapped faults and fractures seen in microseismicity |
| 4 | **What state is it in before we touch it?** | *initial ("native") state* | stress (3 magnitudes plus a direction), pore pressure, temperature, usually as gradients with depth |

Meshing it and adding wells, boundary conditions and a schedule turns it into a **GEOS
deck**. That last step is what SIGA automated. Everything above it is the 80–90%.

```
 raw site data ──► geological model ──► mesh + BCs + wells ──► GEOS deck ──► simulated response
 (logs, seismic,    (1–4 above)          (SIGA's territory)                      │
  maps, tests)          ▲                                                        ▼
                        └────────── calibrate: does it reproduce observations? ◄─┘
```

## 2. There are really two models, and they differ a lot

> **Terminology fix (2026-09-30).** An earlier draft called these the "site geologic
> model" and the "simulation earth model". **Those were my labels, not terms from the
> sources.** The sources say **geologic model** vs **numerical model**. FORGE says
> **Earth Model** vs **Native State Model**. Industry says **static** vs **dynamic**. Full
> mapping and the differences are in [`TERMINOLOGY.md`](TERMINOLOGY.md).

The biggest surprise from the papers:

| | **geologic model** (a.k.a. static model) | **numerical model** (a.k.a. simulation / dynamic model) |
|---|---|---|
| built by | geologists, often the operator (e.g. Ormat at San Emidio) | modelers (e.g. Sherman and Fei) |
| tool | Leapfrog Geothermal, Petrel, etc. | meshing scripts, GEOS / FALCON / MOOSE |
| content | detailed: many units and faults, following interpretations of the whole site | **deliberately thin**: only what the physics question needs, plus initial and boundary conditions |
| example, FORGE (Fei 2025) | granite/basin-fill contact, regional faults | **one uniform granite block** + depth gradients (σh/σH/σv = 46/52/68 MPa, 194.5 °C at 2,775 m) + fracture planes fit to microseismicity |
| example, San Emidio (WHOLESCALE) | 5 units, 8 named faults (Leapfrog) | 6 element sets, with **1–2 faults** given their own properties |

**Consequence for us:** "produce the geological model" needs pinning down. The more
useful and more scorable target is probably what feeds GEOS, with the geologic model as
an intermediate the agent may build or reuse. This is question #1 for Sherman.

## 3. How people build it

**Inputs, and what each constrains:**

| data | constrains | FORGE has it? |
|---|---|---|
| geologic maps, earlier interpretations | framework (1) | yes |
| seismic reflection, gravity, magnetics, MT (magnetotellurics) | framework (1) away from wells | yes |
| well logs (sonic, density, gamma) and cuttings | rock type with depth (1), properties (2), stress profile (4) | yes, several wells |
| image logs (FMI) | natural fractures (3), stress direction from borehole breakouts and drilling-induced cracks (4) | yes |
| core and lab tests | properties (2), friction, strength | yes |
| stress tests (DFIT/minifrac: small injections, then watch pressure decline) | minimum-stress magnitude (4) | yes (58-32, 16B) |
| temperature logs | temperature (4) | yes |
| microseismicity | where fractures actually are (3) | yes, but it is also an **evaluation** signal |

**The process, roughly in order:**
1. **Collect** everything on the site. Sherman: "as much data as possible", plus
   "has someone else done a model for this area?"
2. **Framework:** interpret the unit contacts and faults, then build surfaces (Leapfrog or Petrel).
3. **State:** build a stress profile along each well. Sv comes from integrating density;
   Shmin comes from DFITs; SHmax is bounded by friction; the direction comes from image logs.
   Add pressure and temperature gradients.
4. **Properties:** assign per unit, or fill the grid geostatistically from logs (random
   fields conditioned on logs; Fei's 3D stress fields are an example).
5. **Fractures:** a statistical DFN from image logs, and/or deterministic planes (e.g.
   PCA fits to microseismic clouds in Fei 2025).
6. **Simplify and mesh** for GEOS.
7. **Calibrate** (§4) and repeat from step 3.

**Where the expert judgment lives:**
- what to *leave out* (Fei drops the natural fractures entirely);
- correlation lengths and other geostatistical choices;
- carrying data from one well to another (Fei applies the 16B log to 16A);
- choosing among stress realizations (WHOLESCALE: 78 candidates, chosen by fault slip tendency);
- reconciling conflicting data (WHOLESCALE's unit names don't match between Leapfrog and GEOS).

**Why it takes so long:** the data is heterogeneous and scattered across reports, and
every gap needs a defensible assumption. Several steps have *no* documented recipe: the
Leapfrog → GEOS conversion at San Emidio is not described anywhere.

## 4. How it's judged

**Your intuition is right: the model must reproduce what was observed at the site.**
Every paper uses some version of this. The observations in use:

| observation | metric in the papers | notes |
|---|---|---|
| **pressure** at the injection well or monitoring wells | by eye (Fei); misfit in kPa with preset targets (WHOLESCALE: 37–41 kPa achieved vs a 20 kPa target) | cheapest and most common |
| **microseismicity** | event counts over time, magnitudes, spatial extent, migration (Fei); "did the stress change push faults toward slip where and when events occurred" (WHOLESCALE: 60–85% of events) | event-by-event matching is called "impossible" (Fei) |
| **fiber strain (DAS/DSS)** | where the strain signal flips sign marks fracture height (Sherman 2019) | FORGE well 16B has it |
| **surface deformation (InSAR/GPS)** | uplift or subsidence map misfit (Tang; WHOLESCALE) | the WHOLESCALE model was **4× off** on subsidence |

**Three caveats that shape our evaluation design:**
1. **Many models fit the same data (non-uniqueness).** Two different stress values fit
   one minifrac curve equally well (Fei, 21.91 vs 20.61 MPa). Tang 2022 says outright that
   matching the true geology is *not* the goal; forecasting skill is. So "matches
   observations" does not mean "correct model".
2. **The experts' own models only partly fit.** Calibration is manual and parameters are
   refit per stage, which absorbs the error. A score of "as good as the expert model" is
   a reasonable bar; "perfect" is not.
3. **Calibration and evaluation data must be separated.** WHOLESCALE gets this right,
   with a 2016 shutdown to calibrate, a 2022 shutdown to audit, and preset targets. Fei
   2025 does not: it builds fractures *from* the 2024 microseismicity and then compares
   against it. We must split **by time**.

## 5. What this implies for the benchmark

Score an agent's model on three independent axes, since no single one is enough:

| axis | question | cost | who |
|---|---|---|---|
| **A. artifact** | does it agree with the published expert model (surfaces, stress gradients, properties, fracture orientations) within tolerances? | cheap, no simulation | automatic |
| **B. prediction** | run it through GEOS: does it predict *held-out, later* observations (pressure, microseismic extent) as well as the expert model does? | GEOS runs | automatic |
| **C. judgment** | would an expert accept it? | ~1 h per site | Sherman |

**B is the honest measure and A is the dense signal.** Self-evolution needs a dense
signal, which is why A exists. C keeps both of them honest.

Two more things follow:
- **Time is the natural split.** At FORGE the agent gets data from before the 2024
  stimulations and predicts the 2024 response. That is also realistic: it is exactly the
  forecast a team would have had to make.
- **Sherman's easier tasks are sub-tasks of this one:** (i) "new data arrived, update
  the model" (continual learning); (ii) sensitivity analysis. Both reuse the same site
  and scoring.
