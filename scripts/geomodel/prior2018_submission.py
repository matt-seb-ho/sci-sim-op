#!/usr/bin/env python3
"""The Phase 2B (Dec 2018) earth-model surface (GDR 1107) as a FORGE-v0 submission:
granitoid_top.csv and lithology.csv only (the 2B model has no state or properties).
It anchors variant B: did the agent's update beat the model it started from?"""
import csv
import sys
from pathlib import Path

import numpy as np
from scipy.interpolate import griddata

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from geomodel_bench.grid import FORGE_1205 as LAT  # noqa: E402

FORGE = Path("/data/matt/sci-sim-op/geomodel/forge")
OUT = FORGE / "baselines" / "prior2018"
OUT.mkdir(parents=True, exist_ok=True)
v = np.genfromtxt(FORGE / "raw/1107/top_granitoid_vertices.csv", delimiter=",", names=True)
names = v.dtype.names
P = np.column_stack([v[names[0]], v[names[1]]]); Z = v[names[2]]
xs, ys = np.arange(332000, 338001, 50), np.arange(4260000, 4266001, 50)
X, Y = np.meshgrid(xs, ys, indexing="ij")
zt = griddata(P, Z, (X, Y), method="linear")
with open(OUT / "granitoid_top.csv", "w", newline="") as f:
    w = csv.writer(f, lineterminator="\n"); w.writerow(["x", "y", "z_top"])
    for x, y, z in zip(X.ravel(), Y.ravel(), zt.ravel()):
        if np.isfinite(z):
            w.writerow([int(x), int(y), round(float(z), 2)])
cc = np.array([LAT.cell_xyz(c) for c in range(LAT.n_cells)])
zc = griddata(P, Z, cc[:, :2], method="linear")
with open(OUT / "lithology.csv", "w", newline="") as f:
    w = csv.writer(f, lineterminator="\n"); w.writerow(["cell_id", "unit"])
    for c in range(LAT.n_cells):
        w.writerow([c, "granitoid" if cc[c, 2] < zc[c] else "basin_fill"])
print("done", np.nanmin(zt), np.nanmax(zt))
