#!/usr/bin/env python3
"""Apply the RESEARCH_PROGRAM.md inclusion criteria to a screening corpus.

Emits the study set, the per-family split assignment, and the achievable MDE, so
task selection is a reproducible consequence of measurement rather than a choice.
"""
from __future__ import annotations
import argparse, collections, json, math, statistics
from pathlib import Path

# RESEARCH_PROGRAM.md 3.3. A family lives entirely in one split.
FAMILY_RULES = [
    ("fracture",    ("kgd", "pennyFrac", "pkn", "Sneddon", "TFrac", "Proppant",
                     "singleFracCompression", "HydraulicFracture")),
    ("flow",        ("buckleyLeverett", "LeakyWell", "SPE11b", "CO2FieldCase",
                     "DeadOil", "HystInjection")),
    ("poroelastic", ("Mandel", "Thermoporoelastic", "Poroelasticity", "faultVerification")),
    ("driver",      ("triaxialDriver", "relaxationTest")),
]
SPLIT_OF_FAMILY = {"wellbore": "TRAIN", "driver": "TRAIN",
                   "fracture": "DEV", "poroelastic": "DEV", "flow": "TEST"}

def family(task: str) -> str:
    for fam, keys in FAMILY_RULES:
        if any(k.lower() in task.lower() for k in keys):
            return fam
    return "wellbore"          # the residual family; every remaining task is one

def load(paths):
    by = collections.defaultdict(list)
    err = collections.Counter()
    for p in paths:
        for line in open(p):
            r = json.loads(line)
            s = r.get("score")
            v = s.get("value") if isinstance(s, dict) else s
            status = s.get("status") if isinstance(s, dict) else None
            if status == "harness_error":
                err[r["task"]] += 1
                continue
            if isinstance(v, (int, float)):
                by[r["task"]].append(v)
    return by, err

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("corpora", nargs="+", type=Path)
    ap.add_argument("--max-mean", type=float, default=0.90)
    ap.add_argument("--min-mean", type=float, default=0.05)
    ap.add_argument("--max-sd", type=float, default=0.30)
    a = ap.parse_args()

    by, err = load(a.corpora)
    rows = []
    for t, v in by.items():
        m = statistics.mean(v)
        sd = statistics.stdev(v) if len(v) > 1 else None
        zr = sum(1 for x in v if x == 0.0) / len(v)
        reasons = []
        if m > a.max_mean: reasons.append(f"ceiling(mean {m:.2f})")
        if m < a.min_mean: reasons.append(f"floor(mean {m:.2f})")
        if sd is not None and sd > a.max_sd: reasons.append(f"noisy(sd {sd:.2f})")
        if len(v) < 2: reasons.append("n<2")
        rows.append(dict(task=t, fam=family(t), n=len(v), mean=m, sd=sd, zero=zr,
                         err=err.get(t, 0), include=not reasons, why=";".join(reasons)))

    rows.sort(key=lambda r: (r["fam"], -r["mean"]))
    print(f"{'task':<52}{'family':<13}{'split':<7}{'n':>3}{'mean':>8}{'sd':>8}{'zero':>7}  verdict")
    for r in rows:
        sd = f"{r['sd']:.3f}" if r["sd"] is not None else "  -  "
        print(f"{r['task'][:52]:<52}{r['fam']:<13}{SPLIT_OF_FAMILY[r['fam']]:<7}"
              f"{r['n']:>3}{r['mean']:>8.3f}{sd:>8}{r['zero']:>7.2f}  "
              f"{'INCLUDE' if r['include'] else 'exclude: ' + r['why']}")

    inc = [r for r in rows if r["include"]]
    print(f"\n=== {len(inc)} of {len(rows)} tasks pass ===")
    fam = collections.Counter(r["fam"] for r in inc)
    for f, n in sorted(fam.items()):
        print(f"  {f:<13}{SPLIT_OF_FAMILY[f]:<7}{n:>3} eligible")
    for split in ("TRAIN", "DEV", "TEST"):
        n = sum(v for f, v in fam.items() if SPLIT_OF_FAMILY[f] == split)
        print(f"  -> {split:<6}{n:>3} tasks")

    sds = [r["sd"] for r in inc if r["sd"] is not None]
    if sds:
        pooled = statistics.mean(sds)
        print(f"\npooled sd over included tasks: {pooled:.3f}")
        for cells in (12, 24, 36, 48):
            print(f"  MDE @ {cells:>2} cells: {1.96*pooled/math.sqrt(cells):.4f}")
        print(f"  cells needed for MDE 0.05: {math.ceil((1.96*pooled/0.05)**2)}")
        print("\n(paired designs see a LOWER sd than this: the arms share the task,"
              "\n so treat these as a conservative upper bound on MDE.)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
