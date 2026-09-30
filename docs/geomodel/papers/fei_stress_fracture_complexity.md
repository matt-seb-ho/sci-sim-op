# In-situ stress vs. fracture complexity at Utah FORGE: final report (Fei et al. 2026)
Lu, Kroll, Bunger, Cusini, Fei, Wang, "Final Report for Closing the Loop Between In Situ Stress Complexity and EGS Fracture Complexity", LLNL-TR-2017584, April 2026 (DOE award DE-EE0007080; LLNL + U. Pittsburgh) · [OSTI](https://www.osti.gov/biblio/3028321) · local: `/data/matt/sci-sim-op/geomodel/papers/osti_3028321_fei_stress_fracture.pdf`
*Page numbers below are the report's printed page numbers. The PDF page is the printed number + 3.*

**In one sentence:** GEOS simulations and lab block tests show that the usual ways of reading in-situ stress from injection-test pressure curves (G-function analysis) are biased in hot granite, and that a stress field that is "rough" (varies over short distances) with depth explains the shape of FORGE's Stage 3 hydraulic fracture.
**Why Sherman sent it:** This is a worked GEOS example at FORGE in which the "earth model" is mostly a **stress model**. Stress magnitudes come from DFITs (small diagnostic injection tests), a stress profile comes from a sonic log (acoustic-velocity log), and a geostatistical 3D stress field is built from that log. Each is checked against field pressure curves, image logs and microseismicity.

## What they did
- **Task 1, DFIT modeling (pp. 10–22):** They history-matched the pressure record of minifrac test MF2 (Cycle 1, 5495 ft MD) in well 16(B)78-32 with a GEOS thermo-hydro-mechanical (THM) model: LEFM propagation criterion (linear elastic fracture mechanics) plus a Barton–Bandis fracture aperture law. They then added cooling and poroelastic effects to see how each one biases the stress estimate.
- **Task 2, near-well phase-field modeling (pp. 23–35):** A new phase-field fracture-nucleation model. A parametric sweep over stress regime, σmin and well deviation, run in a lab-block geometry. They then simulated MF2 with random rock heterogeneity and compared the result with the post-test image log.
- **Task 3, field-scale fracture (pp. 36–44):** They simulated the well 16A(78)-32 Stage 3 stimulation (a single perforation cluster, crosslinked gel) three ways: (I) a smooth stress gradient plus a calibrated toughness anisotropy, (II) a layered σhmin profile from the 16B sonic log, (III) 3D geostatistical stress fields. Fracture growth was scored against the microseismic (MEQ) cloud.
- **Task 4, lab (pp. 45–60):** 27 true-triaxial tests on 6-inch cubes of St. Cloud Gray granodiorite (a FORGE analogue), at room temperature and 200 °C, some pre-cooled. Results: breakdown pressure drops about 15% with thermal stress, and an "asperity resistance model" explains why G-function closure picks overestimate σhmin.

## The geological / earth model in this report
- **Inputs (data used to build it):**
  - FORGE DFIT/minifrac pressure records: well 58-32 (2017, 2019) and well 16(B)78-32 (7 tests in 2023; Kelley et al. 2024, GDR 1596) (pp. 5, 10).
  - Pre- and post-test borehole image logs at MF2 (p. 33).
  - A **sonic-log-derived σhmin profile along 16(B)78-32** (p. 39).
  - Stage 3 injection-rate schedule and microseismic catalog (pp. 36–37).
  - "Stress gradient provided in FORGE literature" (p. 30).
  - Lab data on analogue granites: tensile strength, acoustic anisotropy, SEM images (pp. 49–50).
  - Not used: seismic surveys, a geologic/structural model, a DFN (discrete fracture network).
- **What the model contains:**
  - *Geometry:* a single-rock (granite) domain. The Stage 3 model covers roughly TVD 2325–2535 m, with Stage 3 at TVD 2506 m (Fig. 5-3, p. 39). Lateral size: not stated. No lithologic layers or faults.
  - *Stress:* a σhmin field, either a smooth gradient (about 37→49 MPa across the block), a 1D layered profile upscaled to 2 m cells, or 3D Gaussian random fields (roughly 37.5–48 MPa). The random fields use either equal correlation lengths in all directions or horizontal correlation lengths 10× the vertical one (Figs. 5-2 to 5-4, pp. 37–40). Only σhmin is stated for the field model; σHmax and σv are not given.
  - *Pore pressure:* hydrostatic, about 21.5–26.5 MPa (Fig. 5-2).
  - *Properties:* homogeneous. E = 27.58 GPa, ν = 0.3, k = 5×10⁻¹⁷ m², φ = 0.01. Horizontal toughness K_Ic = 5 MPa·m½, vertical = K_Ic,h + ΔK_Ic (Table 5-1, p. 38). The DFIT model uses different values: bulk modulus 51.7 GPa, shear modulus 20 GPa, k = 10⁻¹⁶ m² (Table 3-1, p. 14).
  - *Natural fractures:* **explicitly left out** (p. 44). They are only inferred indirectly, through leakoff that depends on pressure (p. 14).
  - *Temperature:* not in the field model. The DFIT thermal case uses the parameters in Table 3-2, but its initial temperature is not stated.
- **How it was built:**
  - The sonic log σhmin was upscaled by averaging over 2 m cells, which preserves the force on each cell (p. 39).
  - The 3D fields come from sequential Gaussian simulation ("3D SGS", Fig. 5-4) conditioned on log statistics. The correlation lengths are **expert choices**, adjusted to fit the MEQ data (p. 43).
  - In MF2, σhmin (21.91 MPa, from Battelle/Kelley) was treated as uncertain and re-fit to 20.61 MPa (p. 15).
  - The near-well effective stresses (5/15/17.5 MPa) were chosen from literature gradients (p. 30).
  - Log-inferred heterogeneity was applied with correlation lengths of 80, 200 and 500 mm (Fig. 4-7).
  - The 16B stress log was used for a stimulation in 16A, which is an assumption they flag as working "remarkably" well (p. 41).
- **Format handed to GEOS:** Not stated beyond "a mesh with vertical resolution of 2 m" and σhmin assigned per cell. The wellbore is not meshed, and injection is a point source with a specified mass flux (p. 38). The DFIT model runs in two stages: injection, then the geometry is exported to a separate shut-in model (p. 13).

## How it was checked against reality
- **DFIT:** fit to the MF2 Cycle 1 pressure-vs-time curve and G-function plots (Figs. 3-1, 3-3). The fit was judged by eye, with no error metric. Calibrated values: h_max, K_Ic, σhmin, and α_perm = 0.2 /MPa.
- **Near-well:** a qualitative comparison of simulated fracture shape, asymmetry and azimuth with the post-test image log. The fracture azimuth was about 20–30° east of north, which suggests σHmax trends NNE and the stress regime is "most likely normal" (p. 34).
- **Field scale:** fracture half-length over time, split into horizontal and vertical growth, compared with the MEQ distance–time envelopes (Figs. 5-1, 5-5, 5-8), plus the fracture shape compared with the MEQ cloud (Fig. 5-7). Calibration was manual, one parameter (ΔK_Ic), with no formal inversion or data assimilation. The layered sonic profile matched the fracture shape without calibration but grew faster than the MEQ envelope. The authors note that MEQ may lag the actual fracture growth (p. 41).
- **Lab:** the phase-field model was calibrated to one lab breakdown pressure and validated against a 30°-deviated block test (p. 27).

## What this means for an LLM-agent benchmark
- **Agent task candidate, "logs → stress model":** given the 16(B)78-32 sonic/stress log, produce an upscaled 1D σhmin profile and a geostatistical 3D stress field ready for a GEOS mesh. This is well defined and has clear inputs and outputs.
- **Held-out observation:** the Stage 3 microseismic catalog, as horizontal and vertical fracture growth over time and the cloud shape. It is a natural score for any stress model fed to a GEOS hydraulic-fracturing run. Weak point: MEQ-inferred growth is itself uncertain.
- **Held-out observation:** the MF2 pressure/G-function curve. An agent-built model plus GEOS DFIT run can be scored by how well its simulated pressure curve matches the field record. Warning: the report shows that several parameter sets fit it (for example σhmin 21.91 vs 20.61 MPa), so parameter recovery is not identifiable.
- **Not ground truth:** the published σhmin values from DFITs. This report argues they are biased (thermal, poroelastic and asperity effects), so they should not be scored as the answer.
- **Hard parts:** choosing correlation lengths or anisotropy (expert judgment, tuned here to the answer), deciding what to leave out (natural fractures, temperature), and transferring a log from one well to another (16B → 16A).
- **Scope warning:** this report's "geological model" is very thin: one lithology, homogeneous elastic properties, no DFN, no faults. It is a good *minimal* benchmark tier, not the full geomodel Sherman described.

## Numbers worth remembering
- MF2 σhmin: 21.91 MPa (3178 psi) reported; 20.61 MPa (2989 psi) re-fit; K_Ic 1–2 MPa·m½ (pp. 14–15).
- Stage 3: TVD about 2506 m; σhmin about 37–49 MPa; pore pressure about 21.5–26.5 MPa; peak injection about 35 bpm over about 140 min (Fig. 5-2).
- Calibrated toughness anisotropy ΔK_Ic: 0.55 MPa·m½ from the simulation vs 0.27 from the analytical (Dontsov) estimate (p. 43).
- Stress roughness about 2 MPa corresponds to a fabric length scale of about 10–70 mm (p. 43).
- The heterogeneous stress field that fits best has L_corr,x = L_corr,y = 10·L_corr,z (p. 43).
- σHmax azimuth about N20–30°E; stress regime likely normal at MF2 depth (p. 34).
- Lab: thermal pre-cooling cuts breakdown pressure by about 15%; G-function closure picks exceed σhmin by roughly 0–8 MPa (Tables 6-1, 6-2).

## Leads for data collection
- **GDR datasets uploaded by this project:** submissions [1537](https://gdr.openei.org/submissions/1537), [1581](https://gdr.openei.org/submissions/1581), [1633](https://gdr.openei.org/submissions/1633), [1709](https://gdr.openei.org/submissions/1709), [1710](https://gdr.openei.org/submissions/1710), [1711](https://gdr.openei.org/submissions/1711), [1778](https://gdr.openei.org/submissions/1778). The report does not describe their contents; they probably contain the lab data and the models/reports.
- **Kelley et al. 2024**, "Utah FORGE 2439: Report on Minifrac Tests for Stress Characterization", [GDR 1596](https://gdr.openei.org/submissions/1596). This holds the 16(B)78-32 minifrac pressure data and the σhmin/σHmax estimates, and is **essential**.
- **Xing, McLennan & Moore 2020**, "In-Situ Stress Measurements at Utah FORGE", *Energies* 13(21), doi:10.3390/en13215842. It covers the 58-32 injection tests and site geology.
- **McClure 2023**, Stanford Geothermal Workshop, "Calibration Parameters Required to Match the Utah FORGE 16A(78)-32 Stage 3 Stimulation…". A Stage 3 benchmark, with its MEQ-based comparison.
- **Cusini, Bunger & Fei 2025**, "Characterizing Stress Roughness at Utah FORGE Through Simulation of … 16A Stage 3". This is the earlier technical report with the details of the stress profile and homogenization.
- **Fei, Cusini & Bunger 2025**, "Connecting In Situ Stress and Wellbore Deviation to Near-Well Fracture Complexity…". The full phase-field parametric results.
- **Fei et al. 2024**, Stanford Geothermal Workshop, "Modeling of DFITs for In situ Stress Characterization in the Utah FORGE Reservoir".
- **Still needed and not identified in this report:** the Stage 3 microseismic catalog, the 16(B)78-32 sonic/image logs, and the injection-rate data. They are presumably on the FORGE GDR, but the report gives no IDs for them.
- **Methods:** Dontsov & Suarez-Rivera 2021 (*J. Pet. Sci. Eng.* 198) for upscaling logs onto a coarse grid; Fu et al. 2019 (SPE HFTC) on apparent toughness anisotropy from stress roughness.
