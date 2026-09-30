"""Held-out truth for FORGE-v0: build it from the raw GDR files, and load it.

Truth directory (default /data/matt/sci-sim-op/geomodel/forge/truth/):

  lithology.csv       cell_id,unit                      GDR 1205 cell labels
  state_1205ic.csv    node_id,T_C,P_MPa,Sv_MPa,SHmax_MPa,Shmin_MPa,depth_m
                                                         GDR 1205 IC (Leapfrog export)
  state_1160.csv      node_id,T_C,P_MPa,Sv_MPa,SHmax_MPa,Shmin_MPa
                                                         GDR 1160 FALCON native state
  summary.json        SHmax azimuth, regime, gradients, unit properties (+ provenance)
  blind_wells.json    blind-well contacts and temperature logs (Phase 1)

Building needs openpyxl (the IC is an .xlsx); loading needs only the stdlib.
"""
from __future__ import annotations

import csv
import json
import math
import statistics
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .grid import FORGE_1205, Lattice

FIELDS = ("T_C", "P_MPa", "Sv_MPa", "SHmax_MPa", "Shmin_MPa")
UNITS = ("granitoid", "basin_fill")
PROPS = ("permeability_m2", "porosity", "youngs_modulus_GPa", "poissons_ratio",
         "density_kg_m3", "thermal_conductivity_W_mK")
DEFAULT_TRUTH = Path("/data/matt/sci-sim-op/geomodel/forge/truth")
RAW = Path("/data/matt/sci-sim-op/geomodel/forge/raw")


@dataclass
class Truth:
    lattice: Lattice
    lithology: list            # index = cell_id -> unit str
    states: dict               # name -> {field: list indexed by node_id}
    depth_m: list              # node depth below ground (from the 1205 IC)
    summary: dict
    wells: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- load
def load_truth(root: str | Path = DEFAULT_TRUTH, lattice: Lattice | None = None) -> Truth:
    """Load a truth directory. The lattice comes from ``grid.json`` if present."""
    root = Path(root)
    if lattice is None:
        g = root / "grid.json"
        lattice = Lattice(**json.loads(g.read_text())) if g.exists() else FORGE_1205
    lith = [None] * lattice.n_cells
    with open(root / "lithology.csv", newline="") as f:
        for r in csv.DictReader(f):
            lith[int(r["cell_id"])] = r["unit"]
    states, depth = {}, [None] * lattice.n_nodes
    for name, fn in (("1205ic", "state_1205ic.csv"), ("1160", "state_1160.csv")):
        p = root / fn
        if not p.exists():
            continue
        cols = {k: [None] * lattice.n_nodes for k in FIELDS}
        with open(p, newline="") as f:
            for r in csv.DictReader(f):
                nid = int(r["node_id"])
                for k in FIELDS:
                    cols[k][nid] = float(r[k])
                if name == "1205ic":
                    depth[nid] = float(r["depth_m"])
        states[name] = cols
    summary = json.loads((root / "summary.json").read_text())
    wells = {}
    if (root / "blind_wells.json").exists():
        wells = json.loads((root / "blind_wells.json").read_text())
    return Truth(lattice, lith, states, depth, summary, wells)


# -------------------------------------------------------------------------- build
def _read_leapfrog_csv(fobj):
    lines = (ln.decode("utf-8-sig") if isinstance(ln, bytes) else ln for ln in fobj)
    return csv.reader(ln for ln in lines if not ln.startswith("#"))


def _linfit(xs, ys):
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    b = sxy / sxx
    return b, my - b * mx


def build_truth(out: str | Path = DEFAULT_TRUTH, raw: Path = RAW, lattice: Lattice = FORGE_1205) -> dict:
    """Write lithology.csv, state_1205ic.csv, state_1160.csv, summary.json."""
    import io
    import openpyxl  # build-time only

    import dataclasses
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "grid.json").write_text(json.dumps(dataclasses.asdict(lattice), indent=1))
    prov = {}

    # 1. lithology (1205 Mesh Files.zip -> 2019.08.21_global_cell.csv)
    with zipfile.ZipFile(raw / "1205" / "Mesh Files.zip") as z:
        name = "Mesh Files/2019.08.21_global_cell.csv"
        with z.open(name) as f:
            rd = _read_leapfrog_csv(io.TextIOWrapper(f, "utf-8"))
            hdr = next(rd)
            lab = hdr.index("GM_8_19_2019")
            rows = []
            for r in rd:
                if not r or not r[0].strip():
                    continue
                cid = int(r[0])
                x, y, zc = float(r[1]), float(r[2]), float(r[3])
                gx, gy, gz = lattice.cell_xyz(cid)
                assert abs(gx - x) < 0.05 and abs(gy - y) < 0.05 and abs(gz - zc) < 0.05, (cid, x, y, zc)
                unit = {"Granitiod": "granitoid", "Basin Fill": "basin_fill"}[r[lab].strip()]
                rows.append((cid, unit))
    assert len(rows) == lattice.n_cells
    with open(out / "lithology.csv", "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["cell_id", "unit"])
        w.writerows(sorted(rows))
    prov["lithology"] = f"raw/1205/Mesh Files.zip::{name} column GM_8_19_2019"

    # 2. 1205 IC (xlsx; cached formula values)
    with zipfile.ZipFile(raw / "1205" / "Initial Conditions.zip") as z:
        data = z.read("IC/2019.06.10_IC_local_node_v2.xlsx")
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    ws = wb.worksheets[0]
    it = ws.iter_rows(values_only=True)
    for row in it:
        if row[0] == "Id":
            hdr = list(row)
            break
    ix = {k: hdr.index(k) for k in ("Id", "X", "Y", "Z", "pressure", "temperature", "depth",
                                     "disp_k_bc", "disp_j_bc", "disp_i_bc")}
    ic = {}
    for row in it:
        if row[0] is None:
            continue
        nid = int(row[ix["Id"]])
        # local frame: X,Y are metres along the rotated axes from node 0
        i, j = round(row[ix["X"]] / lattice.spacing), round(row[ix["Y"]] / lattice.spacing)
        k = round((row[ix["Z"]] - lattice.z0) / lattice.spacing)
        assert nid == i + lattice.ni * (j + lattice.nj * k), (nid, i, j, k)
        ic[nid] = (row[ix["temperature"]] - 273.15, row[ix["pressure"]] / 1e6,
                   -row[ix["disp_k_bc"]] / 1e6, -row[ix["disp_j_bc"]] / 1e6,
                   -row[ix["disp_i_bc"]] / 1e6, float(row[ix["depth"]]))
    assert len(ic) == lattice.n_nodes, len(ic)
    with open(out / "state_1205ic.csv", "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["node_id", *FIELDS, "depth_m"])
        for nid in range(lattice.n_nodes):
            w.writerow([nid, *(f"{v:.6g}" for v in ic[nid])])
    prov["state_1205ic"] = ("raw/1205/Initial Conditions.zip::IC/2019.06.10_IC_local_node_v2.xlsx; "
                            "T=temperature-273.15; P=pressure/1e6; Sv=-disp_k_bc; SHmax=-disp_j_bc; "
                            "Shmin=-disp_i_bc (total stress BC columns, Pa -> MPa)")

    # 3. 1160 native state (joined to node ids by coordinates)
    with zipfile.ZipFile(raw / "1160" / "native-state-ptm.zip") as z:
        name = [n for n in z.namelist() if n.endswith("_native_state_global.csv") and "MACOSX" not in n][0]
        with z.open(name) as f:
            rd = csv.DictReader(io.TextIOWrapper(f, "utf-8"))
            ns = {}
            for r in rd:
                u, v = lattice.to_local(float(r["x"]), float(r["y"]))
                i, j = round(u / lattice.spacing), round(v / lattice.spacing)
                k = round((float(r["z"]) - lattice.z0) / lattice.spacing)
                nid = i + lattice.ni * (j + lattice.nj * k)
                ns[nid] = (float(r["temperature_C"]), float(r["pressure_Pa"]) / 1e6,
                           float(r["Sigma_V_Pa"]) / 1e6, float(r["sigma_h_max_Pa"]) / 1e6,
                           float(r["sigma_h_min_Pa"]) / 1e6)
    with open(out / "state_1160.csv", "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["node_id", *FIELDS])
        for nid in sorted(ns):
            w.writerow([nid, *(f"{v:.6g}" for v in ns[nid])])
    prov["state_1160"] = f"raw/1160/native-state-ptm.zip::{name} ({len(ns)} nodes)"

    # 4. summary: gradients (fit to the 1205 IC vs depth), azimuth, regime, properties
    depth = [ic[n][5] for n in range(lattice.n_nodes)]
    grads = {}
    for fi, k in enumerate(FIELDS):
        b, a = _linfit(depth, [ic[n][fi] for n in range(lattice.n_nodes)])
        grads[k] = round(b * 1000, 4)
    # SHmax is the stress on the local v ("j") axis (disp_j_bc = h_max in the FALCON input);
    # the v axis points at the lattice azimuth.
    summary = {
        "SHmax_azimuth_deg": lattice.azimuth_deg % 180,
        "stress_regime": "normal" if grads["Sv_MPa"] >= grads["SHmax_MPa"] >= grads["Shmin_MPa"] else "?",
        "gradients_per_km": grads,
        "properties": _unit_properties(raw),
        "provenance": prov,
    }
    summary["provenance"]["gradients"] = "least-squares slope vs 1205 IC depth column over all nodes"
    summary["provenance"]["azimuth"] = ("1205 grid rotated 25 deg clockwise; SHmax BC on the j axis "
                                        "(1315 PTM2.i: pressure_sigma_h_max on disp_j)")
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    return summary


def _unit_properties(raw: Path) -> dict:
    """Per-unit expert properties: FALCON inputs (1315) and per-cell k/phi (1160).

    Where the expert files give two values (density differs between the TH and
    the TM input deck), both are kept; scoring uses the nearer one.
    """
    import io
    kk = {1: [], 2: []}
    ph = {1: [], 2: []}
    with zipfile.ZipFile(raw / "1160" / "reservoir-porosity-and-upscale-dfn-permeability.zip") as z:
        name = [n for n in z.namelist() if n.endswith("poro_perm_global.csv") and "MACOSX" not in n][0]
        with z.open(name) as f:
            rd = _read_leapfrog_csv(io.TextIOWrapper(f, "utf-8"))
            hdr = next(rd)
            ix = {k: hdr.index(k) for k in ("Kii", "Kjj", "Kkk", "porosity", "block")}
            for r in rd:
                if not r or not r[0].strip():
                    continue
                b = int(float(r[ix["block"]]))
                k3 = [float(r[ix[c]]) for c in ("Kii", "Kjj", "Kkk")]
                kk[b].append(math.exp(sum(math.log(v) for v in k3) / 3))
                ph[b].append(float(r[ix["porosity"]]))
    med = statistics.median
    # block 2 = granitoid, block 1 = sediments (1315 PT3.i / PTM2.i comments)
    return {
        "granitoid": {
            "permeability_m2": [med(kk[2])], "porosity": [med(ph[2])],
            "youngs_modulus_GPa": [62.0], "poissons_ratio": [0.3],
            "density_kg_m3": [2640.0, 2750.0], "thermal_conductivity_W_mK": [3.05],
        },
        "basin_fill": {
            "permeability_m2": [med(kk[1])], "porosity": [med(ph[1])],
            "youngs_modulus_GPa": [30.0], "poissons_ratio": [0.3],
            "density_kg_m3": [2400.0, 2500.0], "thermal_conductivity_W_mK": [2.0],
        },
        "_source": ("1315 Phase2 native state model files.zip: PT/2019.06.06_PT3.i (density 2400/2640, "
                    "conductivity 2/3.05) and PTM/2019.06.12_PTM2.i (density 2500/2750, E 30/62 GPa, nu 0.3); "
                    f"k = median per block of geometric-mean(Kii,Kjj,Kkk), phi = median, from 1160 {name} "
                    f"(n = {len(kk[2])} granitoid / {len(kk[1])} sediment cells)"),
    }


if __name__ == "__main__":
    import sys
    print(json.dumps(build_truth(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TRUTH), indent=1))
