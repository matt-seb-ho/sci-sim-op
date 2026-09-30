"""Hand-reviewed classification for FORGE GDR submissions, plus non-GDR sources.

The keyword classifier in forge_build_manifest.py gets most records right; the
entries here fix the ones it gets wrong and pin the important ones (geologic
model, DFN, native-state model, stress) with an explicit reason. Keys are GDR
submission ids. Fields: category, role_guess, reason, phase, priority (1 = download first).
"""

# Matched only because the text mentions Roosevelt Hot Springs / FORGE in passing.
EXCLUDE = {"236", "955", "959", "1126", "1266", "1509", "1556"}

M, I, E, C = "model", "input", "eval", "context"


def _o(cat, role, reason, phase=None, priority=None):
    d = {"category": cat, "role_guess": role, "reason": reason}
    if phase:
        d["phase"] = phase
    if priority:
        d["priority"] = priority
    return d


OVERRIDES: dict[str, dict] = {
    # ---------------- geological (earth) model: the ground-truth candidates
    "1107": _o("geologic_model", M, "Phase 2B Leapfrog earth-model surfaces as vertex CSVs: land surface, top granitoid (basin-fill contact), Opal Mound & Negro Mag faults, 175/225 C isotherms", "2B", 1),
    "1205": _o("geologic_model", M, "Phase 2C Leapfrog export: lithologic contact mesh (granitoid vs basin fill) + initial T/P/stress on 3-D points", "2C", 1),
    "1108": _o("geologic_model", M, "Earth-model companion maps: geologic map rasters, topographic map, site outline (GeoTIFF/shapefile)", "2B", 1),
    "1036": _o("geologic_model", C, "Video fly-through of the Leapfrog 3-D geologic model; visual only", "2B", 1),
    "1110": _o("native_state_or_reservoir_model", M, "1-D analytical temperature model from wells, corrected with the earth model", "2B", 1),
    "715": _o("geologic_model", M, "Phase 1 basin-depth contour model and potentiometric contours (shapefiles)", "1", 1),
    "1150": _o("reports", C, "UGS/EGI report on the Mineral Mountains West fault system (structural interpretation)", "2B", 1),
    # ---------------- native-state (thermal-hydraulic-mechanical) reference model
    "1160": _o("native_state_or_reservoir_model", M, "Phase 2C FALCON native-state P/T/stress on 50 m nodes + DFN-upscaled permeability", "2C", 1),
    "1315": _o("native_state_or_reservoir_model", M, "Phase 2 FALCON native-state model input/output files", "2B/2C", 1),
    "1397": _o("native_state_or_reservoir_model", M, "Phase 3 native-state model, 2022 update (FALCON inputs+outputs, 4x4x4.2 km)", "3A", 1),
    "1812": _o("native_state_or_reservoir_model", M, "Native-state model 2025 update (6x6x4.5 km; includes sediments)", "3B", 1),
    # ---------------- DFN models
    "1222": _o("dfn_model", M, "Golder/WSP stochastic DFN (FracMan .fab), 2020, pre-16A-drilling; Finnila et al. SGW 2020", "2C", 1),
    "1317": _o("dfn_model", M, "Simplified DFN + permeability tensors around 16A(78)-32, April 2021", "2C", 1),
    "1426": _o("dfn_model", M, "Fracture planes fitted to 2022 stimulation microseismicity (derived from eval data)", "3", 1),
    "1475": _o("dfn_model", C, "Documentation of DFN and fracture-propagation modelling", "3", 1),
    "1554": _o("dfn_model", M, "2023 large upscaled DFN realizations (fractures + 10/20 m property grids)", "3", 1),
    "1646": _o("dfn_model", M, "2024 DFN sets: Feb reference, Feb upscaled, May/July MEQ-conditioned", "3", 1),
    "1750": _o("dfn_model", M, "2025 v1 DFN: 131 deterministic planar fractures linking 16A/16B (uses 2022+2024 stimulation data)", "3", 1),
    "1807": _o("dfn_model", C, "Link to Seequent Central 3-D viewer of the 2025 v1 DFN", "3", 1),
    # ---------------- stress measurements (inputs to the stress model)
    "1032": _o("stress_tests", I, "Stress logging data from 58-32", "2A", 1),
    "1109": _o("stress_tests", I, "58-32 injection (mini-frac/DFIT-style) tests 2017 used to measure Shmin", "2A", 1),
    "1146": _o("stress_tests", I, "58-32 2019 small-volume stimulation for stress: paper + data", "2B", 1),
    "1149": _o("stress_tests", I, "58-32 2019 stimulation (3 zones) pressure/rate data; primarily stress measurement", "2B", 1),
    "1210": _o("stress_tests", I, "58-32 injection and packer performance Apr-May 2019", "2B", 1),
    "1408": _o("stress_tests", I, "16A stage-1 pressure falloff (Shmin) from the 2022 stimulation", "3", 1),
    "1570": _o("stress_tests", I, "16B(78)-32 mini-frac field tests (project 2439)", "3", 1),
    "1596": _o("stress_tests", I, "Report on 16B mini-frac tests for stress characterization", "3", 1),
    "1798": _o("stress_tests", C, "Lab wellbore-breakout tests", "3", 3),
    "1562": _o("stress_tests", C, "Lab triaxial shear and breakout tests (5-2557)", "3", 3),
    "1641": _o("simulation_outputs", C, "FE modelling of far-field stress (R&D project)", "3", 3),
    # ---------------- image logs
    "1299": _o("image_logs", I, "58-32 FMI fracture picks", "2A", 1),
    "1727": _o("image_logs", I, "16B(78)-32 Thrubit FMI reinterpretation", "3", 1),
    # ---------------- well data / geometry / geochem inputs
    "1140": _o("stimulation_injection", I, "78-32 capacity (hydraulic) test; pre-stimulation aquifer property", "2B", 2),
    "1268": _o("maps_gis", I, "Updated Phase 2C well location coordinates", "2C", 1),
    "1321": _o("maps_gis", I, "GPS survey of seismic stations and wells", "2C", 2),
    "1358": _o("maps_gis", I, "Updated well/pad/station GPS coordinates", "2C", 2),
    "1370": _o("maps_gis", I, "Shallow seismic well locations", "3", 2),
    "1440": _o("maps_gis", I, "Borehole sensor positions and well trajectories (Apr 2022)", "3", 1),
    "1216": _o("well_logs", I, "16A(78)-32 planned trajectory", "2C", 1),
    "1508": _o("microseismic", I, "Orientation of borehole/surface seismic stations (metadata)", "3", 2),
    "1286": _o("maps_gis", I, "Seismograph station information", "2C", 2),
    "1083": _o("maps_gis", I, "0.5 m LiDAR (topography)", "1", 2),
    "1084": _o("maps_gis", I, "LiDAR bare-earth DEM mosaic", "2A", 2),
    "1112": _o("maps_gis", I, "Terrain slope rasters derived from LiDAR", "2B", 3),
    "702": _o("maps_gis", I, "Satellite imagery and aerial photography", "1", 3),
    "697": _o("core_lab", I, "Well and spring water chemistry", "1", 2),
    "1024": _o("other", I, "Soil helium survey", "2A", 3),
    "1025": _o("other", I, "Soil CO2 survey", "2A", 3),
    "1138": _o("other", I, "Groundwater monitoring wells Wow2/Wow3", "2B", 3),
    "1252": _o("other", I, "Groundwater level monitoring", "2C", 3),
    "1335": _o("other", I, "Groundwater levels 2021", "2C", 3),
    "1371": _o("other", I, "Groundwater levels 2022", "3", 3),
    "718": _o("other", I, "Groundwater data", "1", 3),
    "711": _o("temperature", I, "Interpreted temperature contours (Phase 1)", "1", 2),
    "714": _o("temperature", I, "Heat-flow contours and well data", "1", 2),
    "720": _o("temperature", I, "Temperature contours at 200 m", "1", 2),
    "1608": _o("temperature", E, "16B P-T logs during the March-April 2024 stimulation period", "3", 3),
    "1437": _o("core_lab", I, "Deep-well water and gas sampling (Oct 2022)", "3", 2),
    "1715": _o("core_lab", E, "Produced-fluid geochemistry 2022-2024 (reservoir response)", "3", 3),
    "1741": _o("core_lab", E, "Produced-fluid trace elements 2024", "3", 3),
    "1629": _o("core_lab", I, "Geochemistry of cold groundwaters and produced fluids", "3", 2),
    "1322": _o("other", C, "Public-opinion survey on geothermal energy (not geoscience)", "2C", 4),
    # ---------------- background seismicity (site characterization) vs induced (eval)
    "700": _o("microseismic", I, "Regional natural earthquake information (background)", "1", 2),
    "1039": _o("microseismic", I, "Regional earthquake catalog (background, pre-stimulation)", "2A", 2),
    "1151": _o("microseismic", I, "Phase 2C background microseismic events", "2B", 2),
    "795": _o("microseismic", C, "Earthquake animation", "1", 4),
    "907": _o("microseismic", C, "Preliminary seismic monitoring/impact assessment report", "1", 3),
    "1319": _o("reports", C, "Induced Seismicity Mitigation Plan", "2C", 3),
    "1524": _o("reports", C, "2023 Induced Seismicity Mitigation Plan", "3", 3),
    "1706": _o("reports", C, "Seismic-risk traffic-light system v2", "3", 3),
    "1215": _o("microseismic", E, "Seismicity during the April 2019 58-32 injection", "2B", 3),
    "1385": _o("microseismic", E, "Seismicity associated with 2019 58-32 stimulation", "2B", 3),
    "1773": _o("microseismic", E, "Focal mechanisms, stage 3 of 2022 stimulation", "3", 3),
    # ---------------- seismic velocity models are derived products
    "1294": _o("seismic_reflection", M, "Seismic velocity models (Feb 2021) for event location", "2C", 2),
    "1585": _o("seismic_reflection", M, "Composite 3-D seismic velocity model", "3", 2),
    "1800": _o("seismic_reflection", M, "Empirical 3-D velocity model, Cape EGS + FORGE", "3", 2),
    "1496": _o("seismic_reflection", M, "Reservoir seismic velocity model + resolution study", "3", 2),
    "1470": _o("seismic_reflection", C, "Preliminary report on reservoir velocity model", "3", 3),
    "1723": _o("fiber_das_dts", M, "3-D Vp/Vs image from DAS+geophone data", "3", 3),
    "1848": _o("seismic_reflection", E, "2024 stress-shadow seismic survey (time-lapse around stimulation)", "3", 3),
    "1436": _o("potential_fields", C, "Synthetic 3-D resistivity model for EM survey design", "3", 3),
    "1144": _o("potential_fields", I, "3-D gravity data", "2B", 2),
    "1256": _o("potential_fields", I, "Phase 3 microgravity data", "2C", 2),
    "1719": _o("potential_fields", E, "Borehole EM (VEMP) data collection 2024 around stimulation", "3", 3),
    # ---------------- geodesy: InSAR/GPS are surface-deformation responses (eval),
    "794": _o("reports", C, "Paper on geodetic strain targeting of geothermal resources", "1", 3),
    "1621": _o("geodesy", E, "Deformation measurement and modelling 2018-2022", "3", 3),
    # ---------------- context: large national model, other sites, engineering
    "1592": _o("other", C, "Stanford thermal earth model of the conterminous US (national scale, not FORGE-specific)", "3", 4),
    "898": _o("core_lab", I, "Roosevelt Hot Springs drill-cuttings mineralogy (neighbouring hydrothermal field)", "1", 3),
    "938": _o("maps_gis", I, "SE Great Basin play-fairway maps/models (regional; includes FORGE area)", "1", 3),
    "1336": _o("potential_fields", I, "ZTEM airborne EM survey, Mineral Mountains", "2C", 2),
    "1530": _o("well_logs", C, "Fervo Nevada doublet reports (not the FORGE site)", "3", 4),
    "1504": _o("other", C, "Zonal-isolation device engineering tests", "3", 4),
    "1505": _o("other", C, "Zonal-isolation device engineering tests", "3", 4),
    "1506": _o("other", C, "Zonal-isolation device engineering tests", "3", 4),
    "1507": _o("other", C, "Zonal-isolation device engineering tests", "3", 4),
    "1425": _o("reports", C, "Multi-stage fracturing tool development", "3", 4),
    "1485": _o("reports", C, "Plug-and-perf stimulation design optimization (Fervo)", "3", 3),
    "1600": _o("other", C, "Meteorological data during 2024 stimulation", "3", 4),
    "1612": _o("other", C, "Meteorological data during 2023 circulation", "3", 4),
    "1603": _o("reports", C, "Fiber-optic cable installation report", "3", 3),
    "1481": _o("reports", C, "Video on drilling planning for 16B", "3", 4),
    "1582": _o("simulation_outputs", C, "DAS strain-signature simulations", "3", 3),
    "1581": _o("simulation_outputs", C, "Phase-field modelling of near-wellbore fracture nucleation", "3", 3),
    "1710": _o("simulation_outputs", C, "Hydraulic fracture growth simulations for stress roughness", "3", 3),
    "1766": _o("simulation_outputs", C, "Simulation meshes/results for circulation and pulse interference", "3", 3),
    "1247": _o("reports", C, "Evaluation of potential geochemical responses to injection", "2B", 3),
    "1729": _o("other", C, "Tracer thermal stability lab report", "3", 4),
    "1728": _o("other", C, "Fiber optic thermal slug experiments at Texas Tech (lab)", "3", 4),
    "1394": _o("core_lab", C, "Purdue b-value lab tests (rock saturation)", "3", 4),
    "1873": _o("other", C, "Source code (QuakeCastNet)", "3", 4),
    "1874": _o("other", C, "Lab acoustic-emission dataset (StraboSpot link)", "3", 4),
}

# Keep a hand-assigned phase only where the submission itself states it; otherwise
# the builder's date-based phase applies.
_PHASE_STATED = {"1107", "1108", "1036", "1110", "715", "1205", "1160", "1315", "1397", "1812", "1038", "1187"}
for _k, _v in OVERRIDES.items():
    if _k not in _PHASE_STATED:
        _v.pop("phase", None)
OVERRIDES["1038"] = _o("reports", C, "Phase 2B final topical report: conceptual geologic model, 58-32, geomechanics, temperature, seismic", "2B", 1)
OVERRIDES["1187"] = _o("reports", C, "Phase 2C topical report; appendix contains the updated conceptual geological model", "2C", 1)
OVERRIDES["1315"]["phase"] = "2C"

# Lab experiments on analogue rock (Westerly, Sierra White, gneiss) - generic rock physics, not site data.
for _i in ["1468", "1522", "1569", "1626", "1627", "1774", "1775", "1802", "1625", "1628",
           "1520", "1696", "1821", "1831", "1406", "1400", "1493", "1711", "1756", "1615",
           "1616", "1819", "1759"]:
    OVERRIDES.setdefault(_i, _o("core_lab", C, "laboratory experiment (analogue or generic rock physics), not a site observation", None, 4))

# Neighbouring Fervo sites (Cape Station, adjacent to FORGE; Project Red, Nevada).
for _i in ["1664", "1684", "1690", "1735", "1736", "1737", "1754", "1816", "1823"]:
    OVERRIDES.setdefault(_i, {"role_guess": C, "reason": "Fervo Cape Station (adjacent to FORGE) - different site; useful regional context", "priority": 4})
for _i in ["1751", "1752", "1753"]:
    OVERRIDES.setdefault(_i, {"role_guess": C, "reason": "Fervo Project Red (Nevada) - not the FORGE site", "priority": 4})


EXTRA_SOURCES: list[dict] = [
    {
        "id": "s3:gdr-data-lake/FORGE",
        "source": "oedi_s3",
        "title": "OEDI GDR data lake, prefix FORGE/ (continuous DAS, geophone, 2024 stimulation)",
        "url": "https://data.openei.org/s3_viewer?bucket=gdr-data-lake&prefix=FORGE%2F",
        "s3": ["gdr-data-lake", "FORGE/"],
        "description": "Public AWS S3 bucket (no auth). Backs GDR submissions 1680, 1725, 1824 and others: raw continuous DAS/geophone waveforms. Multi-TB; not downloaded.",
        "category": "fiber_das_dts", "role_guess": E,
        "role_reason": "raw monitoring waveforms during stimulation", "files": [],
        "phase_or_date": {"phase_reviewed": "3", "date_published": None},
        "download": "deferred (size)",
    },
    {
        "id": "ugs:mp-169",
        "source": "ugs",
        "title": "UGS Miscellaneous Publication 169: Geothermal characteristics of the Roosevelt Hot Springs system and adjacent FORGE EGS site (Allis & Moore eds., 2019)",
        "url": "https://ugspub.nr.utah.gov/publications/misc_pubs/mp-169/mp-169.pdf",
        "description": "Compendium of ~20 papers on FORGE geology, geophysics, stress, temperature; the published basis of the Phase 2 earth model.",
        "category": "reports", "role_guess": C,
        "role_reason": "peer-reviewed synthesis describing how the geologic model was built",
        "files": [{"name": "mp-169.pdf", "filename": "mp-169.pdf", "kind": "direct_file",
                   "url": "https://ugspub.nr.utah.gov/publications/misc_pubs/mp-169/mp-169.pdf",
                   "size_str": None, "size_bytes_approx": None}],
        "phase_or_date": {"phase_reviewed": "2B", "date_published": "2019"},
        "priority": 1,
    },
    {
        "id": "web:openei-wiki-utahforge",
        "source": "openei_wiki",
        "title": "OpenEI wiki Utah FORGE pages (Earth Model, Geology, Geophysics, Wells, GIS)",
        "url": "https://openei.org/wiki/Earth_Model",
        "description": "Curated index pages linked from utahforge.com/project-data-dashboard; each points back to GDR submissions. Earth Model page lists 1107, 1110, 1160, 1205, 1222, 1317, 1397, 1426, 1554, 1646, 1750, 1807, 1812.",
        "category": "reports", "role_guess": C, "role_reason": "index/documentation",
        "files": [], "phase_or_date": {"date_published": None},
    },
    {
        "id": "web:forge.geology.utah.gov",
        "source": "ugs",
        "title": "UGS Utah FORGE interactive geoscience map",
        "url": "https://forge.geology.utah.gov/",
        "description": "Web map (same as GDR 1318). No bulk download; layers mirror GDR GIS submissions.",
        "category": "maps_gis", "role_guess": I, "role_reason": "map viewer of input GIS layers",
        "files": [], "phase_or_date": {"date_published": None},
    },
]
