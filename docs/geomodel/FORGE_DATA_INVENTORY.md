# Utah FORGE public data inventory (for the geological-model benchmark)

Snapshot 2026-09-23. Downloads complete: 1,036 files, 117 GB on disk, 0 failures. Machine-readable manifest: `/data/matt/sci-sim-op/geomodel/forge/manifest.json`
(one record per GDR submission plus 4 non-GDR sources). Files land in `/data/matt/sci-sim-op/geomodel/forge/raw/<gdr_id>/`.
Scripts: `scripts/geomodel/forge_build_manifest.py` (enumerate + classify), `forge_overrides.py` (hand review),
`forge_download.py` (download; `--status` shows progress).

## How the data was enumerated

GDR has no JSON search API, and its "Search Utah FORGE Data" project filter (`search?pj[]=utah_forge`) is broken
(it returns all 1,455 submissions). What works:

1. `https://gdr.openei.org/data.json`: a DCAT catalog of all submissions, with a DOE `projectNumber` field.
   Utah FORGE's award number is **EE0007080**. The catalog is missing about 40 of the newest submissions.
2. `https://gdr.openei.org/sitemap.xml` lists every submission id (1,455).
3. The HTML search pages `search?q=EE0007080` (380 hits) and `search?q=Utah+FORGE` (515 hits), paged with `&from=N`.
4. Each of the 538 candidate pages was fetched once and cached in `meta/pages/`. From each page we parsed the
   schema.org JSON-LD block (title, date, authors, organizations) and the resource list (file name, URL, size).
   A submission was kept if it belongs to project EE0007080 or its text names the FORGE wells or site.
   7 submissions that mention FORGE only in passing were excluded by hand.

Result: **392 GDR submissions** (published 2016 to 2026-06). They list **1,088 GDR files, 178 embargoed files**
(Fervo data, released 2027 to 2029), 127 external links, and 5 links into the public **OEDI S3 bucket**
`s3://gdr-data-lake/FORGE/`. That bucket holds 1.18 M objects and **292 TB** of raw DAS and geophone waveforms
(GDR 1680, 1725, 1824). utahforge.com's Data Dashboard links only to OpenEI wiki pages, which point back to GDR. Its TLS
chain is misconfigured, so fetching it needs `-k`. The UGS report MP-169 (2019, the published basis of the Phase 2
earth model) was added as a non-GDR source.

Classification is keyword rules on title and description, then a hand review of about 150 submissions, covering every
model, stress, well and eval record. Every record carries `category`, `role_guess`, `role_reason`, `classified_by`,
`priority` and `phase_or_date`. `phase_or_date` holds the publication date, any phase named in the text, and a phase
inferred from the date: 1/2A before 2017; 2B 2017 to mid-2018 (58-32 drilled); 2C mid-2018 to early 2020;
3A 2020 to 2022 (16A drilled, 2022 stimulation); 3B 2023 on (16B drilled, 2024 stimulation, circulation tests).

## Categories (GDR submissions; sizes are as listed by GDR)

| category | subs | role mix | auto files | auto GB | deferred files (>2 GiB or S3) | deferred GB |
|---|---|---|---|---|---|---|
| reports | 103 | context | 152 | 9.6 | 0 | 0 |
| core_lab | 55 | 28 input / 25 context (analogue-rock lab) / 2 eval | 253 | 36.3 | 11 | 216 |
| fiber_das_dts | 33 | 30 eval | 73 | 6.9 | 14 | 147,400 (S3) |
| microseismic | 27 | 18 eval / 4 input (background) | 31 | 0.9 | 0 | 0 |
| well_logs | 27 | 21 input | 115 | 19.4 | 8 | 48.7 |
| stimulation_injection | 25 | 23 eval | 69 | 1.0 | 0 | 0 |
| maps_gis | 19 | input | 25 | 0.6 | 2 | 17.3 |
| other | 19 | 7 input / 12 context | 35 | 1.4 | 3 | 22.0 |
| potential_fields (grav/mag/MT/EM) | 12 | 10 input | 21 | 0.4 | 0 | 0 |
| stress_tests | 12 | 10 input | 33 | 0.3 | 1 | 2.9 |
| temperature | 10 | 9 input | 23 | 0.2 | 0 | 0 |
| geodesy (InSAR/GPS) | 10 | eval | 49 | 8.3 | 2 | 21.2 |
| simulation_outputs | 10 | context | 16 | 0.1 | 0 | 0 |
| seismic_reflection (+velocity models) | 8 | 2 input / 4 model | 17 | 5.2 | 15 | 133.5 |
| dfn_model | 8 | 6 model | 93 | 21.9 | 1 | 3.5 |
| geologic_model | 5 | 4 model | 16 | 1.1 | 0 | 0 |
| native_state_or_reservoir_model | 5 | model | 7 | 0.8 | 0 | 0 |
| image_logs | 4 | input | 7 | 0.6 | 1 | 2.3 |

Roles: 115 input, 20 model, 86 eval, 171 context. 60% are Phase 3B (2023 on), many of them R&D workshop slides.

## The geological model: ground-truth candidates (all opened and checked)

FORGE's model has two rock units (granitoid basement and the basin fill above it) plus natural fractures, as
Sherman described. It exists as a sequence of versions, each built in Leapfrog Geothermal (Seequent) by EGI/UGS and
handed to INL for native-state (THM) simulation. Coordinates are UTM 12N, NAD83, NAVD88.

1. **Phase 2C block model: GDR 1205** (published 2020-03, built 2019-06/08). Best single GT artifact.
   `Mesh Files.zip` holds Leapfrog CSV exports. `2019.08.21_global_cell.csv` has 137,500 cells (50×50×55) at 50 m,
   rotated 25° clockwise to align with the principal stresses. Centroid z runs from −1475 to +1225 m elevation,
   covering 2.5 × 2.5 × 2.75 km. Each cell is labelled `GM_8_19_2019` = `Granitiod` (98,610) or `Basin Fill` (38,890).
   Node files (145,656 nodes) come in global and local frames.
   `Initial Conditions.zip` → `IC/2019.06.10_IC_local_node_v2.xlsx` gives P, T (K), depth and stress on the same nodes.
   The stress columns are Excel formulas: depth gradients (for example 17.4 and 14.6 kPa/m for the two horizontal
   stresses) combined with pore pressure. This is GEOS-ready as it stands (lithology per cell).
2. **Phase 2B earth-model surfaces: GDR 1107** (2018-12). Plain `x,y,z` vertex CSVs with **no triangle
   connectivity**, so they would have to be re-triangulated. `top_granitoid_vertices.csv` (the granitoid/basin-fill
   contact) has 103,455 points on a 50 m grid over x 329,950–344,150 and y 4,252,850–4,270,950 (about 14 × 18 km),
   z −2112 to +2723 m. `land_surface_vertices.csv` has 413,250 points from the 10 m DEM.
   `Opal_Mound_Fault_vertices.csv` (2,029 points) and `Negro_Mag_Fault_vertices.csv` (1,505 points) are the faults.
   `175C_vertices.csv` and `225C_vertices.csv` are isotherm surfaces.
   The companion GDR 1108 holds geologic and topographic map TIFFs. These are **RGB renderings without geotags**, not
   categorical rasters. It also has the site outline shapefile. GDR 1036 is only a video of the Leapfrog model.
3. **Native-state models** (INL; these use the geologic model as their mesh and add P/T/stress):
   - GDR 1160 (Phase 2C, 2019-07): FALCON results on the 1205 nodes. Columns are
     `x,y,z,temperature_C,pressure_Pa,Sigma_V_Pa,sigma_h_max_Pa,sigma_h_min_Pa`, plus per-cell Kii/Kjj/Kkk
     (7e-18 to 1.7e-14 m²) and porosity from the upscaled DFN. GDR 1315 holds the FALCON `.i` inputs and Exodus `.e` meshes.
   - GDR 1397 (Phase 3, 2022-07): FALCON `.i`, Gmsh `forge_model80x40x40.msh` (4 × 4 × 4.2 km, 0.24 M tetrahedra,
     two units: granitoid and basin fill), Exodus output, and point data along wells 16A, 56-32, 58-32, 78-32 and 78B-32.
   - **GDR 1812 (2025 update, published 2026-01)**: MOOSE/PorousFlow `nativeStateModel2025.i` and Gmsh 4.1 meshes at
     200, 60 and 40 m (6 × 6 × 4.5 km, local frame). The physical volumes are `matrix_133` (granitoid: k 5e-17 m²,
     φ 0.0002, E 62 GPa) and `matrix_134` (sediment: k 1e-14 m², φ 0.12, E 30 GPa). The top and bottom T/P boundary
     conditions were exported from Leapfrog. This is the newest version of the FORGE geology, already in a mesh format.
4. **DFN (WSP/Golder, Finnila)**, a separate model component, versioned:
   - GDR 1222 (2020-06): stochastic FracMan DFN built before 16A was drilled. 65 gzip `.fab` files; one region has
     626,542 hexagonal fractures with permeability, compressibility and aperture. `Filtered_800m_all_csv.zip` holds
     30 realizations of about 4,900 fractures each, with columns
     `FractureX/Y/Z, Radius, Trend, Plunge, Strike, Dip, Aperture, Permeability, Compressibility, Transmissivity, Storativity`.
     Also provided as GOCAD `.ts`.
   - GDR 1317 (2021): simplified DFN around 16A, plus permeability tensors. GDR 1554 (2023): 5 realizations of an
     1800 × 1500 × 1000 m model, upscaled to 10 m and 20 m grids (`CellX,Y,Z, Perm_I/J/K, Porosity, Compressibility`).
   - GDR 1646 (2024): the February reference DFN, conditioned to FMI picks in 16A, 16B, 56-32, 58-32 and 78B-32 and to
     2022 stimulation seismicity (MEQ), plus May and July MEQ-fitted planes.
   - **GDR 1750 (2025 v1)**: 133 rows of deterministic fractures (`object, center XYZ, trend/plunge, strike/dip,
     radius`) plus 19,541 stochastic fractures with radii of 20–150 m, in csv, fab and ts formats.
     **It uses the 2022 and 2024 stimulation data** (MEQ, frac hits, spinner logs), so it is post-eval. Leakage warning.
   - Only 1222 and 1317 are pre-stimulation. The 1646 Feb-2024 reference DFN already includes planes fitted to
     2022 stimulation seismicity (`MS_Stage1-3`).

**Recommendation.** Use a two-unit geology as the GT: GDR 1205 (2019 block model), GDR 1107 (contact and fault
surfaces), and GDR 1812 (current version, 2025 mesh). Treat a stochastic DFN as a statistical target, not a
deterministic one: fracture-set orientations, intensity and size distribution from GDR 1222/1317. Treat
1426, 1646, 1750 and 1554 (conditioned on 16A) as eval-contaminated or later versions.

## Key raw inputs (what an expert would build the model from)
- Wells: 58-32 (GDR 1006 logs, 1101 P-T, 1162/1007 core, 1076/1299 FMI); 16A(78)-32 (1283, 1292, 1595 FMI, 1550 core);
  16B(78)-32 (1516, 1531, 1727, 1566); 56-32 (1295); 78B-32 (1330); older regional wells 9-1, 14-2, 52-21, 82-33
  and Acord-1 (705–709, 747); well coordinates and trajectories (1268, 1440, 1216).
- Stress: 58-32 injection/DFIT tests 2017–2019 (1109, 1146, 1149, 1210, 1032); 16B mini-fracs (1570, 1596); 16A stage-1 falloff (1408).
- Geophysics: seismic reflection (1141 reprocessed, 0.9 GB; raw SEG-Y in 1015 deferred), gravity (717, 1002, 1144, 1327),
  MT (712, 1255, 1578), ZTEM (1336). Maps/GIS 701, 713, 1034; LiDAR 1083/1084; temperature 698, 711, 714, 1012, 1326, 1421.

## Key eval observations (reservoir response)
- 2022 16A stimulation: 1379 (pumping), 1399/1429/1558 (MEQ catalogs), 1418 (strainmeter), 1420 (tracer), 1393 (DAS).
- 2024 16A/16B stimulation and circulation: 1611, 1645, 1695, 1674/1584/1622/1817 (catalogs), 1818 (frac hits),
  1617/1691/1721 (DTS/DSS), 1701/1703 (tracers), 1575/1668/1683 (circulation), 1764/1804 (shut-in pressure).
- InSAR and GPS (1154, 1487, 1490, 1491, 1619, 1143) and produced-fluid chemistry (1715, 1741).

## Deferred (not downloaded)
- 53 files are over 2 GiB and 5 links point to S3 prefixes (58 deferred items): **~148 TB listed**, almost all in the S3 DAS data lake
  (1680: 107 TB, 1725: 39 TB, 1824: 1.4 TB). Other big items: raw 2D/3D seismic SEG-Y in 1015 (15 files, 134 GB);
  analogue-rock lab data (1774: 196 GB); LiDAR and slope rasters (17 GB); the Stanford CONUS thermal model (22 GB);
  InSAR (21 GB).
- **Worth fetching by hand** (about 56 GB, all inputs). The full Schlumberger wireline and image-log packages are
  deferred: 56-32 `Schlumberger_56-32.zip` 8.3 GB, 16A `Schlumberger.zip` 6.3 GB, 16B `Wireline data.zip` 5.1 GB,
  `Processed FMI and UBI.zip` 9.1 GB, 78B-32 FMI/UBI 5.7 GB, 58-32 FMI DLIS 2.1 GB, 16B mini-frac logs 2.7 GB, and the
  1750 DFN development notes 3.3 GB. Run: `forge_download.py --only 1292,1295,1531,1330,1076,1570,1750 --max-file 10`.

## Gaps and surprises
- **No native Leapfrog project (.lfproj) or Petrel file is public.** The geology exists only as CSV exports (1205, 1107)
  and as meshes inside the native-state models (1397, 1812). The fault surfaces have no connectivity. The 1205 block
  model has only two units: no faults and no sub-units (for example, no granitoid vs gneiss split). The Opal Mound and
  Negro Mag faults exist only as point clouds in 1107.
- Model versions and publication dates for a time-based partition: 2B surfaces (2018-12), 2C block model and
  native-state (built 2019, published 2019-07 and 2020-03), stochastic DFN (2020-06), Phase 3 native-state (2022-07),
  DFN 2023/2024/2025, native-state 2025 (2026-01). A clean cut-off is "data published before 2020-03": that includes
  58-32 and the regional data, and excludes 16A/16B and all stimulations.
- The 1108 map "GeoTIFFs" carry no georeferencing. GDR serves `.fabgz` with `Content-Encoding: x-gzip`; HTTP clients
  silently decompress it, so the downloader writes the raw bytes instead.
- Fervo's data is filed under FORGE's award: Cape Station, adjacent to FORGE (8 submissions), and Project Red,
  Nevada (3). All 11 are embargoed until 2027–2029 and marked `context`. Many "FORGE" lab datasets use Westerly or
  Sierra White granite rather than FORGE rock; these are marked `context`, priority 4.
