"""Score a FORGE-v0 submission directory (docs/geomodel/FORGE_v0_OUTPUT_SPEC.md).

Every metric is a dict with a ``status``:
  ok          scored; ``value`` is set
  missing     the file or key is absent / unreadable
  incomplete  fewer than 99% of the required rows are present and numeric
  n/a         cannot be evaluated for this submission (e.g. point outside its surface)
Only ``ok`` metrics carry a ``value``. A missing file is never scored as 0 error.

Axis A compares with the 2019 expert model (GDR 1205, with 1160/1315);
axis B with the blind wells drilled after the 2019-09 cut.
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

from .grid import Lattice
from .truth import FIELDS, PROPS, UNITS, Truth

COVERAGE = 0.99
LOW_CONFIDENCE_T = {"low"}  # blind-well T logs excluded from the pooled T score
# Metrics where higher is better; everything else is an error (lower is better).
HIGHER_IS_BETTER = {"A.lith_balanced_accuracy", "A.stress_regime_match", "A.prop_range_hit_frac"}


def ok(value, **kw):
    return {"status": "ok", "value": value, **kw}


def bad(status, why, **kw):
    return {"status": status, "why": why, **kw}


def _finite(s):
    try:
        v = float(s)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _read_csv(path: Path, required: tuple[str, ...]):
    """Rows as dicts, or raise ValueError with a reason."""
    if not path.is_file():
        raise FileNotFoundError(path.name)
    with open(path, newline="", encoding="utf-8-sig") as f:
        rd = csv.DictReader(f)
        hdr = [h.strip() for h in (rd.fieldnames or [])]
        rd.fieldnames = hdr
        miss = [c for c in required if c not in hdr]
        if miss:
            raise ValueError(f"{path.name}: missing columns {miss} (have {hdr[:10]})")
        return list(rd)


def _read_json(path: Path):
    if not path.is_file():
        raise FileNotFoundError(path.name)
    return json.loads(path.read_text())


def _rmse(pairs):
    if not pairs:
        return None
    return math.sqrt(sum((a - b) ** 2 for a, b in pairs) / len(pairs))


# ---------------------------------------------------------------- submission IO
class Submission:
    def __init__(self, root: str | Path, lat: Lattice):
        self.root = Path(root)
        self.lat = lat
        self.errors: dict[str, str] = {}
        self.lith = self._lith()
        self.state, self.state_cov = self._state()
        self.surface = self._surface()
        self.summary = self._json("state.json")
        self.props = self._json("properties.json")

    def _json(self, name):
        try:
            return _read_json(self.root / name)
        except Exception as e:  # noqa: BLE001
            self.errors[name] = f"{type(e).__name__}: {e}"
            return None

    def _lith(self):
        try:
            rows = _read_csv(self.root / "lithology.csv", ("cell_id", "unit"))
        except Exception as e:  # noqa: BLE001
            self.errors["lithology.csv"] = f"{type(e).__name__}: {e}"
            return None
        out = [None] * self.lat.n_cells
        for r in rows:
            try:
                cid = int(float(r["cell_id"]))
            except (TypeError, ValueError):
                continue
            if 0 <= cid < self.lat.n_cells:
                u = (r["unit"] or "").strip().lower().replace(" ", "_").replace("-", "_")
                out[cid] = u
        return out

    def _state(self):
        try:
            rows = _read_csv(self.root / "initial_state.csv", ("node_id", *FIELDS))
        except Exception as e:  # noqa: BLE001
            self.errors["initial_state.csv"] = f"{type(e).__name__}: {e}"
            return None, {}
        cols = {k: [None] * self.lat.n_nodes for k in FIELDS}
        for r in rows:
            try:
                nid = int(float(r["node_id"]))
            except (TypeError, ValueError):
                continue
            if 0 <= nid < self.lat.n_nodes:
                for k in FIELDS:
                    cols[k][nid] = _finite(r[k])
        cov = {k: sum(v is not None for v in cols[k]) / self.lat.n_nodes for k in FIELDS}
        return cols, cov

    def _surface(self):
        try:
            rows = _read_csv(self.root / "granitoid_top.csv", ("x", "y", "z_top"))
        except Exception as e:  # noqa: BLE001
            self.errors["granitoid_top.csv"] = f"{type(e).__name__}: {e}"
            return None
        pts = {}
        for r in rows:
            x, y, z = _finite(r["x"]), _finite(r["y"]), _finite(r["z_top"])
            if x is None or y is None or z is None:
                continue
            pts[(round(x / 50.0), round(y / 50.0))] = z
        return pts

    def surface_at(self, x: float, y: float):
        """Bilinear on the 50 m map grid; nearest node within 50 m if a corner is
        missing; None if the point is not covered."""
        if not self.surface:
            return None
        fx, fy = x / 50.0, y / 50.0
        i, j = math.floor(fx), math.floor(fy)
        tx, ty = fx - i, fy - j
        c = [self.surface.get((i + a, j + b)) for a in (0, 1) for b in (0, 1)]
        if all(v is not None for v in c):
            return (c[0] * (1 - tx) * (1 - ty) + c[1] * (1 - tx) * ty
                    + c[2] * tx * (1 - ty) + c[3] * tx * ty)
        near = self.surface.get((round(fx), round(fy)))
        return near


# ---------------------------------------------------------------- helpers
def column_contacts(lith, lat: Lattice):
    """Top-of-granitoid elevation per (i, j) column: top face of the highest
    granitoid cell; grid bottom if none. Returns dict (i,j) -> z, or None
    for columns with any unreadable cell."""
    ci, cj, ck = lat.ni - 1, lat.nj - 1, lat.nk - 1
    out = {}
    for j in range(cj):
        for i in range(ci):
            z = lat.z0
            complete = True
            for k in range(ck):
                u = lith[lat.cell_id(i, j, k)]
                if u is None:
                    complete = False
                elif u == "granitoid":
                    z = lat.z0 + (k + 1) * lat.spacing
            out[(i, j)] = z if complete else None
    return out


def _clip(z, lat):
    return min(max(z, lat.z0), lat.z_top)


# ---------------------------------------------------------------- axis A
def score_lithology(sub: Submission, t: Truth) -> dict:
    m = {}
    if sub.lith is None:
        m["A.lith_balanced_accuracy"] = bad("missing", sub.errors.get("lithology.csv"))
        m["A.contact_from_lithology_rmse_m"] = bad("missing", sub.errors.get("lithology.csv"))
        return m
    n = t.lattice.n_cells
    present = sum(u in UNITS for u in sub.lith)
    if present / n < COVERAGE:
        why = f"{present}/{n} cells with a valid unit"
        m["A.lith_balanced_accuracy"] = bad("incomplete", why)
        m["A.contact_from_lithology_rmse_m"] = bad("incomplete", why)
        return m
    rec = {}
    for unit in UNITS:
        idx = [c for c in range(n) if t.lithology[c] == unit]
        rec[unit] = sum(sub.lith[c] == unit for c in idx) / len(idx)
    m["A.lith_balanced_accuracy"] = ok(sum(rec.values()) / len(rec),
                                       recall={u: round(v, 4) for u, v in rec.items()})
    tc = column_contacts(t.lithology, t.lattice)
    sc = column_contacts([u if u in UNITS else "basin_fill" for u in sub.lith], t.lattice)
    pairs = [(sc[k], tc[k]) for k in tc]
    m["A.contact_from_lithology_rmse_m"] = ok(_rmse(pairs), n=len(pairs))
    return m


def score_surface(sub: Submission, t: Truth) -> dict:
    lat = t.lattice
    if sub.surface is None:
        return {"A.contact_rmse_m": bad("missing", sub.errors.get("granitoid_top.csv"))}
    tc = column_contacts(t.lithology, lat)
    pairs = []
    for (i, j), zt in tc.items():
        x, y = lat.column_xy(i, j)
        zs = sub.surface_at(x, y)
        if zs is not None:
            pairs.append((_clip(zs, lat), zt))
    if len(pairs) / len(tc) < COVERAGE:
        return {"A.contact_rmse_m": bad("incomplete", f"surface covers {len(pairs)}/{len(tc)} grid columns")}
    bias = sum(a - b for a, b in pairs) / len(pairs)
    return {"A.contact_rmse_m": ok(_rmse(pairs), n=len(pairs), bias_m=round(bias, 2),
                                   note="both clipped to the grid's z range")}


def score_state(sub: Submission, t: Truth) -> dict:
    m = {}
    for ref, cols in t.states.items():
        tag = "" if ref == "1205ic" else f"_{ref}"
        for k in FIELDS:
            key = f"A.state_rmse{tag}.{k}"
            if sub.state is None:
                m[key] = bad("missing", sub.errors.get("initial_state.csv"))
                continue
            cov = sub.state_cov[k]
            if cov < COVERAGE:
                m[key] = bad("incomplete", f"{cov:.1%} of nodes numeric")
                continue
            pairs = [(s, r) for s, r in zip(sub.state[k], cols[k]) if s is not None and r is not None]
            m[key] = ok(_rmse(pairs), n=len(pairs))
    return m


def _az_err(a, b):
    d = abs((a - b) % 180.0)
    return min(d, 180.0 - d)


def score_summary(sub: Submission, t: Truth) -> dict:
    m = {}
    s = sub.summary
    ts = t.summary
    if not isinstance(s, dict):
        why = sub.errors.get("state.json", "not a JSON object")
        for k in ("A.shmax_azimuth_err_deg", "A.stress_regime_match"):
            m[k] = bad("missing", why)
        for k in FIELDS:
            m[f"A.gradient_relerr.{k}"] = bad("missing", why)
        return m
    az = _finite(s.get("SHmax_azimuth_deg"))
    m["A.shmax_azimuth_err_deg"] = (ok(_az_err(az, ts["SHmax_azimuth_deg"]), submitted=az)
                                    if az is not None else bad("missing", "SHmax_azimuth_deg"))
    reg = s.get("stress_regime")
    m["A.stress_regime_match"] = (ok(1.0 if str(reg).strip().lower() == ts["stress_regime"] else 0.0,
                                     submitted=reg) if reg else bad("missing", "stress_regime"))
    g = s.get("gradients_per_km") if isinstance(s.get("gradients_per_km"), dict) else {}
    for k in FIELDS:
        v = _finite(g.get(k))
        tv = ts["gradients_per_km"][k]
        m[f"A.gradient_relerr.{k}"] = (ok(abs(v - tv) / abs(tv), submitted=v) if v is not None
                                       else bad("missing", f"gradients_per_km.{k}"))
    return m


def score_properties(sub: Submission, t: Truth) -> dict:
    m = {}
    tp = t.summary["properties"]
    p = sub.props if isinstance(sub.props, dict) else None
    hits, total, rel, logk = 0, 0, [], []
    for unit in UNITS:
        for prop in PROPS:
            key = f"A.prop.{unit}.{prop}"
            truths = tp[unit][prop]
            d = (p or {}).get(unit, {}).get(prop) if p else None
            v = _finite(d.get("value")) if isinstance(d, dict) else _finite(d)
            if v is None or (prop == "permeability_m2" and v <= 0):
                m[key] = bad("missing", sub.errors.get("properties.json", f"{unit}.{prop}.value"))
                continue
            if prop == "permeability_m2":
                err = min(abs(math.log10(v) - math.log10(tv)) for tv in truths)
                logk.append(err)
                m[key] = ok(err, unit_of_error="orders of magnitude", submitted=v)
            else:
                err = min(abs(v - tv) / abs(tv) for tv in truths)
                rel.append(err)
                m[key] = ok(err, unit_of_error="relative", submitted=v)
            lo = _finite(d.get("low")) if isinstance(d, dict) else None
            hi = _finite(d.get("high")) if isinstance(d, dict) else None
            total += 1
            if lo is not None and hi is not None and any(lo <= tv <= hi for tv in truths):
                hits += 1
    n_expected = len(UNITS) * len(PROPS)
    m["A.prop_log10k_mae"] = ok(sum(logk) / len(logk), n=len(logk)) if len(logk) == 2 else bad(
        "missing" if not logk else "incomplete", f"{len(logk)}/2 permeabilities")
    n_rel = n_expected - 2
    m["A.prop_relerr_mean"] = ok(sum(rel) / len(rel), n=len(rel)) if len(rel) == n_rel else bad(
        "missing" if not rel else "incomplete", f"{len(rel)}/{n_rel} properties")
    m["A.prop_range_hit_frac"] = ok(hits / n_expected, n=total) if total == n_expected else bad(
        "missing" if not total else "incomplete", f"{total}/{n_expected} properties")
    return m


# ---------------------------------------------------------------- axis B
def score_wells(sub: Submission, t: Truth) -> dict:
    m = {}
    wells = (t.wells or {}).get("wells", {})
    errs = []
    for name, w in wells.items():
        g = w.get("granitoid_top") or {}
        key = f"B.contact_err_m.{name}"
        if sub.surface is None:
            m[key] = bad("missing", sub.errors.get("granitoid_top.csv"))
            continue
        zs = sub.surface_at(g["x"], g["y"])
        if zs is None:
            m[key] = bad("n/a", "surface does not cover the well")
            continue
        e = zs - g["z_elev_m"]
        errs.append(e)
        m[key] = ok(e, note="predicted minus observed elevation; + = predicted too shallow",
                    source_spread_m=g.get("source_spread_m"))
    if sub.surface is None:
        m["B.contact_mae_m"] = bad("missing", sub.errors.get("granitoid_top.csv"))
    elif len(errs) < len(wells):
        m["B.contact_mae_m"] = bad("incomplete", f"{len(errs)}/{len(wells)} wells covered")
    else:
        m["B.contact_mae_m"] = ok(sum(abs(e) for e in errs) / len(errs), n=len(errs))

    pooled = []
    for name, w in wells.items():
        T = w.get("temperature") or {}
        key = f"B.T_rmse_C.{name}"
        if sub.state is None:
            m[key] = bad("missing", sub.errors.get("initial_state.csv"))
            continue
        if sub.state_cov.get("T_C", 0) < COVERAGE:
            m[key] = bad("incomplete", "T_C below coverage")
            continue
        pairs = []
        for x, y, z, tc, inside in zip(T["x"], T["y"], T["z_elev_m"], T["T_C"], T["inside_1205_grid"]):
            if not inside:
                continue
            v = t.lattice.trilinear(sub.state["T_C"], x, y, z)
            if v is not None:
                pairs.append((v, tc))
        if not pairs:
            m[key] = bad("n/a", "no log points inside the grid")
            continue
        conf = T.get("confidence", "")
        m[key] = ok(_rmse(pairs), n=len(pairs), confidence=conf, log_date=T.get("date"))
        if conf not in LOW_CONFIDENCE_T:
            pooled.extend(pairs)
    if sub.state is None:
        m["B.T_rmse_C"] = bad("missing", sub.errors.get("initial_state.csv"))
    elif pooled:
        m["B.T_rmse_C"] = ok(_rmse(pooled), n=len(pooled), note="pooled over wells with T confidence != low")
    else:
        m["B.T_rmse_C"] = bad("incomplete", "no scorable T points")
    return m


# ---------------------------------------------------------------- driver
def score(sub_dir: str | Path, truth: Truth) -> dict:
    sub = Submission(sub_dir, truth.lattice)
    metrics = {}
    for fn in (score_lithology, score_surface, score_state, score_summary, score_properties, score_wells):
        metrics.update(fn(sub, truth))
    files = {f: (sub.root / f).is_file() for f in
             ("lithology.csv", "granitoid_top.csv", "initial_state.csv", "state.json",
              "properties.json", "MODEL_REPORT.md")}
    return {"submission": str(sub.root), "files_present": files, "parse_errors": sub.errors,
            "metrics": metrics}


def attach_baseline(result: dict, baseline: dict, name: str = "naive") -> dict:
    """Put the baseline's value next to every metric (``<name>`` key)."""
    for k, v in result["metrics"].items():
        b = baseline["metrics"].get(k, {})
        v[name] = b.get("value") if b.get("status") == "ok" else b.get("status", "missing")
        v["higher_is_better"] = k in HIGHER_IS_BETTER
    return result


HEADLINE = [
    ("A.lith_balanced_accuracy", "lithology balanced accuracy"),
    ("A.contact_rmse_m", "contact RMSE vs 1205 (m)"),
    ("A.state_rmse.T_C", "T RMSE vs 1205 (°C)"),
    ("A.state_rmse.P_MPa", "P RMSE (MPa)"),
    ("A.state_rmse.Sv_MPa", "Sv RMSE (MPa)"),
    ("A.state_rmse.SHmax_MPa", "SHmax RMSE (MPa)"),
    ("A.state_rmse.Shmin_MPa", "Shmin RMSE (MPa)"),
    ("A.shmax_azimuth_err_deg", "SHmax azimuth error (°)"),
    ("A.stress_regime_match", "stress regime match"),
    ("A.prop_log10k_mae", "permeability error (log10)"),
    ("A.prop_relerr_mean", "other properties, mean rel. error"),
    ("B.contact_mae_m", "blind-well contact MAE (m)"),
    ("B.T_rmse_C", "blind-well T RMSE (°C)"),
]


def fmt(v) -> str:
    if v is None:
        return "–"
    if isinstance(v, str):
        return v
    if abs(v) >= 100:
        return f"{v:.0f}"
    if abs(v) >= 10:
        return f"{v:.1f}"
    return f"{v:.3g}"


def headline_table(results: dict[str, dict]) -> str:
    names = list(results)
    lines = ["| metric | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for key, label in HEADLINE:
        cells = []
        for n in names:
            mv = results[n]["metrics"].get(key, {})
            cells.append(fmt(mv.get("value")) if mv.get("status") == "ok" else mv.get("status", "missing"))
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    return "\n".join(lines)
