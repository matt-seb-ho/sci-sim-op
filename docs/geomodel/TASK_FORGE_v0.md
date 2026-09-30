# Task FORGE-v0: rebuild the 2019 Utah FORGE earth model

**Status:** draft for Sherman's review (next meeting). **Written:** 2026-09-23.
Built on [`WHAT_IS_A_GEOLOGICAL_MODEL.md`](WHAT_IS_A_GEOLOGICAL_MODEL.md) and [`FORGE_DATA_INVENTORY.md`](FORGE_DATA_INVENTORY.md).

---

## 1. The task in one paragraph

> *It is August 2019. You are the modeler on the Utah FORGE team. Here is every public
> dataset about the site published so far. Build the earth model of the reservoir volume
> that the team will simulate: which rock is where, the temperature, pressure and stress
> before anything is injected, and the rock properties. Document where every number came
> from.*

The expert team did exactly this in mid-2019 and published the result as **GDR 1205**.
The wells drilled *after* that (16A in 2020–21, 56-32 in 2021, 78B-32 in 2021) show
what was actually down there. So we have both an **expert answer** and **blind wells**
to check against.

## 2. Why this version first

- **FORGE is the "case 1" site:** two rock units (granite basement under basin-fill
  sediment) plus fractures. Hard enough to be real, simple enough to score.
- **A clean time cut exists.** The model was built 2019-06 to 2019-08. Nothing about the
  stimulations existed yet, so no evaluation data can leak into the inputs.
- **No GEOS runs are needed to score v0.** Blind wells give a reality check for free.
  GEOS forward runs are v1.

## 3. The partition

| bucket | what | GDR ids (examples) | rule |
|---|---|---|---|
| **Inputs** (agent sees) | regional geology maps, faults, lineaments; gravity, MT, seismic reflection (2D/3D); old regional wells (9-1, 14-2, 52-21, 82-33, Acord-1); **well 58-32** logs, core, FMI, P-T logs; 58-32 injection/stress tests; temperature gradient and heat-flow data; earthquake catalogs; LiDAR/DEM | 701, 705–709, 711–714, 717, 1002, 1006, 1007, 1015, 1034, 1076, 1101, 1109, 1146, 1149 … | `role=input` **and** published before **2019-09-01**: 58 submissions |
| **Expert answer** (hidden, scored against) | **2019 Phase 2C block model:** 137,500 cells of 50 m, each labelled granitoid or basin fill; T, P and stress on nodes | **1205** (primary), 1315 + 1160 (INL native-state inputs and outputs: properties and state on the same mesh) | the model built from exactly these inputs |
| **Prior model** (withheld in variant A, given in B) | **Phase 2B** surfaces: granitoid top, Opal Mound and Negro Mag faults, isotherms | 1107, 1108 | Dec 2018, the previous version |
| **Blind wells** (hidden, scored against) | depth of the granite contact and temperature logs in wells drilled after the cut | 1292/1283 (16A), 1295 (56-32), 1330 (78B-32), 1326, 1421 (T logs) | drilled after 2019-09 |
| **Later expert versions** (hidden, for calibration) | 2022 and 2025 native-state models; 2020–2025 DFNs | 1397, 1812, 1222, 1317, 1646, 1750 | shows how much the *experts'* own model moved |
| **Excluded** | everything about the 2022/2024 stimulations (pressure, microseismicity, fiber, tracers) | 1379, 1399, 1429, 1611, … | saved for v1 (GEOS forward prediction) |
| **Excluded** | write-ups of the answer: UGS report MP-169 (2019), papers describing the Phase 2 model | — | they *are* the answer, in prose |

**Two variants** (the same scoring for both):
- **A, from scratch:** the inputs only.
- **B, update:** the inputs plus the Phase 2B model, with the data that arrived after
  Dec 2018 flagged as "new". This is Sherman's *"new data arrived, update the model"*
  task, and it is our continual-learning instance.

## 4. What the agent must produce

The agent gets the **grid definition**: the cell centres and nodes of the 1205 mesh with
the labels removed. Choosing the domain is a modelling decision; it is fixed in v0 and
freed in v1. The agent writes:

| file | content | scored against |
|---|---|---|
| `lithology.csv` | `cell_id, unit` ∈ {granitoid, basin_fill} | 1205 cell labels |
| `granitoid_top.csv` | depth of the granite contact on a 50 m map grid | 1107/1205 contact; blind wells |
| `initial_state.csv` | per node: `T_C, P_MPa, Sv_MPa, SHmax_MPa, Shmin_MPa` | 1205 IC / 1160 |
| `state.json` | SHmax azimuth, gradients, stress regime | 1205, literature |
| `properties.json` | per unit: permeability, porosity, E, ν, density, thermal conductivity, as a value plus a plausible range | 1315 FALCON inputs |
| `MODEL_REPORT.md` | every value → the source file(s) and the reasoning; key assumptions; uncertainties | Sherman |
| `fractures.json` (*optional in v0*) | fracture sets: orientation, intensity, size distribution | 1222 DFN statistics |

## 5. Scoring

| axis | metric | notes |
|---|---|---|
| **A. vs expert model** | lithology: balanced accuracy over cells, and contact-depth RMSE (m); state: RMSE per field (T, P, three stresses) and SHmax azimuth error (°); properties: log₁₀ k error, relative error for the rest | dense and cheap; the signal self-evolution can use |
| **B. blind wells** | error in predicted granite-contact depth at 16A, 56-32, 78B-32; temperature RMSE along their logs | **reality, not an expert's opinion.** Score the expert model the same way |
| **C. expert review** | Sherman grades `MODEL_REPORT.md` and the model: accept / minor fixes / reject, plus the first thing that is wrong | ~1 h per model; a small sample only |

**Anchors for reading a score:**
- **Floor:** a naive model (flat contact at the 58-32 depth, linear gradients from 58-32 only).
- **Ceiling:** the 2019 expert model's own error on the blind wells.
- **Tolerance:** how far the experts' model moved between 2019 and 2025 (1205 → 1812).
  An agent that lands within the experts' own revision distance is doing expert-level work.

## 6. Agent environment

- **Offline and sandboxed** (bubblewrap, no network). This mirrors LLNL's Blackhole setup
  and stops the agent from looking up the answer.
- Inputs mounted read-only at `/site/`, laid out as the GDR submissions, raw. Finding
  what's relevant among ~58 submissions is part of the task.
- Python with numpy, scipy, pandas, lasio (LAS logs), dlisio (DLIS logs), shapely,
  pyvista, and optionally GemPy.
- **Contamination probe (run first):** ask the model what it knows about FORGE geology
  with no data (contact depth, gradients, stress). Score that answer the same way. The
  agent's gain over its own prior is what we report.

## 7. Known weaknesses of v0 (say them before a reviewer does)

- **The expert answer is thin:** two units, with no faults inside the block and stress as
  gradients. Axis A may saturate. That is acceptable for case 1; San Emidio is the hard case.
- **Giving the grid leaks one decision:** its 25° rotation is aligned with the stress
  direction.
- **n = 1 site.** Report per-run results with repeated seeds, not a benchmark mean.
- **The blind-well "truth" has to be extracted from drilling reports and logs.** Not
  done yet; this is the next step.

## 8. Next steps

**Status 2026-09-30 (session 2):** steps 1–4 done; see
[`sessions/2026-09-30_session2_report.md`](sessions/2026-09-30_session2_report.md). Step 5 is open.

1. ✅ **Extract blind-well truth:** granite-contact depths and temperature logs for 16A,
   56-32 and 78B-32 from 1283/1292/1295/1330/1326/1421.
2. ✅ **Build `/site/`** from the manifest: the date filter, role filter and exclusions
   above, plus a leak scan for strings from 1205 and MP-169.
3. ✅ **Write the scorer** (axes A and B), and score the naive baseline and the expert model
   first, so the scale is anchored before any agent runs.
4. ✅ **One pilot agent run** (variant A), read end to end, before any method work.
5. **Take §3 and §5 to Sherman** with the questions below.

## 9. Questions for Sherman

1. Is 1205 + 1160/1315 "the geological model" in his sense, or would he call the
   simulation-ready native-state model (1397/1812) the real artifact?
2. Would a modeler in 2019 really have had the Phase 2B model? That decides whether
   variant B is the realistic default.
3. Is the blind-well contact depth a fair reality check, or is it too easy at FORGE?
4. Should v0 include the DFN, or leave fractures to a v1 that uses GEOS?
5. For v1, which forward prediction would he trust most: 58-32 injection pressure, 2022
   Stage 3 pressure, or the extent of the microseismic cloud?
