# WHOLESCALE (San Emidio) — Feigl et al. 2025
K. L. Feigl, S. L. Bradshaw and the WHOLESCALE team (UW-Madison, LLNL incl. C. Sherman, Ormat, UNR, NREL), "WHOLESCALE – Water & Hole Observations Leverage Effective Stress Calculations And Lessen Expenses: Final Technical Report, San Emidio 2020–2024", DOE award DE-EE0009032, submitted June 18, 2025 · [OSTI](https://www.osti.gov/biblio/2588223) · local: `/data/matt/sci-sim-op/geomodel/papers/osti_2588223_feigl_wholescale.pdf`

Page numbers are the report's printed pages. The PDF page is the printed page + 1.

**In one sentence:** At the San Emidio geothermal field in Nevada, the team used planned plant shutdowns (2016, 2021, 2022) as natural experiments. They built GEOS stress models on top of an industry-supplied 3D geologic model and scored them against four observation types: microseismicity, borehole stress indicators, well pressure and ground deformation (p. 3, 7–8).
**Why Sherman sent it:** It is the San Emidio "capstone" case, and Sherman (LLNL) ran the GEOS modeling tasks (p. 11–12). Section V (p. 107–124) is the "calibrate GEOS against microseismic activity" part he mentioned.

## What they did
- **Hypothesis:** pumping lowers pore pressure, which clamps the faults. When pumping stops, pressure recovers within hours and triggers tiny earthquakes (M −3 to 1) on critically stressed fault patches (p. 3, 126–128).
- **Shutdown experiments (the core data):** a dense seismic array was deployed at each shutdown.
  - Dec 2016 shutdown (19.45 h): 1,302 stations, operated by a contractor for another DOE project (p. 18, 80).
  - Apr 2021: 37 nodes (p. 19).
  - Apr 2022: 450 three-component nodes, the "audit" dataset (p. 23).
  - Pressure was recorded in 13 idle wells in spring 2022 (p. 17).
- **New drilling in 2022:** 4 wells were logged (cuttings every 10 ft, image logs, sonic logs, temperature/spinner logs) (p. 47).
- **Other work:** lab tests on surface rock samples (p. 26–41), InSAR and GPS deformation (p. 61–71), and hydrologic inversion of 2016/2017 pumping tests in COMSOL (p. 72–78).
- **GEOS models** were built in two flavors (p. 107–124, 141):
  - Short-term H-M (hydro-mechanical: fluid pressure plus rock stress), over hours to days, for seismicity and pressure.
  - Long-term T-H-M (adds heat flow), over years, for InSAR/GPS and stress orientation.
- **Outputs:** 3 journal papers, 2 MS theses, 20 talks and 17 public datasets (p. 3).

## The geological model
- **Inputs.** The geologic model itself came from Ormat (Folsom 2020). It combined:
  - Rhodes (2011) surface mapping;
  - 211 magnetotelluric (MT) stations, 1,207 gravity stations and 176 line-km of ground magnetics;
  - a 1,302-station passive seismic survey;
  - drilling results since the 1970s (p. 8, 80, 148).

  WHOLESCALE added:
  - cuttings densities and lithology columns, lost-circulation and feed zones, resistivity/acoustic image logs (fractures, drilling-induced tensile fractures, "DITFs") and sonic logs from wells 17A-21, 18A-21, 25B-21 and 84-20 (p. 47–50);
  - regional stress indicators: World Stress Map, nearby fields, fault slickensides, 2016 Gerlach earthquakes (p. 42–44);
  - lab E, ν and Biot measurements on outcrop samples, because no drill core was available (p. 26);
  - relocated microseismic events and a 3D P-wave velocity (Vp) model (p. 82–101);
  - Ormat well coordinates and open intervals, flow rates and pressure records (p. 72).
- **What the model contains:**
  - *Units and domain.*
    - Leapfrog version, 5 units (deepest first): TrJn metasediments, Tvu andesite/tuff, Tpb basalt, Qal alluvium, Qas silicified alluvium (p. 72).
    - GEOS mesh, 6 element sets: Qal/QTa, Qas, Tpts, Tpts′, TrJn, Ts. The naming is not reconciled with the Leapfrog units (p. 107).
    - Domain: "~6 km × 5 km × 2 km" (p. 8). An AGU abstract says ~10 × 10 × 3 km (p. 158).
  - *Faults.*
    - The 2022 map names 8: RFF, NF, FF, AF, SEF, BBF, PF, NWF (p. 10). **Sherman's "24 faults" is not stated.**
    - In COMSOL, only SEF and BBF were permeable zones, each 1 m wide (p. 73).
    - In GEOS, faults appear as offsets in unit geometry plus one `fault_se` element set with its own permeability (p. 107–108).
  - *Per-unit properties (Table 13, p. 108):* anisotropic k from 3.1e-14 to 4.3e-11 m², porosity 0.05–0.35, bulk modulus 5.7–28.6 GPa, shear modulus 4.3–21.5 GPa, density 2,120–2,800 kg/m³, and Biot 0.36 everywhere.
  - *Boundary and initial conditions (Table 12, p. 107):*
    - zero-displacement sides and base; hydrostatic pressure on the y-edges;
    - injection wells at −94.3 °C relative temperature; well mass fluxes of ~920–990 kg/s as listed;
    - initial temperature from Folsom's "natural state" 80–150 °C contours (p. 111).
- **How it was built:**
  1. Ormat (M. Folsom) built the geometry in **Leapfrog Geothermal** as volumes, fault and contact surfaces, and well paths. It was updated in 2022 after the new wells (p. 10, 72, 160).
  2. Cardiff imported it into COMSOL, made a tetrahedral mesh that follows the unit boundaries (≤50 m near wells), and inverted for permeability (next section) (p. 72–73).
  3. Luo, Sherman and colleagues built a tetrahedral GEOS mesh (Luo et al. 2024, Stanford workshop). **The Leapfrog→GEOS conversion tool and file format are not stated.** CUBIT appears only in the bibliography (p. 170).
  4. Pre-stress (Jahnke et al. 2023):
     - They built stress profiles for 22 wells: Sv from density; SHmax and Shmin from a friction limit of μ = 0.6.
     - They let the stress equilibrate in GEOS, repeating this for 78 realizations of SHmax azimuth and stress ratio.
     - They picked the realization by how prone the SEF/BBF faults were to slip ("slip tendency"): transtensional (Sv = SHmax > Shmin), SHmax N–N10°E (p. 45, 145).
     - Example: at 1,636 m in Kosmos 1-9, Sv = SHmax = 39.3 MPa and Shmin = 23.5 MPa (p. 45).
- **Where judgment and uncertainty entered:**
  - The structural geometry is a single deterministic interpretation.
  - Uncertainty was explored only in the parameters: 4 permeability "conceptual models" in COMSOL, 78 stress realizations, and about 26 permeability cases in GEOS (p. 73, 115).
  - The fault model "was constructed without seismicity constraints". The relocated earthquakes sit up to ~200 m off the modeled faults (p. 101).
- **Why it was hard:**
  - The field sits in a right-step of a normal-fault zone with dense, intersecting faults (p. 7).
  - Stress is transitional between normal and strike-slip faulting, and the DITF azimuth rotates with formation: N30E, N10E, N40E (p. 56).
  - There is no core, and QTa and Tpts could not be tested in the lab (p. 26).
  - Wells only 6–30 m apart hit feed zones at different depths, and the BBF looks like multiple strands (p. 48–49).
  - Pressure data imply flow paths "not currently represented in the geologic conceptual structure" (p. 74).
  - Conductive fractures do not align with the major faults (p. 141).

## How GEOS models were checked against reality
- **Scoring setup.** A pre-registered set of Technical Performance Metrics (TPMs) with a "minimum" and a "target" level. The misfit is mean(|U_obs − U_mod|), with calibration and audit datasets kept separate (Table 14, p. 109).

| TPM | Observation | Min / target | Result |
|---|---|---|---|
| 1 | Microseismic events (MSEs), scored by where and when ΔCFS > 0 | location 250 / 100 m | 88% of 32 focal-mechanism planes had ΔCFS > 0; 60% of 2016 events fell in positive-ΔCFS time windows; audit on 2022: 85%; location TBD (p. 117–118) |
| 2 | Stress orientation (DITFs in 17A-21) and Sv magnitude | 20°/10°; 10/5 MPa | "within 20°" (p. 141); table still says TBD (p. 110) |
| 3 | Pressure in 6 wells, 2017 flow test | 50 / 20 kPa | GEOS H-M: best RMS of 36.8–40.9 kPa from a hand sweep (case 40); COMSOL H-only overall RMSE 5.2–5.8 kPa (p. 78, 114–116) |
| 4 | Vertical velocity (InSAR 2016–22, GPS) | 10 / 5 mm | pixel misfit 1.1 mm/yr, but the SEMN–SEMS rate is 28 mm/yr modeled vs 7 ± 2 observed: **4× too fast**; the model misses the playa-area gradient (p. 111–112) |

In the TPM 1 row, ΔCFS is the change in Coulomb failure stress, i.e. whether the modeled stress change pushed a fault toward slipping.

- **Seismicity method:**
  - Assume the rock was critically stressed at t_ref; take GEOS stress (sign flipped), μ = 0.6, cohesion 0.
  - Compute ΔCFS on each event's two candidate fault planes, and on optimally oriented planes on a 100 m grid every hour.
  - Check event timing and location against positive-ΔCFS zones (p. 117; Figs 74–75, p. 122–123).
- **Calibration method:**
  - COMSOL: formal Gauss-Newton least squares on log-permeability, with 4 competing conceptual models (RMSE 5.2–5.8 kPa; the structure was judged by how plausible the fitted values are) (p. 73–78).
  - GEOS: manual trial of permeability sets (Table 18, p. 115). No inversion.
- **What didn't work:**
  - The joint "calibrate THM on ALL data" (Subtask 9.5) remained "we plan to" (p. 124).
  - Deformation stays 4× off. Permeability "will require further tuning" (p. 112).
  - The cyclic-seismicity explanation is "plausible, but not definitive" and fine-tuned (p. 134–135).

## What this means for an LLM-agent benchmark
- **The report does not show the build process.** It skips the "solid year" of geologic modeling: Ormat did it in commercial Leapfrog, and it is described only by citation (Folsom 2020). To learn how that year was spent, read Folsom 2020 (Stanford workshop PDF, also on GDR 1434) and Luo et al. 2024.
- **Candidate task (hard):** from public San Emidio data, build a GEOS-readable model with units, faults, properties and pre-stress. Inputs: GDR maps, MT, gravity, well coordinates and flux. Score it downstream with WHOLESCALE's own TPMs: run the 2016 shutdown and compute ΔCFS hit rate, pressure RMS and the InSAR rate.
- **Pre-registered metrics with thresholds (Table 14)** are directly reusable as a scoring rubric. The calibration/audit split (2016 vs 2022 shutdown) is a natural held-out test.
- **Held-out observation sets exist publicly:**
  - 2022 MSE catalog (GDR 1614);
  - 2016 catalog and Vp model (Guo 2023 supplement);
  - well flux (GDR 1552) and well coordinates (GDR 1551);
  - GPS (GDR 1338).
- **Ground-truth geomodel caution:** the 2022 Folsom/Ormat Leapfrog model and the GEOS mesh/deck are **not** in the report's data table (p. 144), so they are likely proprietary. The closest public ground truth is the older UNR **"3D Model of the San Emidio Geothermal Area"** (GDR 365: 5 units, 55 faults, 2013). It predates the 2022 update.
- **Hard parts for an agent:**
  - fault network interpretation and unit naming that is inconsistent across tools;
  - no core;
  - stress regime ambiguity;
  - permeability controlled by features smaller than the model resolves;
  - even the experts' model misses deformation by 4×, so scoring should be relative (beat a baseline), not "match the truth".

## Numbers worth remembering
- Production is 190–280 L/s at 140–148 °C, about 9 MW net. The reservoir is 400–700 m deep; most events are within 400 m of a producer (p. 7, 141).
- 2016: 123 events from the original catalog, and >1,000 after reprocessing. 2022: 1,761 events (1,575 during the shutdown), M −3 to 1.1 (p. 80, 97, 99).
- Pressure rise during a shutdown is ~40 kPa within hundreds of meters. Pcrit ≈ 7,000 kPa at 700 m. ΔCFS on the triggering planes was 10–50 kPa (p. 131–132).
- Subsidence is 7 ± 2 mm/yr near the producers. Shmin gradient ≈ 13.7 MPa/km, from a leak-off test (p. 50, 141).
- Lab dynamic E (outcrop samples): TrJn 78–86 GPa, Tpb′ 28–42 GPa, Tss 57–58 GPa; samples essentially isotropic (p. 30).

## Data availability
Listed in the report (Table 22, p. 144). All are on the DOE Geothermal Data Repository (`https://gdr.openei.org/submissions/<ID>`) unless noted. Sizes are from GDR pages checked 2026-09-23.

| ID | Title (abridged) | Size |
|---|---|---|
| 1395 | Seismic Survey 2016 data (raw) | ~1.3 TB + 1.27 TB |
| 1386 | Seismic Survey 2016 metadata (+ Warren/Teplow reports) | ~55 MB |
| 1441 | Passive Seismic Emission Tomography results + P-wave velocity model (CSV) | 62 MB + 4.4 MB |
| 1434 | MT data 2016 (EDI, Occam 1D, includes Folsom_2020.pdf) | ~130 MB |
| 1478 / 1463 | 2021 seismic data / metadata | 1.67 TB / ~25 MB |
| 1610 | 2022 seismic waveforms, pointer to EarthScope (FDSN net 4Q, doi 10.7914/m5qt-mh37) | small |
| 1614 | 2022 microseismic event catalog | 170 kB |
| 1551 | Well coordinates (Well Specs.csv) | 2 kB |
| 1552 | Well mass-flux rates, Dec 2016 | 1.8 MB |
| 1338 | GPS RINEX and time series (SEMN, SEMS, GARL) | not shown |
| 1357 / 1396 | Rock-sample catalog v1 / v2 | ~860 MB photos / 21 kB |
| 1356 | Seismic 2021 example data | "in progress" |

- The 2016 event catalog with focal mechanisms and the 3D Vp model are supplements to Guo et al. 2023, JGR 128, e2023JB027008.

Also found on GDR by search, not in the report:
- **365**, 3D Model of the San Emidio Geothermal Area (UNR/Faulds 2013; 5 units, 55 faults), 34.8 MB, 136 files;
- **371**, Slip and Dilation Tendency Analysis, San Emidio (UNR 2013), 19.7 MB;
- **674**, Play Fairway CA-NV-OR: San Emidio geophysics (gravity 2012/2015, magnetics, PSInSAR, SP; xlsx, ~13 MB);
- **852**, 3-component long-offset seismic survey (2010; P 540 MB, S 225 MB, report 30 MB);
- **1147**, PoroTomo InSAR, San Emidio 1992–2010 (~220 MB).

No GEOS input deck, mesh or Leapfrog project file is published, per the report and the GDR search. InSAR/TerraSAR-X processing products are not listed either.
