"""Reference submissions that anchor the FORGE-v0 score scale.

naive       flat contact at the 58-32 contact elevation; T from a straight-line fit
            to the 58-32 temperature log; hydrostatic P; textbook stress ratios and
            N-S SHmax (Basin-and-Range E-W extension); textbook granite/sediment
            properties. Uses nothing a 2019 modeller would not have in hand.
expert2019  the 2019 expert model itself: 1205 labels and IC, 1315/1160 properties,
            its contact surface sampled on the 50 m map grid inside the 1205 footprint.
            Trivially perfect on axis A; its axis-B score is the ceiling.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from .grid import Lattice
from .score import column_contacts
from .truth import FIELDS, PROPS, UNITS, Truth

# Textbook values (Turcotte & Schubert / generic crystalline vs basin sediment).
TEXTBOOK = {
    "granitoid": {"permeability_m2": (1e-18, 1e-20, 1e-16), "porosity": (0.01, 0.001, 0.05),
                  "youngs_modulus_GPa": (50.0, 30.0, 70.0), "poissons_ratio": (0.25, 0.2, 0.3),
                  "density_kg_m3": (2650.0, 2600.0, 2700.0),
                  "thermal_conductivity_W_mK": (3.0, 2.5, 3.5)},
    "basin_fill": {"permeability_m2": (1e-13, 1e-15, 1e-11), "porosity": (0.25, 0.1, 0.4),
                   "youngs_modulus_GPa": (10.0, 1.0, 30.0), "poissons_ratio": (0.3, 0.2, 0.4),
                   "density_kg_m3": (2200.0, 1900.0, 2500.0),
                   "thermal_conductivity_W_mK": (1.5, 1.0, 2.5)},
}
SV_KPA_M = 25.0          # rho 2550 kg/m3
SHMIN_RATIO = 0.6        # normal-faulting textbook ratios to Sv
SHMAX_RATIO = 0.8
PHYD_KPA_M = 9.81


def _write_csv(path: Path, header, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def _surface_grid(extent=(332000, 338000, 4260000, 4266000), step=50):
    x0, x1, y0, y1 = extent
    for x in range(x0, x1 + 1, step):
        for y in range(y0, y1 + 1, step):
            yield x, y


NAIVE_T_LOG = ("raw/1101/58-32_Temp_Pres_11_08_18.zip", "UOFU_MU-ESW1_PT118.las", 21.5)  # KB above GL, ft


def read_1101_t_profile(forge_root: str | Path = "/data/matt/sci-sim-op/geomodel/forge"):
    """58-32 temperature log of 2018-11-08 (GDR 1101, an input): [(depth below GL m, T C)]."""
    import zipfile
    zpath, member, kb_ft = NAIVE_T_LOG
    with zipfile.ZipFile(Path(forge_root) / zpath) as z:
        txt = z.read(member).decode("latin-1")
    out, in_data = [], False
    for line in txt.splitlines():
        if line.startswith("~A"):
            in_data = True
            continue
        if line.startswith("~"):
            in_data = False
            continue
        if in_data or (line.strip() and line.strip()[0].isdigit() and not line.startswith(("~", "#"))):
            parts = line.split()
            try:
                dep_ft, t_f = float(parts[0]), float(parts[1])
            except (IndexError, ValueError):
                continue
            if t_f < -900:
                continue
            out.append(((dep_ft - kb_ft) * 0.3048, (t_f - 32) / 1.8))
    return out


def write_naive(out: str | Path, truth: Truth, t_profile) -> Path:
    """t_profile: [(depth below ground m, T C)] from the 58-32 pre-cut log."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    lat = truth.lattice
    ref = truth.wells["reference_wells"]["58-32"]
    zc = ref["granitoid_top"]["z_elev_m"]
    ground = ref["wellhead"]["ground_elev_m"]
    prof = [(d, t) for d, t in t_profile if d >= 100.0]  # below the water level
    d = [p[0] for p in prof]
    tt = [p[1] for p in prof]
    mx, my = sum(d) / len(d), sum(tt) / len(d)
    b = sum((x - mx) * (y - my) for x, y in zip(d, tt)) / sum((x - mx) ** 2 for x in d)
    a = my - b * mx

    _write_csv(out / "lithology.csv", ["cell_id", "unit"],
               [(c, "granitoid" if lat.cell_xyz(c)[2] < zc else "basin_fill") for c in range(lat.n_cells)])
    _write_csv(out / "granitoid_top.csv", ["x", "y", "z_top"], [(x, y, zc) for x, y in _surface_grid()])
    rows = []
    for n in range(lat.n_nodes):
        dep = max(ground - lat.node_xyz(n)[2], 0.0)
        sv = SV_KPA_M * dep / 1000
        rows.append((n, round(a + b * dep, 3), round(PHYD_KPA_M * dep / 1000, 4), round(sv, 4),
                     round(SHMAX_RATIO * sv, 4), round(SHMIN_RATIO * sv, 4)))
    _write_csv(out / "initial_state.csv", ["node_id", *FIELDS], rows)
    (out / "state.json").write_text(json.dumps({
        "SHmax_azimuth_deg": 0.0, "stress_regime": "normal",
        "gradients_per_km": {"T_C": round(b * 1000, 3), "P_MPa": PHYD_KPA_M, "Sv_MPa": SV_KPA_M,
                             "SHmax_MPa": SHMAX_RATIO * SV_KPA_M, "Shmin_MPa": SHMIN_RATIO * SV_KPA_M},
    }, indent=1))
    (out / "properties.json").write_text(json.dumps(
        {u: {p: dict(zip(("value", "low", "high"), TEXTBOOK[u][p])) for p in PROPS} for u in UNITS}, indent=1))
    (out / "MODEL_REPORT.md").write_text(
        "# Naive baseline\n\nFlat contact at the 58-32 contact elevation "
        f"({zc:.0f} m); T = {a:.1f} + {b * 1000:.1f} °C/km × depth (fit to the 58-32 log "
        f"of 2018-11-08, GDR 1101); hydrostatic P; Sv {SV_KPA_M} kPa/m, SHmax {SHMAX_RATIO} Sv, "
        f"Shmin {SHMIN_RATIO} Sv, SHmax N-S; textbook properties. Depth is below the 58-32 "
        f"ground level ({ground:.0f} m), taken as flat.\n")
    return out


def _contact_interp(lat: Lattice, cc: dict, x: float, y: float):
    """Bilinear in the lattice frame between column centres, held constant up to one
    map cell (50 m) beyond the edge columns; None further out."""
    u, v = lat.to_local(x, y)
    h = lat.spacing
    fu, fv = u / h - 0.5, v / h - 0.5
    ci, cj = lat.ni - 1, lat.nj - 1
    if not (-1.5 <= fu <= ci + 0.5 and -1.5 <= fv <= cj + 0.5):
        return None
    fu = min(max(fu, 0.0), ci - 1.0)
    fv = min(max(fv, 0.0), cj - 1.0)
    i, j = min(int(fu), ci - 2), min(int(fv), cj - 2)
    tu, tv = fu - i, fv - j
    return ((1 - tu) * (1 - tv) * cc[(i, j)] + tu * (1 - tv) * cc[(i + 1, j)]
            + (1 - tu) * tv * cc[(i, j + 1)] + tu * tv * cc[(i + 1, j + 1)])


def write_expert(out: str | Path, truth: Truth, state: str = "1205ic") -> Path:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    lat = truth.lattice
    _write_csv(out / "lithology.csv", ["cell_id", "unit"], list(enumerate(truth.lithology)))
    cc = column_contacts(truth.lithology, lat)
    L_u, L_v = (lat.ni - 1) * lat.spacing, (lat.nj - 1) * lat.spacing
    corners = [lat.to_global(u, v) for u in (0, L_u) for v in (0, L_v)]
    xs, ys = [c[0] for c in corners], [c[1] for c in corners]
    bbox = (int(min(xs) // 50 * 50), int(max(xs) // 50 * 50 + 50),
            int(min(ys) // 50 * 50), int(max(ys) // 50 * 50 + 50))
    pts = []
    for x, y in _surface_grid(bbox):
        z = _contact_interp(lat, cc, x, y)
        if z is not None:
            pts.append((x, y, round(z, 2)))
    _write_csv(out / "granitoid_top.csv", ["x", "y", "z_top"], pts)
    cols = truth.states[state]
    _write_csv(out / "initial_state.csv", ["node_id", *FIELDS],
               [(n, *(cols[k][n] for k in FIELDS)) for n in range(lat.n_nodes)])
    s = truth.summary
    (out / "state.json").write_text(json.dumps({k: s[k] for k in
                                                ("SHmax_azimuth_deg", "stress_regime", "gradients_per_km")}, indent=1))
    props = {u: {p: {"value": s["properties"][u][p][0], "low": min(s["properties"][u][p]),
                     "high": max(s["properties"][u][p])} for p in PROPS} for u in UNITS}
    (out / "properties.json").write_text(json.dumps(props, indent=1))
    (out / "MODEL_REPORT.md").write_text(f"# Expert 2019 (GDR 1205 + 1160/1315), state from {state}\n")
    return out


def write_perfect_flipped(out: str | Path, truth: Truth) -> Path:
    """Expert submission with every lithology label swapped (for tests / sanity)."""
    out = write_expert(out, truth)
    flip = {"granitoid": "basin_fill", "basin_fill": "granitoid"}
    _write_csv(out / "lithology.csv", ["cell_id", "unit"],
               [(c, flip[u]) for c, u in enumerate(truth.lithology)])
    return out

