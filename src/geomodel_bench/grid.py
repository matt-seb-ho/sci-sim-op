"""The FORGE-v0 model grid: a rotated regular lattice (GDR 1205 geometry).

Nodes are numbered ``id = i + ni*j + ni*nj*k`` (i fastest, k = up), cells
likewise with (ni-1, nj-1, nk-1). Local axis u points along the rotated
"x" direction, v along the rotated "y" direction; both are horizontal.
"""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Lattice:
    x0: float          # node (0,0,0), UTM easting
    y0: float          # node (0,0,0), UTM northing
    z0: float          # node (0,0,0), elevation
    azimuth_deg: float  # local v axis, degrees clockwise from north
    spacing: float
    ni: int            # nodes along u
    nj: int            # nodes along v
    nk: int            # nodes along z

    # -- sizes -------------------------------------------------------------
    @property
    def n_nodes(self) -> int:
        return self.ni * self.nj * self.nk

    @property
    def n_cells(self) -> int:
        return (self.ni - 1) * (self.nj - 1) * (self.nk - 1)

    @property
    def z_top(self) -> float:
        return self.z0 + (self.nk - 1) * self.spacing

    # -- frames ------------------------------------------------------------
    def to_local(self, x: float, y: float) -> tuple[float, float]:
        a = math.radians(self.azimuth_deg)
        dx, dy = x - self.x0, y - self.y0
        return dx * math.cos(a) - dy * math.sin(a), dx * math.sin(a) + dy * math.cos(a)

    def to_global(self, u: float, v: float) -> tuple[float, float]:
        a = math.radians(self.azimuth_deg)
        return (self.x0 + u * math.cos(a) + v * math.sin(a),
                self.y0 - u * math.sin(a) + v * math.cos(a))

    def node_xyz(self, nid: int) -> tuple[float, float, float]:
        i, j, k = nid % self.ni, (nid // self.ni) % self.nj, nid // (self.ni * self.nj)
        x, y = self.to_global(i * self.spacing, j * self.spacing)
        return x, y, self.z0 + k * self.spacing

    def cell_ijk(self, cid: int) -> tuple[int, int, int]:
        ci, cj = self.ni - 1, self.nj - 1
        return cid % ci, (cid // ci) % cj, cid // (ci * cj)

    def cell_id(self, i: int, j: int, k: int) -> int:
        return i + (self.ni - 1) * (j + (self.nj - 1) * k)

    def cell_xyz(self, cid: int) -> tuple[float, float, float]:
        i, j, k = self.cell_ijk(cid)
        h = self.spacing
        x, y = self.to_global((i + 0.5) * h, (j + 0.5) * h)
        return x, y, self.z0 + (k + 0.5) * h

    def column_xy(self, i: int, j: int) -> tuple[float, float]:
        h = self.spacing
        return self.to_global((i + 0.5) * h, (j + 0.5) * h)

    def contains(self, x: float, y: float, z: float | None = None) -> bool:
        u, v = self.to_local(x, y)
        L_u, L_v = (self.ni - 1) * self.spacing, (self.nj - 1) * self.spacing
        ok = 0 <= u <= L_u and 0 <= v <= L_v
        if z is not None:
            ok = ok and self.z0 <= z <= self.z_top
        return ok

    # -- interpolation -----------------------------------------------------
    def trilinear(self, values, x: float, y: float, z: float):
        """Interpolate node values (indexable by node id) at a point. None if
        outside the lattice or if any of the 8 corner values is None."""
        if not self.contains(x, y, z):
            return None
        u, v = self.to_local(x, y)
        h = self.spacing
        fu, fv, fz = u / h, v / h, (z - self.z0) / h
        i = min(int(fu), self.ni - 2)
        j = min(int(fv), self.nj - 2)
        k = min(int(fz), self.nk - 2)
        tu, tv, tz = fu - i, fv - j, fz - k
        acc = 0.0
        for di, wu in ((0, 1 - tu), (1, tu)):
            for dj, wv in ((0, 1 - tv), (1, tv)):
                for dk, wz in ((0, 1 - tz), (1, tz)):
                    w = wu * wv * wz
                    if w == 0.0:
                        continue
                    val = values[(i + di) + self.ni * ((j + dj) + self.nj * (k + dk))]
                    if val is None:
                        return None
                    acc += w * val
        return acc


FORGE_1205 = Lattice(x0=333358.2232, y0=4262837.092, z0=-1500.0, azimuth_deg=25.0,
                     spacing=50.0, ni=51, nj=51, nk=56)


def check_against_nodes_csv(lat: Lattice, path: str, tol: float = 0.05) -> int:
    """Assert that nodes.csv matches the lattice numbering; return rows checked."""
    n = 0
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            nid = int(row["node_id"])
            x, y, z = lat.node_xyz(nid)
            if (abs(x - float(row["x"])) > tol or abs(y - float(row["y"])) > tol
                    or abs(z - float(row["z"])) > tol):
                raise ValueError(f"node {nid}: file {row} vs lattice {(x, y, z)}")
            n += 1
    if n != lat.n_nodes:
        raise ValueError(f"{n} nodes in file, lattice has {lat.n_nodes}")
    return n
