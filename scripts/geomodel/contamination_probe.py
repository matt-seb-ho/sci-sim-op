#!/usr/bin/env python3
"""Contamination probe (TASK_FORGE_v0 §6): what does the model know about FORGE with no data?

Asks the pilot model, with no tools and no files, for the FORGE-v0 quantities it can
give from memory, turns the answer into a submission (a planar contact, linear
gradients below the 58-32 ground level, the given properties), and scores it with
the same scorer.

    python3 scripts/geomodel/contamination_probe.py --samples 3
Key from .env (OPENROUTER_API_KEY); never printed. Outputs under
/data/matt/sci-sim-op/geomodel/forge/runs/probe_<i>/.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
from geomodel_bench import score as S  # noqa: E402
from geomodel_bench.truth import FIELDS, PROPS, UNITS, load_truth  # noqa: E402

FORGE = Path("/data/matt/sci-sim-op/geomodel/forge")
MODEL = "xiaomi/mimo-v2.6-flash"
# Well 58-32 location: an input the agent also has (GDR 1153 / 1006). Needed to place the answer.
X58, Y58, GROUND58 = 335451.0, 4263037.0, 1685.0

PROMPT = """You are a geoscientist. Answer from your own knowledge only; you have no data files,
no tools and no internet.

Site: the Utah FORGE enhanced-geothermal-system site near Milford, Utah, as understood
in August 2019. Coordinates are UTM zone 12N (NAD83); well 58-32 is at about
x = 335,451 m, y = 4,263,037 m, ground elevation about 1,685 m above sea level.

Give your best estimates for the reservoir volume around well 58-32 (roughly 0.4-3.2 km
depth). If you do not know a value, still give your best estimate and say so in "notes".
Return ONLY a JSON object with exactly these keys:

{
 "contact_depth_m_at_58_32": <depth below ground of the top of the crystalline basement (granitoid) under the basin-fill sediments at well 58-32, m>,
 "contact_dip_deg": <dip of that contact surface, degrees>,
 "contact_dip_direction_deg": <azimuth the contact dips toward, degrees clockwise from north>,
 "surface_T_C": <temperature at the ground surface, C>,
 "T_gradient_C_per_km": <average temperature gradient with depth, C/km>,
 "P_gradient_MPa_per_km": <pore pressure gradient, MPa/km>,
 "Sv_gradient_MPa_per_km": <vertical stress gradient>,
 "SHmax_gradient_MPa_per_km": <maximum horizontal stress gradient>,
 "Shmin_gradient_MPa_per_km": <minimum horizontal stress gradient>,
 "SHmax_azimuth_deg": <azimuth of the maximum horizontal stress, 0-180>,
 "stress_regime": <"normal" | "strike-slip" | "reverse">,
 "properties": {
   "granitoid":  {"permeability_m2": {"value": ..., "low": ..., "high": ...}, "porosity": {...},
                  "youngs_modulus_GPa": {...}, "poissons_ratio": {...}, "density_kg_m3": {...},
                  "thermal_conductivity_W_mK": {...}},
   "basin_fill": {same six keys}
 },
 "confidence": <"low" | "medium" | "high">,
 "notes": <one or two sentences on what you actually remember about this site>
}"""


def call(prompt: str, seed: int) -> dict:
    key = os.environ["OPENROUTER_API_KEY"]
    base = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
    body = json.dumps({"model": MODEL, "messages": [{"role": "user", "content": prompt}],
                       "seed": seed, "max_tokens": 60000, "reasoning": {"effort": "medium"},
                       "usage": {"include": True}}).encode()
    req = urllib.request.Request(base + "/chat/completions", data=body, headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read())


def parse(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0))


def to_submission(ans: dict, out: Path, lat) -> None:
    out.mkdir(parents=True, exist_ok=True)
    zc0 = GROUND58 - float(ans["contact_depth_m_at_58_32"])
    dip = math.radians(float(ans.get("contact_dip_deg") or 0.0))
    ddir = math.radians(float(ans.get("contact_dip_direction_deg") or 0.0))

    def zc(x, y):  # plane through (58-32, zc0), going down toward ddir
        along = (x - X58) * math.sin(ddir) + (y - Y58) * math.cos(ddir)
        return zc0 - along * math.tan(dip)

    with open(out / "lithology.csv", "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["cell_id", "unit"])
        for c in range(lat.n_cells):
            x, y, z = lat.cell_xyz(c)
            w.writerow([c, "granitoid" if z < zc(x, y) else "basin_fill"])
    with open(out / "granitoid_top.csv", "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["x", "y", "z_top"])
        for x in range(332000, 338001, 50):
            for y in range(4260000, 4266001, 50):
                w.writerow([x, y, round(zc(x, y), 2)])
    g = {k: float(ans[k]) for k in ("T_gradient_C_per_km", "P_gradient_MPa_per_km", "Sv_gradient_MPa_per_km",
                                    "SHmax_gradient_MPa_per_km", "Shmin_gradient_MPa_per_km")}
    t0 = float(ans.get("surface_T_C") or 10.0)
    with open(out / "initial_state.csv", "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["node_id", *FIELDS])
        for n in range(lat.n_nodes):
            d = max(GROUND58 - lat.node_xyz(n)[2], 0.0) / 1000.0
            w.writerow([n, round(t0 + g["T_gradient_C_per_km"] * d, 3), round(g["P_gradient_MPa_per_km"] * d, 4),
                        round(g["Sv_gradient_MPa_per_km"] * d, 4), round(g["SHmax_gradient_MPa_per_km"] * d, 4),
                        round(g["Shmin_gradient_MPa_per_km"] * d, 4)])
    (out / "state.json").write_text(json.dumps({
        "SHmax_azimuth_deg": ans.get("SHmax_azimuth_deg"), "stress_regime": ans.get("stress_regime"),
        "gradients_per_km": {"T_C": g["T_gradient_C_per_km"], "P_MPa": g["P_gradient_MPa_per_km"],
                             "Sv_MPa": g["Sv_gradient_MPa_per_km"], "SHmax_MPa": g["SHmax_gradient_MPa_per_km"],
                             "Shmin_MPa": g["Shmin_gradient_MPa_per_km"]}}, indent=1))
    (out / "properties.json").write_text(json.dumps(ans.get("properties", {}), indent=1))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=3)
    a = ap.parse_args()
    truth = load_truth(FORGE / "truth")
    naive = S.score(FORGE / "baselines" / "naive", truth)
    for i in range(1, a.samples + 1):
        run = FORGE / "runs" / f"probe_{i}"
        run.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        resp = call(PROMPT, seed=i)
        (run / "response.json").write_text(json.dumps(resp, indent=1))
        (run / "prompt.txt").write_text(PROMPT)
        text = resp["choices"][0]["message"]["content"] or ""
        usage = resp.get("usage", {})
        try:
            ans = parse(text)
            (run / "answer.json").write_text(json.dumps(ans, indent=1))
            to_submission(ans, run / "submission", truth.lattice)
            res = S.attach_baseline(S.score(run / "submission", truth), naive)
            (run / "score.json").write_text(json.dumps(res, indent=1))
            status = "scored"
        except Exception as e:  # noqa: BLE001
            status = f"unparseable: {type(e).__name__}: {e}"
        print(json.dumps({"probe": i, "status": status, "secs": round(time.time() - t0, 1),
                          "cost": usage.get("cost"), "tokens": usage.get("total_tokens")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
