#!/usr/bin/env python3
"""Champion vs seed, paired per (task, seed) cell. Never a bare mean.

The comparison this campaign exists to make. Paired because the arms run the
*same* tasks at the *same* seeds, so the cell-wise difference removes
between-task variance -- which on this pool spans two orders of magnitude and
would otherwise swamp any effect.

Three things it refuses to do:

* **Pair across a harness error.** A cell where either arm hit infrastructure is
  dropped, not zero-filled (F8).
* **Report a delta without the MDE.** On this pool the arm-vs-arm minimum
  detectable effect is ~0.058 at n=6 seeds; a delta below that is not evidence
  of anything, and printing it alone invites the reader to believe it.
* **Average over cells that are not paired.** Unequal cells silently become an
  unpaired comparison wearing a paired label.

    uv run python scripts/paired_champion.py --champion cand_xxx [--seed-cid cand_yyy]
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=REPO / ".evolve" / "geos_search")
    ap.add_argument("--champion", required=True)
    ap.add_argument("--seed-cid", default=None,
                    help="default: the candidate with the most rollouts that is "
                         "not the champion")
    ap.add_argument("--model", default="z-ai/glm-5.3-flash")
    ap.add_argument("--mde", type=float, default=None,
                    help="arm-vs-arm MDE to print beside the result; read from "
                         "pool.json when omitted")
    args = ap.parse_args()

    rows = [json.loads(l) for l in (args.out / "rollouts.jsonl").read_text().splitlines() if l.strip()]
    rows = [r for r in rows if r.get("model") == args.model]

    cells: dict[str, dict[tuple[str, int], float]] = defaultdict(dict)
    dropped: list[str] = []
    for r in rows:
        s = r.get("score") or {}
        cid = r.get("candidate_id")
        key = (r["task"], int(r["seed"]))
        if s.get("status") == "harness_error":
            dropped.append(f"{cid} {key[0]}/seed{key[1]} (harness error)")
            continue
        cells[cid][key] = float(s["value"])

    champ = args.champion
    if champ not in cells:
        print(f"no rollouts for champion {champ!r}; have {sorted(cells)}")
        return 1
    seed_cid = args.seed_cid or max(
        (c for c in cells if c != champ), key=lambda c: len(cells[c]), default=None)
    if seed_cid is None:
        print("no seed candidate to compare against")
        return 1

    shared = sorted(set(cells[champ]) & set(cells[seed_cid]))
    if not shared:
        print(f"no paired cells between {champ} and {seed_cid}")
        return 1

    mde = args.mde
    if mde is None:
        pool = args.out / "pool.json"
        if pool.is_file():
            mde = json.loads(pool.read_text()).get("mde_kept_two_arm")

    print(f"champion {champ}   vs   seed {seed_cid}   model {args.model}")
    print(f"{len(shared)} paired cell(s); {len(dropped)} dropped\n")
    print(f"{'task':<32}{'seed':>5}{'seed_score':>12}{'champion':>11}{'delta':>10}")
    deltas = []
    for task, sd in shared:
        a = cells[seed_cid][(task, sd)]
        b = cells[champ][(task, sd)]
        deltas.append(b - a)
        print(f"{task:<32}{sd:5d}{a:12.4f}{b:11.4f}{b - a:+10.4f}")

    md = statistics.mean(deltas)
    sd_ = statistics.stdev(deltas) if len(deltas) > 1 else 0.0
    half = 1.96 * sd_ / math.sqrt(len(deltas)) if len(deltas) > 1 else float("nan")
    print(f"\npaired mean delta {md:+.4f}"
          + (f"   95% CI [{md - half:+.4f}, {md + half:+.4f}]" if len(deltas) > 1 else "")
          + f"   n={len(deltas)} cells")
    if len(deltas) > 1:
        spans = (md - half) * (md + half) <= 0
        print("CI spans zero:", spans)
    if mde:
        print(f"arm-vs-arm MDE on this pool: {mde:.4f}"
              f"  ->  |delta| {abs(md):.4f} is "
              f"{'BELOW' if abs(md) < mde else 'above'} it")
        if abs(md) < mde:
            print("   A delta below the MDE is not evidence of an effect in either "
                  "direction. Report it as 'no detectable difference', not as a win "
                  "or a loss.")
    for d in dropped:
        print(f"   dropped: {d}")
    (args.out / "paired_champion.json").write_text(json.dumps({
        "champion": champ, "seed": seed_cid, "model": args.model,
        "cells": [{"task": t, "seed": s,
                   "seed_score": cells[seed_cid][(t, s)],
                   "champion_score": cells[champ][(t, s)],
                   "delta": cells[champ][(t, s)] - cells[seed_cid][(t, s)]}
                  for t, s in shared],
        "paired_mean_delta": md,
        "ci95": [md - half, md + half] if len(deltas) > 1 else None,
        "n_cells": len(deltas), "mde_two_arm": mde, "dropped": dropped,
    }, indent=2))
    print(f"\n-> {args.out / 'paired_champion.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
