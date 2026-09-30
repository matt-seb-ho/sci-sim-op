#!/usr/bin/env python3
"""Extract blind-well truth for FORGE-v0 (brief phase 1, spec §8.1).

For each post-2019 well (16A(78)-32, 56-32, 78B-32, 16B(78)-32) and the input
well 58-32 (reference only), write:
  - the top of granitoid (basin fill -> granitoid contact): MD, TVD, x, y, z;
  - the most equilibrated temperature log, resampled to 10 m MD, with x, y, z
    along the trajectory;
  - whether each point falls inside the GDR 1205 grid.

Contact picks come from image-only mud logs (read by eye from rendered pages)
and text reports, so they are hand-entered below, each with its citation.
Everything else (trajectories, elevations, temperatures) is parsed from files.

Needs: numpy, pandas, openpyxl, lasio, h5py, pyproj, scipy.
Run:   python3 scripts/geomodel/extract_blind_wells.py
Out:   /data/matt/sci-sim-op/geomodel/forge/truth/blind_wells.json
"""
from __future__ import annotations

import io
import json
import math
import re
import subprocess
import zipfile
from pathlib import Path

import h5py
import lasio
import numpy as np
import openpyxl
import pandas as pd

FORGE = Path("/data/matt/sci-sim-op/geomodel/forge")
RAW = FORGE / "raw"
OUT = FORGE / "truth" / "blind_wells.json"
FT = 0.3048                      # international foot (depths, elevations)
USFT = 1200 / 3937               # US survey foot (UTM usft map coords)

# ----------------------------------------------------------------------------
# 1205 grid frame (from the header of 2019.08.21_global_cell.csv, GDR 1205
# 'Mesh Files.zip'): minimum corner 333358.2232 4262837.0922 -1500, azimuth
# 25 deg clockwise, 50 x 50 x 55 blocks of 50 m. Verified: local cell 0 centre
# (25, 25) maps to global (333391.4464, 4262849.1844), as in the file.
# ----------------------------------------------------------------------------
G_X0, G_Y0, G_Z0 = 333358.2232, 4262837.0922, -1500.0
G_AZ = math.radians(25.0)
G_LEN = (2500.0, 2500.0, 2750.0)


def to_grid_local(x, y, z):
    dx, dy = np.asarray(x) - G_X0, np.asarray(y) - G_Y0
    u = dx * math.cos(G_AZ) - dy * math.sin(G_AZ)
    v = dx * math.sin(G_AZ) + dy * math.cos(G_AZ)
    return u, v, np.asarray(z) - G_Z0


def inside_grid(x, y, z):
    u, v, w = to_grid_local(x, y, z)
    return (u >= 0) & (u <= G_LEN[0]) & (v >= 0) & (v <= G_LEN[1]) & (w >= 0) & (w <= G_LEN[2])


def _check_grid_frame():
    zf = zipfile.ZipFile(RAW / "1205" / "Mesh Files.zip")
    g = pd.read_csv(zf.open("Mesh Files/2019.08.21_global_cell.csv"), comment="#", nrows=5)
    loc = pd.read_csv(zf.open("Mesh Files/2019.08.22_local_cell.csv"), comment="#", nrows=5)
    u, v, w = to_grid_local(g.X.values, g.Y.values, g.Z.values)
    assert np.allclose(u, loc.X.values, atol=0.01) and np.allclose(v, loc.Y.values, atol=0.01), "grid frame mismatch"


# ----------------------------------------------------------------------------
# Trajectories -> DataFrame(md_ft, tvd_ft, x, y) in UTM 12N NAD83 metres.
# ----------------------------------------------------------------------------
def traj_16a():
    """1283 '16A(78)-32 Survey.xlsx' (COMPASS report; grid-north azimuths, offsets in ft
    from the wellhead). Wellhead: 'Latitude/Departure' 13987645.20 / 1097896.92 usft
    (sheet rows 57-58), which matches the Woolsey land survey of the wellhead in 1516
    'WELL 16B (78)-32 LOCATION Survey.pdf' (lat 38°30'14.44783", lon 112°53'47.06681" ->
    334639.62, 4263442.82) to 3 cm."""
    wb = openpyxl.load_workbook(RAW / "1283" / "16A(78)-32 Survey.xlsx", data_only=True)
    rows = [r for r in wb.active.iter_rows(min_row=77, values_only=True) if isinstance(r[1], (int, float))]
    x0, y0 = 1097896.92 * USFT, 13987645.20 * USFT
    df = pd.DataFrame([(r[2], r[6], r[8], r[9]) for r in rows], columns=["md", "tvd", "ns", "ew"]).astype(float)
    return pd.DataFrame({"md_ft": df.md, "tvd_ft": df.tvd, "x": x0 + df.ew * FT, "y": y0 + df.ns * FT})


def traj_16b():
    """1516 '16B(78)-32 Well Survey.zip' -> '16B(78)-32 Final Survey Report.txt' (grid north,
    UTM 12N usft, NAD83 Utah-HARN; KB 5447.65 ft, GL 5415.65 ft)."""
    zf = zipfile.ZipFile(RAW / "1516" / "16B(78)-32 Well Survey.zip")
    txt = zf.read("16B(78)-32 Final Survey Report.txt").decode("latin-1")
    rec = []
    for line in txt.splitlines():
        p = line.split()
        if len(p) == 11 and re.fullmatch(r"[\d.]+", p[0]):
            md, inc, azi, tvd, sstvd, ns, northing, ew, easting, vs, dls = map(float, p)
            rec.append((md, tvd, easting * USFT, northing * USFT))
    return pd.DataFrame(rec, columns=["md_ft", "tvd_ft", "x", "y"])


def traj_5632():
    """1295 'Well 56-32 trajectory survey data.zip' -> '56-32 well_survey_final.csv'
    (UTM_E, UTM_N in m, Depth = MD ft, Tru_Vdepth = TVD ft). Its Elev_msl_ft column
    subtracts TVD from the ground level (5451.72 ft), although the survey depths are
    from the RKB (EOWR p8: RKB 30.40 ft above GL), so elevations are recomputed here."""
    zf = zipfile.ZipFile(RAW / "1295" / "Well 56-32 trajectory survey data.zip")
    df = pd.read_csv(zf.open("56-32 well_survey_final.csv")).dropna()
    return pd.DataFrame({"md_ft": df.Depth, "tvd_ft": df.Tru_Vdepth, "x": df.UTM_E, "y": df.UTM_N})


def traj_78b():
    """1330 '78B-32 directional survey (1).zip' -> 'directional survey78B.xlsx'
    (MD, inc, azi, TVD, N-S, E-W in ft; wellhead UTM 335865.45, 4262983.529, row 4, cols O-P)."""
    zf = zipfile.ZipFile(RAW / "1330" / "78B-32 directional survey (1).zip")
    wb = openpyxl.load_workbook(io.BytesIO(zf.read("directional survey78B.xlsx")), data_only=True)
    rec = [(r[2], r[5], r[6], r[7]) for r in wb.active.iter_rows(min_row=3, values_only=True)
           if isinstance(r[2], (int, float))]
    df = pd.DataFrame(rec, columns=["md", "tvd", "ns", "ew"]).astype(float)
    x0, y0 = 335865.45, 4262983.529
    return pd.DataFrame({"md_ft": df.md, "tvd_ft": df.tvd, "x": x0 + df.ew * FT, "y": y0 + df.ns * FT})


def traj_5832():
    """1006 '58-32_EOWR.zip' -> 'DirectionalSurveyRpt_All.pdf' (GRG report, MD/TVD/N-S/E-W ft).
    Wellhead from 1268 'FORGE_WellHeads_GPS.xlsx', 'final positions' table."""
    zf = zipfile.ZipFile(RAW / "1006" / "58-32_EOWR.zip")
    pdf = zf.read("58-32_EOWR/DirectionalSurveyRpt_All.pdf")
    txt = subprocess.run(["pdftotext", "-layout", "-", "-"], input=pdf, capture_output=True).stdout.decode()
    rec = [(0.0, 0.0, 0.0, 0.0)]
    for line in txt.splitlines():
        m = re.match(r"\s+(MSS|MMS|MWD|GYRO|Gyro)\s+([\d,.]+)\s+[\d.]+\s+[\d.]+\s+([\d,.]+)\s+(-?[\d,.]+)\s+(-?[\d,.]+)", line)
        if m:
            rec.append(tuple(float(g.replace(",", "")) for g in m.groups()[1:]))
    df = pd.DataFrame(rec, columns=["md", "tvd", "ns", "ew"]).drop_duplicates("md").sort_values("md")
    x0, y0 = 335451.38025, 4263037.084
    return pd.DataFrame({"md_ft": df.md, "tvd_ft": df.tvd, "x": x0 + df.ew * FT, "y": y0 + df.ns * FT})


def along(traj, md_ft):
    """Interpolate TVD, x, y at md_ft; below the last survey station, extend along the
    direction of the last survey segment (np.interp alone would clamp TVD)."""
    md_ft = np.asarray(md_ft, float)
    m, cols = traj.md_ft.values, [traj.tvd_ft.values, traj.x.values, traj.y.values]
    out = []
    for c in cols:
        v = np.interp(md_ft, m, c)
        below = md_ft > m[-1]
        if below.any():
            slope = (c[-1] - c[-2]) / (m[-1] - m[-2])
            v[below] = c[-1] + slope * (md_ft[below] - m[-1])
        out.append(v)
    return tuple(out)


# ----------------------------------------------------------------------------
# Temperature logs -> (md_ft, T_degF, meta)
# ----------------------------------------------------------------------------
def _las_from_zip(zpath, member, curve):
    zf = zipfile.ZipFile(zpath)
    las = lasio.read(io.StringIO(zf.read(member).decode("latin-1")))
    d = las.df().reset_index()
    d = d[[d.columns[0], curve]].dropna()
    return d.iloc[:, 0].values.astype(float), d[curve].values.astype(float)


def temp_16a():
    md, t = _las_from_zip(RAW / "1292" / "16A(78)_32 CBL Wireline.zip",
                          "UniversityofUtah_Forge_16A-78-32_Trip7_CBL_Main_16Aug21_LAS.las", "MTEM")
    return md, t, {
        "date": "2021-08-16",
        "source": "GDR 1292 '16A(78)_32 CBL Wireline.zip' -> 'UniversityofUtah_Forge_16A-78-32_Trip7_CBL_Main_16Aug21_LAS.las', curve MTEM (degF), 81.5-10740 ft",
        "confidence": "high",
        "equilibration_note": "~216 days after rig release (1/12/21), per GDR 1421 'Data Summary' row 11 and sheet '16A(78)-32_2nd'. Most equilibrated of the two 16A logs; the other (2021-03-01, ~57 d) did not reach TD.",
        "depth_reference": "LAS LMF=KB, APD 32 ft above GL 5403.5 ft (wireline header). The drilling survey uses RKB 30 ft above GL 5414 ft; MD taken as equivalent (datum difference < 3 m).",
    }


def temp_5632():
    md, t = _las_from_zip(RAW / "1295" / "56-32 Cement Bond.zip",
                          "UniversityofUtah_Forge56-32_MonitorWell_CBL_Main_17Aug21_LAS.las", "MTEM")
    return md, t, {
        "date": "2021-08-17",
        "source": "GDR 1295 '56-32 Cement Bond.zip' -> 'UniversityofUtah_Forge56-32_MonitorWell_CBL_Main_17Aug21_LAS.las', curve MTEM (degF), 60-9111 ft",
        "confidence": "high",
        "equilibration_note": "~162 days of recovery, per GDR 1421 'Data Summary' row 9. Alternative: DiDrill memory PT log 2021-06-29 (112 d), GDR 1326 '56-32_TP.zip'.",
        "depth_reference": "LAS LMF=KB, APD 30 ft above GL 5452 ft (EOWR: RKB 30.40 ft, GL 5451.71 ft).",
    }


def temp_78b():
    md, t = _las_from_zip(RAW / "1330" / "78B-32_CBL_LOG.zip",
                          "7.0-inch casing cement bond log data/UniversityofUtah_Forge78B-32_6Oct21_CBL_Main_REV1.las", "MTEM")
    return md, t, {
        "date": "2021-10-06",
        "source": "GDR 1330 '78B-32_CBL_LOG.zip' -> 'UniversityofUtah_Forge78B-32_6Oct21_CBL_Main_REV1.las', curve MTEM (degF), 103-8504 ft (tool did not reach TD 9500 ft)",
        "confidence": "medium (67 d recovery; deeper part may still be below equilibrium)",
        "equilibration_note": "67 days after rig release (7/31/21), per GDR 1421 'Data Summary' row 12. The only other log (1330 'UOU_FORGE-78B-32_Temperature_Log_22Jul21_.Pdf') was run during drilling.",
        "depth_reference": "LAS LMF=KB, APD 29.5 ft above GL (header says GL 5536 ft; see wellhead note: that GL is probably wrong).",
    }


def temp_5832():
    md, t = _las_from_zip(RAW / "1326" / "58-32_PT.zip", "UOFU_58-32_PT.las", "TEMP")
    # logged from ground level -> convert to RKB MD (KB 21.5 ft above GL, EOWR p5/p11)
    return md + 21.5, t, {
        "date": "2021-06-28",
        "source": "GDR 1326 '58-32_PT.zip' -> 'UOFU_58-32_PT.las' (DiDrill), curve TEMP (degF), 0-7510 ft below GL",
        "confidence": "high",
        "equilibration_note": "1371 days after last circulation (GDR 1421 'Data Summary' row 5). Note the April-May 2019 58-32 stimulations cooled the open hole near TD; 2 years of recovery since. Pre-2019 log (2017-11-02, 37 d) is in GDR 1006/1421.",
        "depth_reference": "LAS 'LOG WAS MEASURED FROM GROUND LEVEL'; converted to RKB MD by adding 21.5 ft.",
    }


def temp_16b():
    path = RAW / "1826" / "Utah Forge 16B(78)-32 - DTS calibrated - evo 5.h5"
    with h5py.File(path, "r") as f:
        md = f["depth"][:].astype(float)
        t = f["data"][0, :].astype(float)
        stamp = f["stamps"][0].decode()
    ok = (md > 0) & (md <= 10080) & np.isfinite(t)   # fibre ends at ~10090 ft: T drops from 437 F to ~92 F within 30 ft
    return md[ok], t[ok], {
        "date": "{2}-{0}-{1}".format(*stamp[:10].split("/")),
        "source": f"GDR 1826 '{path.name}', dataset 'data' row 0 (first frame, {stamp} UTC), 'depth' (ft)",
        "equilibration_note": ("First frame of the Aug-2025 circulation-test DTS, i.e. the shut-in baseline before circulation started. "
                               "No pre-stimulation equilibrated log of 16B is in the local data (16B was drilled Apr-Jun 2023 and circulated Jul 2023; "
                               "16A/16B stimulated Apr 2024). The profile is therefore post-stimulation and may be cooled near the stimulated interval. "
                               "It reads 6-15 C warmer than 16A at the same TVD (1-2.3 km), possibly warm-biased by earlier production from 16B. "
                               "Lower confidence than the other wells: use with care in scoring."),
        "confidence": "low",
        "depth_reference": "fibre depth, taken as MD from KB (not verified against a depth-correlation log; could be off by tens of ft).",
    }


# ----------------------------------------------------------------------------
# Wellheads (UTM 12N NAD83 m, NAVD88 m) and contact picks (MD ft from RKB)
# ----------------------------------------------------------------------------
WELLS = {
    "16A(78)-32": dict(
        traj=traj_16a, temp=temp_16a, blind=True,
        wellhead=dict(
            gl_ft=5414.0, kb_ft=5444.0,
            source=("GL 5414 ft and KB 5444 ft (RKB 30 ft): 1283 '16A(78)-32 Survey.xlsx' rows 51-53 and 1296 'Drilling Summary' p7. "
                    "Wellhead x,y from the survey header (usft), confirmed by the Woolsey wellhead survey in 1516 'WELL 16B (78)-32 LOCATION Survey.pdf' "
                    "(top of steel 5420.37 ft NAVD88). GDR 1216 'planned' wellhead (4263458.9 N) is 16 m north of the actual one: not used.")),
        pick=dict(md_ft=4520.0, rule="final mud log: first depth where granitoid is the logged lithology", sources=[
            dict(file="GDR 1292 '16A(78)-32 Mud Log Final 130-10987_.pdf'", page_or_row="p1, lithology track at ~4510-4525 ft (image-only; read from render at 100 dpi, +/-10 ft)",
                 value_md_ft=4520.0, note="Green 'granitic wash / reworked granite' (basin fill) to ~4510 ft; thin black rhyolite ~4510-4520 ft; red-hatched granite from ~4520 ft. Description column: 'GRANITE: MED DRK GRY IN BULK' starting just below 'RHYOLITE' after survey 4457 ft."),
            dict(file="GDR 1283 'Composite-C (1).pdf' (daily reports)", page_or_row="p6",
                 value_md_ft=4441.0, note="'Drilling break at 4,441' ... Weathered granite'; 'Lithology at 4,460: Granite / Granodiorite'. The mud log calls 4440-4465 'reworked granite' (basin fill)."),
            dict(file="GDR 1296 'Drilling Summary Well 16A(78)-32.pdf'", page_or_row="p28 (also p15)",
                 value_md_ft=4552.0, note="'The granite contact is at 4552+/- ft MD/TVD'. 4552 ft is also the end of BHA 04, which 'drilled just past the approximate top of the granite' (p15)."),
        ])),
    "56-32": dict(
        traj=traj_5632, temp=temp_5632, blind=True,
        wellhead=dict(
            gl_ft=5451.71, kb_ft=5482.11,
            source="1295 '56-32 EOWR - Final 22 July 2021.pdf' p15 (GL 5,451.71 ft ASL, rotary table 5,482.11 ft ASL, RKB 30.40 ft); x,y from '56-32 well_survey_final.csv' row 1 (readme: 5451.72 ft, 335505.75, 4263426.35)."),
        pick=dict(md_ft=3180.0, rule="mud logger: first interval where granite is the dominant (>=50%) lithology", sources=[
            dict(file="GDR 1295 '56-32 Daily Mud Logs.zip' -> 'FORGE 56-32 Morning Report 2-11-21.pdf'", page_or_row="p1, Lithology table",
                 value_md_ft=3180.0, note="3050-3180 '40-80% Clay, 10-60% Alluvium, 0-40% Granite'; 3180-3230 '50-80% Granite, 20-50% Clay'; 3230-3270 '100% Granite'."),
            dict(file="GDR 1295 'University of Utah FORGE 56-32 Final Compiled Log.pdf'", page_or_row="p1 (single strip), lithology track ~3050-3230 ft (image-only; read from render, +/-10 ft)",
                 value_md_ft=3125.0, note="Alluvium to 3050 ft, clay 3050-~3125 ft, granite first logged ~3125 ft, mixed with clay to ~3230 ft; description 'Granite: wht,lt gry,mod hd-hd ...' at ~3140 ft."),
            dict(file="GDR 1295 '56-32 EOWR - Final 22 July 2021.pdf'", page_or_row="p8 (Summary)",
                 value_md_ft=3110.0, note="'encountered the top of the granite at about 3,110 ft'."),
            dict(file="GDR 1295 '56-32 Daily Drilling Reports.zip' -> 'DailyReportDetailRpt_210210081912.pdf'", page_or_row="p1",
                 value_md_ft=3240.0, note="'Clay has cleaned up and hit the top of the granite at around 3,240''. Matches the mud logger's 100% granite at 3230 ft."),
        ])),
    "78B-32": dict(
        traj=traj_78b, temp=temp_78b, blind=True,
        wellhead=dict(
            gl_ft=1704.5 / FT, kb_ft=1704.5 / FT + 30.4,
            source=("x,y: 1330 'directional survey78B.xlsx' row 4 (Well Head NAD83 UTM 335865.45, 4262983.529). "
                    "GL: the EOWR (p16) and CBL header give 5,536 ft ASL, but that is 58-32's EOWR value and ~56 ft below the terrain here; "
                    "the 10 m DEM in GDR 1107 'land_surface_vertices.csv' gives 1704.5 m (5592 ft) at the wellhead, and 78-32 85 m west is 1701.9 m by GPS (1268). "
                    "Using GL = 1704.5 m (DEM) and RKB 30.40 ft (EOWR p8). The 78B mud-log header coordinates (335450, 4263043) are 58-32's and were ignored.")),
        pick=dict(md_ft=2700.0, rule="final mud log: first depth where granite is the dominant (>=50%) lithology", sources=[
            dict(file="GDR 1330 '78B-32 Mud Log.pdf'", page_or_row="p9, lithology track 2640-2700 ft (image-only; read from render at 110 dpi, +/-10 ft)",
                 value_md_ft=2700.0, note="Rhyolite (p8-9) from ~2410 ft, granite appears ~2640 ft as a minor fraction, 100% granite from 2700 ft ('Granite: wht/beige-dk gry ...')."),
            dict(file="GDR 1330 '78B-32 EOWR with appendices.zip' -> '78B-32 EOWR with ref appendices.pdf'", page_or_row="p8 (Summary)",
                 value_md_ft=2700.0, note="'encountered the top of the granite at about 2,700 ft'."),
            dict(file="GDR 1330 '78B-32 EOWR with appendices.zip' -> '78B-32 EOWR Appendices to attach.pdf'", page_or_row="p223-225 (mud logger morning reports)",
                 value_md_ft=2650.0, note="'2630-2650 100% Alluvium; 2650-2670 10-50% Rhyolite 50-90% Granite; 2670-2700 100% Granite'. An earlier report (p226) logged 2430-2690 as rhyolite with 20-30% granite from 2640 ft."),
        ])),
    "16B(78)-32": dict(
        traj=traj_16b, temp=temp_16b, blind=True,
        wellhead=dict(
            gl_ft=5415.65, kb_ft=5447.65,
            source="1516 '16B(78)-32 Well Survey.zip' -> '16B(78)-32 Final Survey Report.txt' header (KB 5447.65 ft, GL 5415.65 ft, wellhead 1097907.09 E / 13987765.96 N usft); mud log header (Exlog, 16B Mud Logs.zip) GL 5416.65, KB 5424.65 (typo)."),
        pick=dict(md_ft=4390.0, rule="cuttings photo log: first sample logged as granite (samples every 30 ft)", sources=[
            dict(file="GDR 1516 '16B Mud Logs.zip' -> 'Utah Forge PHOTO LOG_6_18_23.pdf'", page_or_row="p15-16",
                 value_md_ft=4390.0, note="4270 'ALLUVIUM'; 4330 and 4360 'GRANITE WASH'; 4390 'GRANITE: MED - DRK GRY IN BULK ... TR RHY'. Contact lies between 4360 and 4390 ft."),
            dict(file="GDR 1516 '16B Daily Reports.zip' -> '20230501-DailyReport15DetailRpt_230501064742.pdf'", page_or_row="p1 (also EOWR 'End of Well Report-16B78-32-May_2024.pdf' p211)",
                 value_md_ft=4330.0, note="'Formation changed to granite wash around 4,330''. Granite wash is basin fill, so this is an upper bound on the contact."),
            dict(file="GDR 1516 '16B Mud Logs.zip' -> 'Frontier_16-16B(78)-32(Frontier_16-16B(78)-32) 6-20-23.pdf'", page_or_row="p20-21 (image-only)",
                 value_md_ft=None, note="Granite-wash pattern from ~4270 ft (p20); crystalline patterns throughout the next visible interval (4435-4600 ft, p21), solid granite from ~4555 ft. The 4360-4435 ft interval is not on either page."),
        ])),
    "58-32": dict(
        traj=traj_5832, temp=temp_5832, blind=False,
        wellhead=dict(
            gl_ft=1684.80118 / FT, kb_ft=1684.80118 / FT + 21.5,
            source=("1268 'Updated Utah FORGE Phase 2C Well Locations.zip' -> 'FORGE_WellHeads_GPS.xlsx', 'final positions' (335451.38, 4263037.084, 1684.801 m NAVD88 geoid12A). "
                    "RKB 21.5 ft above GL (1006 EOWR p5, p11). The EOWR's GL of 5,536 ft ASL is 8 ft above the GPS value; GPS used.")),
        pick=dict(md_ft=3175.0, rule="final mud log: first depth where granite is the logged lithology", sources=[
            dict(file="GDR 1006 '58-32_EOWR.zip' -> '58-32_EOWR/FinalMudLog.pdf'", page_or_row="p1 (single strip), lithology track 3150-3200 ft (image-only; read from render at 110 dpi, +/-10 ft)",
                 value_md_ft=3175.0, note="Alluvium to ~3168 ft, granite from ~3175 ft ('Granite: wht,gry,tan,mod hd-hd ...'), granodiorite from ~3300 ft."),
            dict(file="GDR 1006 '58-32_EOWR.zip' -> '58-32_EOWR/58-32_EOWR_DOE.pdf'", page_or_row="p5",
                 value_md_ft=3200.0, note="'encountered the top of the granite at about 3200 ft. (975 m)'."),
            dict(file="GDR 1006 '58-32_EOWR.zip' -> '58-32_EOWR/Geology Morning Reports.pdf'", page_or_row="p1 (8/13/2017 report) and later",
                 value_md_ft=2150.0, superseded=True, note="Morning reports log '2080-2150 mixed Granite and Alluvium; 2150-3330 Granite'. Superseded by the final mud log, which calls 2150-3168 ft alluvium; recorded for completeness, not used."),
        ])),
}


def build():
    _check_grid_frame()
    out = {
        "schema": "blind_wells v1 (session 2, 2026-09-30)",
        "crs": {"xy": "UTM zone 12N, NAD83, metres (EPSG:26912)", "z": "elevation, NAVD88, metres (up positive)",
                "md_tvd": "metres along hole / vertical below the drilling rig datum (RKB) given per well as md_datum",
                "T": "degrees Celsius"},
        "grid_1205": {"origin_min_corner": [G_X0, G_Y0, G_Z0], "azimuth_deg_clockwise": 25.0, "extent_m": list(G_LEN),
                      "source": "GDR 1205 'Mesh Files.zip' -> 2019.08.21_global_cell.csv header; checked against 2019.08.22_local_cell.csv"},
        "pick_convention": ("granitoid_top = basin fill -> granitoid (granite/granodiorite, incl. rhyolite dykes within it) contact, from cuttings. "
                            "'Granite wash', 'reworked granite' and weathered-granite sand are basin fill. MD are from each well's RKB."),
        "wells": {}, "reference_wells": {},
        "generated_by": "scripts/geomodel/extract_blind_wells.py",
    }
    for name, w in WELLS.items():
        traj = w["traj"]()
        wh = w["wellhead"]
        kb_m = wh["kb_ft"] * FT
        rec = {"wellhead": {"x": float(traj.x.iloc[0]), "y": float(traj.y.iloc[0]), "ground_elev_m": round(wh["gl_ft"] * FT, 2),
                            "kb_elev_m": round(kb_m, 2), "source": wh["source"]},
               "trajectory": {"md_m": list(np.round(traj.md_ft.values * FT, 2)), "tvd_m": list(np.round(traj.tvd_ft.values * FT, 2)),
                              "x": list(np.round(traj.x.values, 2)), "y": list(np.round(traj.y.values, 2))}}
        p = w["pick"]
        tvd, x, y = along(traj, p["md_ft"])
        z = kb_m - tvd * FT
        vals = [s["value_md_ft"] for s in p["sources"] if s["value_md_ft"] is not None and not s.get("superseded")]
        spread_m = (max(vals) - min(vals)) * FT
        rec["granitoid_top"] = {
            "md_m": round(p["md_ft"] * FT, 1), "md_ft": p["md_ft"], "md_datum": f"RKB ({kb_m:.1f} m NAVD88)",
            "tvd_m": round(float(tvd) * FT, 1), "x": round(float(x), 1), "y": round(float(y), 1), "z_elev_m": round(float(z), 1),
            "depth_below_ground_m": round(float(tvd) * FT - (wh["kb_ft"] - wh["gl_ft"]) * FT, 1),
            "pick_rule": p["rule"], "sources": p["sources"],
            "source_range_md_ft": [min(vals), max(vals)], "spread_excludes": "sources marked superseded", "source_spread_m": round(spread_m, 1),
            "disagreement_flag": bool(spread_m > 10.0),
            "inside_1205_grid": bool(inside_grid(x, y, z)),
            "grid_local_uvw_m": [round(float(a), 1) for a in to_grid_local(x, y, z)],
        }
        md_ft, t_f, meta = w["temp"]()
        order = np.argsort(md_ft)
        md_ft, t_f = md_ft[order], t_f[order]
        md_m = md_ft * FT
        grid = np.arange(math.ceil(md_m.min() / 10) * 10, md_m.max(), 10.0)
        t_c = (np.interp(grid, md_m, t_f) - 32) / 1.8
        tvd_ft, xs, ys = along(traj, grid / FT)
        zs = kb_m - tvd_ft * FT
        ins = inside_grid(xs, ys, zs)
        rec["temperature"] = {**meta, "resampled": "linear interpolation at 10 m MD steps",
                              "md_m": list(np.round(grid, 1)), "tvd_m": list(np.round(tvd_ft * FT, 1)),
                              "z_elev_m": list(np.round(zs, 1)), "x": list(np.round(xs, 1)), "y": list(np.round(ys, 1)),
                              "T_C": list(np.round(t_c, 2)), "inside_1205_grid": [bool(b) for b in ins],
                              "fraction_inside_1205_grid": round(float(ins.mean()), 3),
                              "traj_extrapolated_below_md_m": round(float(traj.md_ft.max() * FT), 1)}
        (out["wells"] if w["blind"] else out["reference_wells"])[name] = rec
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, default=float))
    return out


if __name__ == "__main__":
    o = build()
    for grp in ("wells", "reference_wells"):
        for n, r in o[grp].items():
            g, t = r["granitoid_top"], r["temperature"]
            print(f"{n:11s} top MD {g['md_m']:7.1f} m TVD {g['tvd_m']:7.1f} z {g['z_elev_m']:7.1f} "
                  f"({g['x']:.0f},{g['y']:.0f}) spread {g['source_spread_m']:5.1f} m flag={g['disagreement_flag']} in1205={g['inside_1205_grid']} "
                  f"| T {t['date']} n={len(t['T_C'])} Tmax {max(t['T_C']):.1f}C in1205 {t['fraction_inside_1205_grid']:.2f}")
