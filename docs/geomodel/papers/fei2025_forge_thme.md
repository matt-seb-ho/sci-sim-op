# GEOS + earthquake simulation of FORGE well 16A stimulations — Fei 2025
F. Fei, C. Wang, K. Kroll Whiteside, "Prediction and Analysis of Utah FORGE Injection Activities using a Coupled THM+E Modeling Workflow", LLNL-TR-2002096, Feb 2025 (30 pp. technical report, not peer reviewed) · [OSTI](https://www.osti.gov/biblio/2537965) · local: `/data/matt/sci-sim-op/geomodel/papers/osti_2537965_fei2025_forge_thme.pdf`

Page numbers below are the report's printed numbers (PDF page = printed + 3).

**In one sentence:** Using public FORGE field data, they built a simple GEOS reservoir model (a uniform granite block, depth gradients for stress, pressure and temperature, and fracture planes fitted to microseismic clouds). They tuned two permeability parameters per stage to match bottom-hole pressure, then passed GEOS stresses to an earthquake simulator (RSQSim) to test whether the 2024 stages (3R, 4, 5) reopened the fracture created by Stage 3 in 2022.
**Why Sherman sent it:** It is the closest existing example of our target: GEOS applied to FORGE, starting from public data. The "geological model" in it is much thinner than we might expect, which shows what a realistic minimum is.

## What they did
- Fit planes to the microseismic events of each stage with PCA. Stages 3–6 give closely aligned, intersecting planes, which suggests one fracture zone (p. 2, Fig. 2).
- Read supporting evidence off radius-vs-time plots of events (p. 2–4, Fig. 3) and cross-well fiber strain on well 16B. One persistent strain signal at about 9,800 ft MD from Stage 3R to Stage 6 is read as the reopening of an existing fracture, not a new one (p. 4–5, Fig. 4, taken from Jurick et al. 2024).
- Ran fully implicit THM (thermo-hydro-mechanical: heat, fluid flow, rock deformation) simulations in GEOS for Stages 3, 3R, 4 and 5. Stage 6 was dropped because of "unexpected injection results" (p. 6).
- Calibrated a pressure-dependent permeability law separately for each stage by matching the bottom-hole pressure curve (p. 7, 15–21).
- One-way coupling: GEOS stress and pressure histories are projected onto a single fracture plane and drive RSQSim, a rate-and-state earthquake simulator. The output is a synthetic event catalog, compared with the observed one (p. 5–6, 9–10, 21–27).

## The geological / earth model in this paper
- **Inputs (data used to build it):** microseismic catalogs from 2022 and 2024 (geophones in 58-32, 56-32 and 78B-32) (p. 1); fiber-optic DSS strain on 16B (p. 4); injection rate and bottom-hole pressure for each stage (Figs. 10, 13, 15, 17); the fluid split from the July 2023 circulation test (30% of the rate assigned to the Stage 3 location for 3R, p. 17); "lab experiments performed on Utah-FORGE rock" for the friction parameters (p. 10). Where the Table 1 stresses and gradients come from is **not stated**. No well logs, image logs, seismic surveys or lithology model are used or mentioned.
- **What the model contains:**
  - Matrix: one homogeneous, isotropic, poroelastic rock with no layers or units. E = 55 GPa, ν = 0.26, Biot 1.0, k0 = 50e-18 m², φ = 0.01, thermal conductivity 4.0 W/m/K (Table 2, p. 9).
  - Initial state at TVD 2,775 m, varying linearly with depth: p = 27.04 MPa (hydrostatic gradient, 0.00981 MPa/m); T = 194.5 °C (0.06 °C/m); total stresses σh = 46.06, σH = 52.06, σv = 67.94 MPa (Table 1, p. 7). SHmax azimuth is 20° (p. 10).
  - Fractures: a deterministic set of fracture planes turned into cell permeability ("upscaled DFN permeability", initial aperture 0.06 mm, Table 2). The Stage 3 run includes only the Stage 1 and 2 fractures. The 3R–5 runs add planes fitted to the microseismicity of Stages 3–6 (p. 6, Fig. 5). How the Stage 1 and 2 fractures were built is **not stated**; in Fig. 5 they look irregular, not like simple disks.
  - Stimulation: k(p) = k0·exp[αk(p − p0)], applied only in the y and z directions. This assumes fractures open perpendicular to σh, which is taken as the x axis (Eqs. 1–2, p. 7). Eq. 2 is printed as max{k(p), kmax}; min{} is presumably meant.
  - Domain size, mesh resolution, boundary conditions and run times: **not stated**. Fig. 5 shows a rectangular block with wells 16A and 16B inside a larger bounding box, with no dimensions given.
- **How it was built:** by hand, with judgment calls at every step: which fractures to include, fitting planes to event clouds, the anisotropic-permeability simplification, and injecting only at the Stage 3 location for 3R (p. 17). No geomodelling software (Petrel, Leapfrog, etc.) is mentioned.
- **Format handed to GEOS:** "coupled finite element and finite volume" THM solver (p. 6). The fractures enter as upscaled permeability fields, not as explicit fracture surfaces. File formats and mesh type: **not stated**. For RSQSim, one plane (strike 171°, dip 69.78°, rake −156.76°) is cut into 10 m elements. Its initial shear stress is a von Kármán random field: H = 0.2, correlation length 2,270 m, standard deviation 4 MPa, seed 12345, giving 2.75–27.85 MPa with a mean of 14 MPa (p. 9–11, Fig. 6).

## How it was checked against reality
- **Pressure:** modeled vs field bottom-hole pressure for each stage, compared **by eye** only; no misfit number is given. Two parameters (αk, kmax) are fitted per stage (Figs. 10, 13, 15, 17).
- **Stimulated-zone geometry:** compared by eye with the Stage 3 microseismic cloud. Size and location match, but the model misses the observed upward growth (p. 15, Fig. 12).
- **Seismicity:** statistics over the whole catalog, not event-by-event matching. The authors argue event-by-event history matching is "impossible" (p. 22). Compared quantities: cumulative event counts over time (Figs. 19–20; M ≥ −1.5 for Stage 3, M ≥ 0 for later stages; Stage 3 cut at 300 min to exclude a splay fracture); magnitude distributions (Fig. 21); event locations in three views (Fig. 22); distance-vs-time migration (Fig. 23).
- **Result:** good match for Stages 3, 4 and 5. Stage 5 produces too many events that are too large. Stage 3R produces too few events, possibly because the initial shear stress is too high (p. 22–23, 28).
- **Inversion method:** none (manual calibration only).

## What this means for an LLM-agent benchmark
- **Task shape:** input is public GDR data (well paths, microseismic catalogs, stress data, pumping records). The agent outputs a GEOS-ready earth model: a stress/pressure/temperature state with depth gradients, rock properties, and fracture planes as permeability. Table 1 and Table 2 plus the fitted-plane geometry make a concrete **reference answer**, but it is one expert's simplified choice, not ground truth.
- **Sub-task that is easy to score:** fit planes to microseismic clouds (PCA). Score orientation against strike 171° / dip 69.78° for the main plane (p. 9–10).
- **Held-out observations are ready-made:** bottom-hole pressure for each stage, the 2024 microseismic catalogs, and the 16B fiber strain are all published. A natural split is to build the model from 2022 (Stage 3) data and predict the 2024 stages. **Leakage warning:** the paper builds the 3R–5 fractures *from* the 2024 microseismicity it later compares against.
- **Scoring can follow the paper's own metrics:** a pressure-curve misfit (they give none, so we would define one, e.g. an L2 or peak/residual pressure error), event counts over time, magnitude range, and moveout. Event-by-event matching is judged infeasible (p. 22).
- **Hard parts:** undocumented inputs (Stage 1–2 fracture construction, source of the stress gradients, domain and mesh); a stage-by-stage fitted permeability law that absorbs most model error; possible typos (kmax = 1e-7 m² for Stage 3; Eq. 2 max/min).
- **Scope note:** this model is a local, stimulation-scale box with no stratigraphy. The site-scale FORGE geologic model (granite/basin-fill contact, faults) is **not used** here.

## Numbers worth remembering
- Reference depth TVD 2,775 m; T 194.5 °C; p 27.04 MPa; σh / σH / σv = 46.06 / 52.06 / 67.94 MPa (Table 1).
- Calibrated (αk [1/MPa], kmax [m²]): Stage 3 = (0.8, 1e-7 as printed); 3R = (1.2, 1.2e-13); 4 = (3, 1e-12); 5 = (0.6, 1e-12) (p. 15–19).
- Stage timing: Stages 1–3 in April 2022 and Stages 3R–10 in April 2024 (p. 1). One passage on p. 17 says "2021", which conflicts.
- Stage durations: about 160–250 min each. Peak BHP is roughly 60–70 MPa on the figure axes.
- Observed event counts, read roughly off the Fig. 21 axes: Stage 3 about 1,400; 3R about 60; 4 about 120; 5 about 100.
- RSQSim: a = 0.004, b = 0.00533, μ = 0.70, Dc = 9e-6 m, 10 m elements (Table 3).

**Data / paper leads for FORGE:** GDR 1686 (Jurick et al. 2024, 16B crosswell fiber strain report, April 2024 stimulation); GDR 1695 (McClennan et al. 2024, 16A/16B stimulation program report, doi 10.15121/2483880); FORGE microseismic catalogs for 2022 and 2024 (source not cited); July 2023 circulation test (fluid partition, not cited); Lee & Ghassemi 2023, Stanford Geothermal Workshop (FORGE stimulation modeling, same permeability law); FORGE lab friction tests ("other tasks under this project", not cited).
