#!/usr/bin/env python3
"""Turn the 2025 expert native-state model (GDR 1812) into a FORGE-v0 submission,
so the scorer can measure how far the experts' own model moved from 2019 (1205).

1812 is in a local frame. Its own script (inputData/lpToMOOSEWellLocalCoordSys.py)
defines the map from UTM: rotate +20 deg about z around c = (335343.707, 4263012.44),
then translate by (-335345.48, -4263010.66, +1150). We invert that.

  - lithology:     unit of the mesh60m tetrahedron containing each 1205 cell centre
                   (matrix_133 = granitoid, matrix_134 = sediment/basin fill)
  - granitoid_top: highest granitoid sample on a vertical line (10 m steps) at each
                   50 m map point of the output-spec extent
  - initial_state: IDW (8 nearest) of the 40 m-mesh element-centre samples
                   (MOOSEfiles/THM_40mMesh_point_sample_0012.csv) at each 1205 node;
                   horizontal principal stresses from (ii, ij, jj); compression positive
  - properties:    nativeStateModel2025.i
Needs numpy + scipy. Output: /data/matt/sci-sim-op/geomodel/forge/baselines/expert2025/
"""
from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
from geomodel_bench.grid import FORGE_1205 as LAT  # noqa: E402

FORGE = Path("/data/matt/sci-sim-op/geomodel/forge")
W = FORGE / "work1812" / "GDR"
OUT = FORGE / "baselines" / "expert2025"
C = np.array([335343.707, 4263012.44])
T = np.array([-335345.48, -4263010.66, 1150.0])
A = math.radians(20.0)
R = np.array([[math.cos(A), -math.sin(A)], [math.sin(A), math.cos(A)]])


def utm_to_local(xyz: np.ndarray) -> np.ndarray:
    xy = (xyz[:, :2] - C) @ R.T + C + T[:2]
    return np.column_stack([xy, xyz[:, 2] + T[2]])


def read_gmsh41(path: Path):
    """Nodes (dict tag->xyz array) and tets with their physical tag (133/134)."""
    with open(path) as f:
        lines = iter(f.read().split("\n"))
    ent_phys = {}
    node_tags, node_xyz = [], []
    tets, tet_phys = [], []
    for line in lines:
        if line == "$Entities":
            npt, ncu, nsu, nvo = map(int, next(lines).split())
            for _ in range(npt + ncu + nsu):
                next(lines)
            for _ in range(nvo):
                p = next(lines).split()
                nphys = int(p[7])
                ent_phys[int(p[0])] = int(p[8]) if nphys else None
        elif line == "$Nodes":
            nblocks = int(next(lines).split()[0])
            for _ in range(nblocks):
                _dim, _tag, _par, n = map(int, next(lines).split())
                tags = [int(next(lines)) for _ in range(n)]
                xyz = [list(map(float, next(lines).split())) for _ in range(n)]
                node_tags.extend(tags)
                node_xyz.extend(xyz)
        elif line == "$Elements":
            nblocks = int(next(lines).split()[0])
            for _ in range(nblocks):
                dim, tag, etype, n = map(int, next(lines).split())
                rows = [next(lines) for _ in range(n)]
                if dim == 3 and etype == 4:
                    arr = np.array([list(map(int, r.split()))[1:5] for r in rows])
                    tets.append(arr)
                    tet_phys.append(np.full(len(arr), ent_phys[tag]))
    idx = np.full(max(node_tags) + 1, -1)
    idx[np.array(node_tags)] = np.arange(len(node_tags))
    return np.array(node_xyz), idx[np.vstack(tets)], np.concatenate(tet_phys)


class Locator:
    def __init__(self, xyz, tets, phys):
        self.v = xyz[tets]                       # (n,4,3)
        self.phys = phys
        self.tree = cKDTree(self.v.mean(axis=1))
        T0 = self.v[:, 1:, :] - self.v[:, :1, :]  # (n,3,3) edge vectors
        self.inv = np.linalg.inv(np.transpose(T0, (0, 2, 1)))

    def unit(self, pts: np.ndarray, k: int = 24) -> np.ndarray:
        """Physical tag of the tet containing each point (nearest-centroid tet if none)."""
        out = np.zeros(len(pts), dtype=int)
        for s in range(0, len(pts), 200_000):
            p = pts[s:s + 200_000]
            _, nn = self.tree.query(p, k=k)
            rel = p[:, None, :] - self.v[nn, 0, :]               # (m,k,3)
            lam = np.einsum("mkij,mkj->mki", self.inv[nn], rel)  # barycentric 1..3
            inside = (lam >= -1e-9).all(-1) & (lam.sum(-1) <= 1 + 1e-9)
            first = np.where(inside.any(1), inside.argmax(1), 0)
            out[s:s + 200_000] = self.phys[nn[np.arange(len(p)), first]]
        return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    xyz, tets, phys = read_gmsh41(W / "mesh60m.msh")
    print("mesh60m:", len(xyz), "nodes", len(tets), "tets", {int(t): int((phys == t).sum()) for t in np.unique(phys)})
    loc = Locator(xyz, tets, phys)

    # lithology at 1205 cell centres
    cc = np.array([LAT.cell_xyz(c) for c in range(LAT.n_cells)])
    u = loc.unit(utm_to_local(cc))
    with open(OUT / "lithology.csv", "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["cell_id", "unit"])
        for c, t in enumerate(u):
            w.writerow([c, "granitoid" if t == 133 else "basin_fill"])

    # contact on the map grid (vertical scan, 10 m)
    xs = np.arange(332000, 338001, 50)
    ys = np.arange(4260000, 4266001, 50)
    X, Y = np.meshgrid(xs, ys, indexing="ij")
    zs = np.arange(-1795.0 + 0, 2700.0, 10.0) - 1150.0      # local z range -> elevation
    tops = np.full(X.size, np.nan)
    flat = np.column_stack([X.ravel(), Y.ravel()])
    for s in range(0, len(flat), 500):
        blk = flat[s:s + 500]
        pts = np.column_stack([np.repeat(blk, len(zs), axis=0), np.tile(zs, len(blk))])
        un = loc.unit(utm_to_local(pts)).reshape(len(blk), len(zs))
        g = un == 133
        top = np.where(g.any(1), zs[np.where(g, np.arange(len(zs)), -1).max(1)] + 5.0, zs[0])
        tops[s:s + 500] = top
    with open(OUT / "granitoid_top.csv", "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["x", "y", "z_top"])
        for (x, y), z in zip(flat, tops):
            w.writerow([int(x), int(y), round(float(z), 1)])

    # state at 1205 nodes: IDW of the 40 m element-centre samples
    rows = np.genfromtxt(W / "MOOSEfiles" / "THM_40mMesh_point_sample_0012.csv", delimiter=",", names=True)
    sp = np.column_stack([rows["x"], rows["y"], rows["z"]])
    tree = cKDTree(sp)
    nodes = np.array([LAT.node_xyz(n) for n in range(LAT.n_nodes)])
    d, nn = tree.query(utm_to_local(nodes), k=8)
    wgt = 1.0 / np.maximum(d, 1e-3) ** 2
    wgt /= wgt.sum(1, keepdims=True)

    def interp(col):
        return (rows[col][nn] * wgt).sum(1)

    Tn = interp("temperature") - 273.15
    Pn = interp("pressure") / 1e6
    sii, sij, sjj, skk = (interp(c) / 1e6 for c in ("stress_ii", "stress_ij", "stress_jj", "stress_kk"))
    mean, rad = (sii + sjj) / 2, np.sqrt(((sii - sjj) / 2) ** 2 + sij ** 2)
    shmax, shmin = -(mean - rad), -(mean + rad)          # compression negative in MOOSE
    with open(OUT / "initial_state.csv", "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["node_id", "T_C", "P_MPa", "Sv_MPa", "SHmax_MPa", "Shmin_MPa"])
        for n in range(LAT.n_nodes):
            w.writerow([n, round(Tn[n], 3), round(Pn[n], 4), round(-skk[n], 4), round(shmax[n], 4), round(shmin[n], 4)])
    # SHmax azimuth: nativeStateModel2025.i applies sigma_h_max on the ymin/ymax boundaries,
    # i.e. along local y. UTM = Rz(-20 deg) . local, so local y points to bearing N20E.
    az = 20.0
    depth_proxy = LAT.z_top + 450 - nodes[:, 2]
    g = {k: float(np.polyfit(depth_proxy, v, 1)[0] * 1000) for k, v in
         (("T_C", Tn), ("P_MPa", Pn), ("Sv_MPa", -skk), ("SHmax_MPa", shmax), ("Shmin_MPa", shmin))}
    (OUT / "state.json").write_text(json.dumps({"SHmax_azimuth_deg": round(float(az), 1),
                                                "stress_regime": "normal", "gradients_per_km": g}, indent=1))
    props = {
        "granitoid": {"permeability_m2": 5e-17, "porosity": 0.0002, "youngs_modulus_GPa": 62.0,
                      "poissons_ratio": 0.3, "density_kg_m3": 2750.0, "thermal_conductivity_W_mK": 3.05},
        "basin_fill": {"permeability_m2": 1e-14, "porosity": 0.12, "youngs_modulus_GPa": 30.0,
                       "poissons_ratio": 0.3, "density_kg_m3": 2500.0, "thermal_conductivity_W_mK": 2.8},
    }
    (OUT / "properties.json").write_text(json.dumps(
        {u_: {p: {"value": v, "low": v, "high": v} for p, v in d_.items()} for u_, d_ in props.items()}, indent=1))
    (OUT / "MODEL_REPORT.md").write_text("# Expert 2025 (GDR 1812), resampled onto the 1205 grid\n\n"
                                         "Built by scripts/geomodel/expert2025_submission.py. Calibrated with wells drilled "
                                         "after 2019, so its blind-well score is not blind.\n")
    print("SHmax azimuth (UTM) =", round(float(az), 1), "gradients", {k: round(v, 2) for k, v in g.items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
