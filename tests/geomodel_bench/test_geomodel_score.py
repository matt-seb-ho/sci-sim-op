"""Scorer tests on a small synthetic site (no FORGE data needed)."""
import csv
import json
import math
import shutil

import pytest

from geomodel_bench import baselines
from geomodel_bench.grid import FORGE_1205, Lattice
from geomodel_bench.score import attach_baseline, score
from geomodel_bench.truth import FIELDS, PROPS, UNITS, load_truth

LAT = Lattice(x0=1000.0, y0=2000.0, z0=0.0, azimuth_deg=25.0, spacing=50.0, ni=7, nj=6, nk=8)
GROUND = 400.0


def contact_z(x, y):
    """Truth contact: dips to the west (smaller x), 150-250 m."""
    return 150.0 + 0.2 * (x - 1000.0)


def write(p, header, rows):
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


@pytest.fixture()
def truth_dir(tmp_path):
    d = tmp_path / "truth"
    d.mkdir()
    import dataclasses
    (d / "grid.json").write_text(json.dumps(dataclasses.asdict(LAT)))
    rows = []
    for c in range(LAT.n_cells):
        x, y, z = LAT.cell_xyz(c)
        rows.append((c, "granitoid" if z < contact_z(x, y) else "basin_fill"))
    write(d / "lithology.csv", ["cell_id", "unit"], rows)
    st = []
    for n in range(LAT.n_nodes):
        x, y, z = LAT.node_xyz(n)
        dep = GROUND - z
        st.append((n, 20 + 0.07 * dep, 0.0098 * dep, 0.025 * dep, 0.018 * dep, 0.015 * dep, dep))
    write(d / "state_1205ic.csv", ["node_id", *FIELDS, "depth_m"], st)
    props = {u: {p: [1.0 + i] for i, p in enumerate(PROPS)} for u in UNITS}
    props["granitoid"]["permeability_m2"] = [1e-17]
    props["basin_fill"]["permeability_m2"] = [1e-14]
    (d / "summary.json").write_text(json.dumps({
        "SHmax_azimuth_deg": 25.0, "stress_regime": "normal",
        "gradients_per_km": {"T_C": 70.0, "P_MPa": 9.8, "Sv_MPa": 25.0, "SHmax_MPa": 18.0, "Shmin_MPa": 15.0},
        "properties": props}))
    # one blind well, vertical, at a point inside the grid
    wx, wy = LAT.to_global(120.0, 110.0)
    zs = [300.0 - 10 * i for i in range(20)]
    wells = {"wells": {"W1": {
        "granitoid_top": {"x": wx, "y": wy, "z_elev_m": contact_z(wx, wy), "source_spread_m": 5},
        "temperature": {"x": [wx] * 20, "y": [wy] * 20, "z_elev_m": zs,
                        "T_C": [20 + 0.07 * (GROUND - z) for z in zs],
                        "inside_1205_grid": [True] * 20, "confidence": "high"}}},
        "reference_wells": {}}
    (d / "blind_wells.json").write_text(json.dumps(wells))
    return d


@pytest.fixture()
def truth(truth_dir):
    return load_truth(truth_dir)


@pytest.fixture()
def perfect(tmp_path, truth):
    return baselines.write_expert(tmp_path / "perfect", truth)


def m(res, key):
    return res["metrics"][key]


def test_lattice_roundtrip():
    for n in (0, 1, 51, 2601, FORGE_1205.n_nodes - 1):
        x, y, z = FORGE_1205.node_xyz(n)
        u, v = FORGE_1205.to_local(x, y)
        assert abs(u - (n % 51) * 50) < 1e-6 and abs(v - ((n // 51) % 51) * 50) < 1e-6
    # node 1 is 50 m along the rotated axis: bearing 115 degrees
    x0, y0, _ = FORGE_1205.node_xyz(0)
    x1, y1, _ = FORGE_1205.node_xyz(1)
    assert math.degrees(math.atan2(x1 - x0, y1 - y0)) % 360 == pytest.approx(115.0)


def test_trilinear_exact_for_linear_field():
    vals = [LAT.node_xyz(n)[2] * 2 + 1 for n in range(LAT.n_nodes)]
    x, y = LAT.to_global(77.0, 33.0)
    assert LAT.trilinear(vals, x, y, 123.0) == pytest.approx(247.0)
    assert LAT.trilinear(vals, x, y, 10_000.0) is None


def test_perfect_submission(perfect, truth):
    res = score(perfect, truth)
    assert m(res, "A.lith_balanced_accuracy")["value"] == 1.0
    assert m(res, "A.contact_from_lithology_rmse_m")["value"] == 0.0
    for k in FIELDS:
        assert m(res, f"A.state_rmse.{k}")["value"] == pytest.approx(0.0, abs=1e-9)
    assert m(res, "A.shmax_azimuth_err_deg")["value"] == 0.0
    assert m(res, "A.stress_regime_match")["value"] == 1.0
    assert m(res, "A.prop_log10k_mae")["value"] == pytest.approx(0.0)
    assert m(res, "A.prop_relerr_mean")["value"] == pytest.approx(0.0)
    assert m(res, "A.prop_range_hit_frac")["value"] == 1.0
    assert m(res, "B.T_rmse_C")["value"] == pytest.approx(0.0, abs=1e-6)
    # the surface is resampled on the 50 m map grid: small but not zero error
    assert m(res, "A.contact_rmse_m")["value"] < 30
    assert abs(m(res, "B.contact_err_m.W1")["value"]) < 30


def test_flipped_labels(tmp_path, truth):
    sub = baselines.write_perfect_flipped(tmp_path / "flip", truth)
    res = score(sub, truth)
    assert m(res, "A.lith_balanced_accuracy")["value"] == 0.0
    assert m(res, "A.contact_from_lithology_rmse_m")["value"] > 50


@pytest.mark.parametrize("fname", ["lithology.csv", "granitoid_top.csv", "initial_state.csv",
                                   "state.json", "properties.json"])
def test_missing_file_is_missing_not_zero(perfect, truth, fname):
    (perfect / fname).unlink()
    res = score(perfect, truth)
    affected = {
        "lithology.csv": ["A.lith_balanced_accuracy", "A.contact_from_lithology_rmse_m"],
        "granitoid_top.csv": ["A.contact_rmse_m", "B.contact_mae_m", "B.contact_err_m.W1"],
        "initial_state.csv": [f"A.state_rmse.{k}" for k in FIELDS] + ["B.T_rmse_C", "B.T_rmse_C.W1"],
        "state.json": ["A.shmax_azimuth_err_deg", "A.stress_regime_match"]
                      + [f"A.gradient_relerr.{k}" for k in FIELDS],
        "properties.json": ["A.prop_log10k_mae", "A.prop_relerr_mean", "A.prop_range_hit_frac"]
                           + [f"A.prop.{u}.{p}" for u in UNITS for p in PROPS],
    }[fname]
    for key in affected:
        assert m(res, key)["status"] == "missing", key
        assert "value" not in m(res, key), key
    assert res["files_present"][fname] is False


def test_empty_directory_scores_nothing(tmp_path, truth):
    res = score(tmp_path / "does_not_exist", truth)
    assert all(v["status"] != "ok" for v in res["metrics"].values())


def test_garbage_files_do_not_crash(perfect, truth):
    (perfect / "lithology.csv").write_text("not,a\ncsv file at all\n")
    (perfect / "state.json").write_text("{not json")
    (perfect / "initial_state.csv").write_text("node_id,T_C\n0,abc\n")
    res = score(perfect, truth)
    assert m(res, "A.lith_balanced_accuracy")["status"] == "missing"
    assert m(res, "A.shmax_azimuth_err_deg")["status"] == "missing"
    assert m(res, "A.state_rmse.T_C")["status"] == "missing"


def test_partial_rows_are_incomplete(perfect, truth):
    rows = (perfect / "initial_state.csv").read_text().splitlines()
    (perfect / "initial_state.csv").write_text("\n".join(rows[: len(rows) // 2]) + "\n")
    res = score(perfect, truth)
    assert m(res, "A.state_rmse.T_C")["status"] == "incomplete"
    assert m(res, "B.T_rmse_C.W1")["status"] == "incomplete"


def test_nan_values_do_not_count_as_zero_error(perfect, truth):
    p = perfect / "initial_state.csv"
    rows = list(csv.reader(p.open()))
    for r in rows[1:]:
        r[1] = "nan"
    write(p, rows[0], rows[1:])
    res = score(perfect, truth)
    assert m(res, "A.state_rmse.T_C")["status"] == "incomplete"
    assert m(res, "A.state_rmse.P_MPa")["status"] == "ok"


def test_known_errors(perfect, truth):
    # +10 C everywhere -> RMSE 10; azimuth 115 == 25 + 90 -> 90 deg; 205 == 25 mod 180 -> 0
    p = perfect / "initial_state.csv"
    rows = list(csv.reader(p.open()))
    for r in rows[1:]:
        r[1] = str(float(r[1]) + 10)
    write(p, rows[0], rows[1:])
    s = json.loads((perfect / "state.json").read_text())
    s["SHmax_azimuth_deg"] = 115.0
    (perfect / "state.json").write_text(json.dumps(s))
    res = score(perfect, truth)
    assert m(res, "A.state_rmse.T_C")["value"] == pytest.approx(10.0)
    assert m(res, "B.T_rmse_C")["value"] == pytest.approx(10.0)
    assert m(res, "A.shmax_azimuth_err_deg")["value"] == pytest.approx(90.0)
    s["SHmax_azimuth_deg"] = 205.0
    (perfect / "state.json").write_text(json.dumps(s))
    assert m(score(perfect, truth), "A.shmax_azimuth_err_deg")["value"] == pytest.approx(0.0)


def test_surface_offset_is_measured(perfect, truth):
    p = perfect / "granitoid_top.csv"
    rows = list(csv.reader(p.open()))
    for r in rows[1:]:
        r[2] = str(float(r[2]) + 40.0)
    write(p, rows[0], rows[1:])
    res = score(perfect, truth)
    assert m(res, "B.contact_err_m.W1")["value"] == pytest.approx(40.0, abs=30)
    assert m(res, "A.contact_rmse_m")["bias_m"] == pytest.approx(40.0, abs=15)


def test_baseline_attached_next_to_every_metric(tmp_path, perfect, truth):
    other = shutil.copytree(perfect, tmp_path / "other")
    (other / "properties.json").unlink()
    res = attach_baseline(score(perfect, truth), score(other, truth))
    for key, v in res["metrics"].items():
        assert "naive" in v, key
    assert res["metrics"]["A.prop_log10k_mae"]["naive"] == "missing"
