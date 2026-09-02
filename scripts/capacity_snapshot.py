#!/usr/bin/env python3
"""Record what else was running on this box while an arm ran.

Wall-clock numbers from a shared machine are not a property of the model. On
2026-09-02 this box carried a 15-minute load average of **119.98 on 128 cores**
from SimWorld / SimWorldEditor processes owned by five other users, with no
`geosx` among them. Timeouts measured under that are partly other people's load,
and a reader cannot discount what was never recorded -- so it is recorded, per
arm, and the report names it as a threat to every wall-clock figure.

    uv run python scripts/capacity_snapshot.py --arm search --out .evolve/geos_search
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path


def snapshot(arm: str) -> dict:
    try:
        one, five, fifteen = os.getloadavg()
    except OSError:
        one = five = fifteen = float("nan")
    ncpu = os.cpu_count() or 0
    top: list[dict] = []
    try:
        out = subprocess.run(
            ["ps", "-eo", "user,pcpu,comm", "--sort=-pcpu"],
            capture_output=True, text=True, timeout=15,
        ).stdout.splitlines()[1:9]
        for line in out:
            parts = line.split(None, 2)
            if len(parts) == 3:
                top.append({"user": parts[0], "pcpu": float(parts[1]), "comm": parts[2]})
    except Exception:  # noqa: BLE001 - a snapshot must never break an arm
        pass
    mine = sum(t["pcpu"] for t in top if t["user"] == os.environ.get("USER", "matt"))
    return {
        "ts": int(time.time()),
        "kind": "capacity",
        "arm": arm,
        "nproc": ncpu,
        "loadavg_1m": round(one, 2),
        "loadavg_5m": round(five, 2),
        "loadavg_15m": round(fifteen, 2),
        "load_per_core_15m": round(fifteen / ncpu, 3) if ncpu else None,
        "top_cpu": top,
        "our_pcpu_cores": round(mine / 100.0, 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arm", required=True)
    ap.add_argument("--out", type=Path,
                    default=Path(__file__).resolve().parents[1] / ".evolve" / "geos_search")
    args = ap.parse_args()
    snap = snapshot(args.arm)
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "capacity.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(snap) + "\n")
    print(json.dumps(snap, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
