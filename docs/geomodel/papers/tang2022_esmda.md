# Updating a 3D reservoir model from InSAR with ML surrogates and ES-MDA — Tang 2022
H. Tang, P. Fu, H. Jo, S. Jiang, C. S. Sherman, F. Hamon, N. A. Azzolina, J. P. Morris, "Deep learning-accelerated 3D carbon storage reservoir pressure forecasting based on data assimilation using surface displacement from InSAR", Int. J. Greenhouse Gas Control, 2022 (LLNL-JRNL-830880) · [OSTI](https://www.osti.gov/biblio/2005124) · local: `/data/matt/sci-sim-op/geomodel/papers/osti_2005124_tang2022.pdf`

Page numbers are PDF pages of the accepted manuscript.

**In one sentence:** On a synthetic CO₂-storage reservoir, they update an ensemble of 3D models (rock type, porosity and permeability per cell) so that simulated ground uplift matches a "measured" uplift map. GEOS generates training data for neural-network stand-ins ("surrogates"), which replace GEOS inside the loop. The whole update then runs in about 30 minutes on a laptop, versus about 3,000 core-hours with GEOS (p. 39).
**Why Sherman sent it:** It is a template for **calibrating a geological model against observations** at scale: build many plausible models from well data, run GEOS, and keep the ones that match the data. For us it shows how a geomodel could be updated and scored against a map-like observable.

## What they did
- Built a synthetic "truth" reservoir, then generated 1,000 plausible prior models conditioned on data queried along 9 wells (p. 21–25).
- Compressed each model to 946 numbers: PCA plus a CNN post-processor for rock type (290 dims) and plain PCA for porosity and permeability (656 dims) (p. 9–10, 25).
- Ran GEOSX forward models (two-phase CO₂/brine flow, then one-way coupled mechanics) to train two 3D-to-2D residual U-Nets. One predicts the surface uplift map, the other the depth-averaged pressure map (p. 13–19, 26–27).
- ES-MDA (ensemble smoother with multiple data assimilation) updated 100 models over 12 iterations to fit the uplift map at year 2, then forecast pressure to year 10 (p. 32–34).
- Sensitivity tests on noise level (5/7/10%) and on how much of the uplift map's variance was kept (90/94/97%) (p. 35–38).

## The geological / earth model in this paper
- **Inputs (data used to build it):** entirely synthetic. The reference model follows a clastic-shelf setting from Bosshart et al. (2018). Porosity and permeability are sampled from the EERC Average Global Database (p. 21). Prior models use "virtual well logs" along 4 injectors and 5 exploration wells, with 100% Gaussian noise on porosity and permeability (p. 24).
- **What the model contains:**
  - Reservoir: 32,156 × 32,156 × 85 m, 64 × 64 × 28 cells, 2 rock types (shaly sand, sand), per-cell porosity and permeability, rock-type relative permeability curves, pore compressibility 4.64e-9 1/Pa (Table 2, p. 21–22).
  - Mechanics: 6 overburden layers plus a dolostone basement, each with thickness, Young's modulus and Poisson's ratio (Table 3, p. 22). Example: reservoir at 1,219 m depth, E = 9.9–18.9 GPa. Reservoir stiffness is tied to porosity (Eq. 19).
  - In-situ stress, temperature and boundary conditions: **not stated**.
- **How it was built:** geostatistics in GSLIB. Rock type by sequential indicator simulation; porosity and permeability by sequential Gaussian simulation; then rescaled per rock type. Variogram ranges are drawn at random: rock type 12.6–20.1 km major; porosity/permeability 1.5–2.5 km major (Table 4, p. 24–25). Judgment enters in the variograms, the noise level, and the choice of 9 wells: the 4 injectors alone could not constrain the model (p. 41).
- **Format handed to GEOS:** a structured cuboid grid with cell-wise properties (GEOSX). File format: **not stated**.

## How it was checked against reality
Only against the synthetic truth (a "twin experiment"; there are no real InSAR data, p. 41–42).
- Observation: the year-2 surface uplift map (4,096 pixels) plus 5% white noise, compressed to 11 dimensions (p. 32).
- Metrics: RMSE of the posterior-mean maps against truth. Uplift RMSE is 0.27 mm (year 2) and 0.60 mm (year 10); pressure RMSE is 0.08 MPa and 0.12 MPa (p. 33–34). The paper also reports the 95% confidence interval of R² across the ensemble (Tables 5–6).
- Surrogate accuracy on 100 test cases: R² 0.985 for uplift and 0.983 for pressure, with 6,200 training runs (p. 27).
- Explicit stance: matching the reference geology is **not** the goal; forecast skill is (p. 34).

## What this means for an LLM-agent benchmark
- **Scoring idea to borrow:** score an agent's geomodel by how well its forecasts match held-out observations, not by how close it is to a "true" geology, which is unknown in the field (p. 34).
- **Twin-experiment design:** make a hidden reference model, give the agent sparse well data, and score the agent's model on predicted observables. This gives exact ground truth, but it is synthetic.
- **Agent task candidates:** choosing variograms, conditioning geostatistics on logs, and setting up the GEOS mesh and property files. The ES-MDA/U-Net machinery is a downstream tool, not the task.
- **Relevance to FORGE is limited:** this is sedimentary layered geology with GSLIB statistics, while FORGE is fractured granite. InSAR is a real FORGE-area observable, though (Feigl et al., separate paper in our folder).
- **Hard parts:** real InSAR has gaps and correlated noise (p. 41–42). Four injector wells alone were too few to constrain the priors.

## Numbers worth remembering
- 64 × 64 × 28 grid; 946-dimensional latent space; 1,000 prior models.
- ES-MDA: ensemble size 100, 12 iterations. Larger kept-variance settings (94%/97%) needed ensembles of 1,000 and 3,000 to avoid collapse (p. 35–38).
- Cost: GEOSX runs about 2 core-h (pressure) and about 0.25 core-h (uplift). Full ES-MDA with GEOSX is about 2,925 core-h, with surrogates about 0.5 h on a laptop. Training data cost about 13,950 core-h (Table 7, p. 39–40).
- Injection: 2 Mt CO₂/yr through 4 wells for 10 years (p. 21).
- Pressure forecasts stay reasonable up to 10% noise and break down beyond that (p. 36).

**Data / paper leads for FORGE:** none FORGE-specific. Method leads: Bosshart et al. 2018, IJGGC 69:8–19 (depositional-environment reference models); EERC Average Global Database; Liu & Durlofsky 2021 (CNN-PCA); Emerick & Reynolds 2013 (ES-MDA).
