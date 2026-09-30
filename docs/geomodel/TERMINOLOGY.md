# Terminology: what people actually call the models

**Written:** 2026-09-30 · **Reading time:** ~4 min
**Why this exists:** an earlier draft used "site geologic model" and "simulation earth
model". **Those were my coinage, not terms from the literature.** This page records what
the sources actually say, so we ask Sherman the right question in his words.

## 1. What each source actually says

Counted in the five papers' text, and checked against the FORGE GDR titles:

| source | the interpretive geology | the thing the simulator runs |
|---|---|---|
| WHOLESCALE (Feigl) | **"geologic model"**, "geologic structural model" (Folsom's Leapfrog model) | **"numerical model"** (GEOS, COMSOL) |
| Fei 2025, Fei stress report | (not discussed) | **"numerical model"** |
| Tang 2022 | (synthetic geology) | **"reservoir model"** (35×) |
| Utah FORGE (GDR) | **"Earth Model"** (1107/1108, Phase 2B Leapfrog surfaces); "3-D Model" (1205) | **"Native State Model"** / "Native State Numerical Model" (1160, 1315, 1397, 1812) |
| Sherman, in the meeting | "geologic model", "block model that GEOS can read" | (the GEOS model) |

**Standard industry terms** (general petroleum and geothermal practice, *not* from our
five papers):
- **static model** / geocellular model: the geology and rock properties on a grid, with
  no time dimension;
- **dynamic model** / simulation model: the static model after upscaling, plus initial
  conditions, boundary conditions and wells, ready to run through time;
- **upscaling**: the step that turns the first into the second;
- **mechanical earth model (MEM)**: the geomechanics flavour, meaning stress, pore
  pressure and rock strength/stiffness along wells or in 3D. It is the closest standard
  name for what Fei's GEOS models consume.

## 2. How the two actually differ

| | **geologic (static) model** | **numerical (simulation) model** |
|---|---|---|
| question it answers | *what is down there?* | *what happens when we inject?* |
| content | rock units, contacts, faults, sometimes rock-type and property distributions | mesh + physics parameters per cell + **initial state** (P, T, stress) + **boundary conditions** + wells/sources |
| resolution | as fine as the interpretation supports | as coarse as the physics question allows (cost) |
| how many | usually **one** per site version | **many** per geologic model: one per physics question |
| who builds it | geologists, often the operator (Ormat at San Emidio; EGI/UGS at FORGE) | modelers (Sherman, Fei; INL for FORGE native state) |
| tools | Leapfrog, Petrel, GOCAD | meshers + GEOS / FALCON / MOOSE |
| uncertainty handled by | alternative interpretations (rare in practice) | parameter sweeps, ensembles, calibration |
| how it is checked | consistency with data: honours well picks, maps and geophysics | reproducing observed response: pressure, microseismicity, strain |

**The line is blurry in practice. FORGE shows the steps in between:**

```
1107 Earth Model (2018)        1205 "3-D Model" (2019)             1160/1397/1812 Native State
Leapfrog surfaces:        ──►  geology labels on a 50 m sim  ──►   FALCON/MOOSE run to thermal and
granite top, 2 faults,         mesh + P/T/stress from gradients    stress equilibrium; per-cell
isotherms                      (exported from Leapfrog)            perm/porosity from upscaled DFN
   = geologic model               = in between                        = numerical model
```

Our draft task targets **1205**, the in-between artifact. That is defensible, but it is
our choice, not an established category.

## 3. Why this matters for the Sherman question

The WHOLESCALE report says the **San Emidio geologic model was built by the operator
(Ormat), not by Sherman's team.** So his "a solid year to build a geologic model for
numerical modeling" was probably spent on the *conversion and numerical side*: meshing
the Leapfrog model, assigning properties, initializing stress (78 realizations), and
calibrating. That is our inference, but it would move the target.

**Questions to ask, in his vocabulary:**
1. *"When you said 80–90% of the time goes to the geologic model, which part of that is
   building the geology itself, like the Leapfrog surfaces, and which part is turning it
   into a numerical model GEOS can run: meshing, properties, initial stress, calibration?"*
2. *"At San Emidio, Ormat supplied the Leapfrog model. What filled your year?"*
3. *"Is the initial stress, pore pressure and temperature state part of the 'geologic
   model' in your usage, or part of the numerical model?"*
4. *"What file does the geologist hand the modeler, and what does the modeler hand GEOS?
   Is there a standard format or conversion tool, or is it custom each time?"*
5. *"If an agent could hand you one artifact, which would save you the most time: a
   Leapfrog-style geologic model, a GEOS-ready mesh with properties and initial state
   (like FORGE's 1205), or a calibrated model?"*

**Q5 decides the task.** Q1 and Q2 tell us whether the bottleneck is geology,
conversion, or calibration. They are three different agent tasks with three different
scoring schemes.
