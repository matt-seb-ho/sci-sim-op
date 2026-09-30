# Simulating fiber-optic (DAS) strain with GEOS — Sherman 2019
C. S. Sherman, R. Mellors, J. Morris, F. Ryerson, "Geomechanical modeling of distributed fiber-optic sensor measurements", Interpretation 7(1) SA21, 2019 (LLNL-JRNL-746313) · [OSTI](https://www.osti.gov/biblio/1513299) · local: `/data/matt/sci-sim-op/geomodel/papers/osti_1513299_sherman2019.pdf`

Page numbers are the accepted manuscript's "Interpretation N" headers (PDF page = N + 2).

**In one sentence:** They use GEOS to generate synthetic fiber-optic strain records (DAS) for a slipping fault and for a growing hydraulic fracture in simple synthetic models. The main finding is that where the low-frequency signal flips sign along a fiber marks the fracture's height, and signal strength relates to its opening (aperture) (p. 10–13).
**Why Sherman sent it:** It shows GEOS can predict a field observable (fiber strain) directly from an earth model. That observable can then check a geological model. Fiber strain data exists at FORGE (well 16B, used in Fei 2025).

## What they did
- Implemented "virtual fibers" in GEOS: displacement along a line of mesh nodes, converted to strain with a finite-difference operator and then smoothed over the fiber's gauge length (p. 6).
- Verified the approach on a slip event on a 10 × 10 m fault, comparing with an analytic solution (Aki & Richards). The result was a visually excellent match (p. 7, 9–10, Fig. 4).
- Ran three hydraulic-fracture models of increasing complexity: HF-I (uniform rock, fracture height capped by hand), HF-II (layered stress profile with stress barriers), HF-III (adds a random fracture network, DFN) (p. 8–9).
- Recorded synthetic DAS on three fibers: one along the injection well, one in a pilot well, one in an offset well. Data were low-pass filtered at 1 Hz (p. 8).
- Stressed that the model has to start in equilibrium with drift below 0.1 nano-strain/s, because the signals are much smaller than 1 microstrain (p. 6).

## The geological / earth model in this paper
- **Inputs (data used to build it):** none from a real site. The models are explicitly "not designed to approximate any particular site" (p. 4, 9).
- **What the model contains:**
  - Fault model: a 100 m cube of uniform elastic rock (G = 12 GPa, K = 20 GPa, ρ = 2650 kg/m³). Fault friction 0.6, cohesion 1 MPa, then rate-and-state weakening with a − b = −0.005. Uniform stress: σx = 1, σy = 2, σz = 3, σxy = 1 MPa. Walls fixed against normal displacement (p. 7).
  - HF-I: same rock, σx/σy/σz = 15/9/17 MPa, fracture artificially confined to −35 < z < 35 m (p. 8).
  - HF-II: depth-varying minimum stress, with a low-stress zone at −25 < z < 25 m and stress barriers at z = 25 and 75 m (p. 8–9, Fig. 2, about 9–16 MPa over ±150 m).
  - HF-III: adds a DFN of two vertical joint sets striking 30° and 90° from y. Lengths follow a power law (50–400 m, exponent 2.0); aspect ratio is uniform from 0.1 to 0.25 (p. 9).
  - Porosity, permeability and temperature fields: **not stated**. Domain size of the HF models: **not stated** (Fig. 3 scale bar suggests roughly 2 km long).
- **How it was built:** by hand, as idealized test cases.
- **Format handed to GEOS:** FE mesh with explicit solid mechanics, FV implicit flow and heat. Fractures are inserted along element faces, grow by a stress-intensity-factor criterion, and follow Barton–Bandis hydraulic behavior (p. 5). Mesh resolution and file format: **not stated**.

## How it was checked against reality
Not checked against field data. The only validation is the analytic fault-slip comparison, done by eye (p. 9–10). The authors say DAS interpretation needs "calibration against site-specific models and field measurements" (p. 11, 14).

## What this means for an LLM-agent benchmark
- **Not a geomodel-building paper,** but it defines a **forward operator:** earth model → GEOS → synthetic fiber strain. That is how a FORGE model could be scored against the 16B fiber data.
- **Robust scoring signal:** the sign flip ("node") of low-frequency DAS marks fracture height, and the authors expect it to be robust to noise (p. 13–14). An agent's model could be judged on whether it reproduces fracture-hit depth and extent, not full waveforms.
- **Sensitivity to layered stress** (HF-I vs HF-II) shows that the agent's stress-vs-depth profile is what controls predicted fracture height. This argues for scoring the stress model.
- **Hard parts:** tiny signals (drift must stay below 0.1 nano-strain/s), unknown fiber coupling, and overlapping signals from several fractures (p. 3–4, 13).
- **Ready-made ground truth:** no field data. The analytic fault-slip case could serve as a unit test for a DAS post-processor.

## Numbers worth remembering
- Injection 0.053 m³/s for 80 min; fibers offset 50 m from the fracture plane; offset-well fiber at x = 380 m (p. 8).
- Fracture tip passes the offset fiber at 18 min (HF-I); HF-II breaks through the z = 25 m barrier after 5 min (p. 10–11).
- Fault slip event magnitude Mw 0.1, slip pulse about 0.005 s (p. 9).
- Typical DAS gauge length 1–10 m (p. 3).

**Data / paper leads for FORGE:** none FORGE-specific. Method references: Settgast et al. 2016 (GEOS hydrofracture formulation); Jin & Roy 2017 (low-frequency DAS interpretation, also cited by Fei 2025); Sherman & Morris 2017 (Newberry EGS microseismicity modeling, a geothermal analog).
