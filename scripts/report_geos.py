#!/usr/bin/env python3
"""Recompute every number from the rollout corpus. Costs nothing.

The rollouts are the expensive part; the statistics are free. Keeping the report
separate from the run means any question asked *after* the run -- a different
noise band, an added baseline, a corrected bug, a slice recut -- is answered
without spending another rollout. Without that separation the answer to a
follow-up question is "we will not re-run it", which is the same as not asking.

    python3 scripts/report_geos.py --out .evolve/geos_search
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


def load(corpus: Path) -> list[dict]:
    if not corpus.is_file():
        return []
    out = []
    for line in corpus.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue          # a truncated last line is what a crash looks like
    return out


def status_of(rec: dict) -> str:
    return (rec.get("score") or {}).get("status", "?")


def value_of(rec: dict) -> float:
    return float((rec.get("score") or {}).get("value", 0.0))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=REPO / ".evolve" / "geos_search")
    args = ap.parse_args()
    records = load(args.out / "rollouts.jsonl")
    if not records:
        print(f"no rollouts in {args.out / 'rollouts.jsonl'}")
        return 1

    # Infrastructure failures are separated everywhere, not averaged in. A
    # harness error is not evidence about a candidate (worklog §5.3, §8.3).
    infra = [r for r in records if status_of(r) == "harness_error"]
    scored = [r for r in records if status_of(r) != "harness_error"]

    print(f"corpus: {args.out / 'rollouts.jsonl'}")
    print(f"{len(records)} rollouts  ({len(scored)} scored, "
          f"{len(infra)} harness errors excluded)\n")

    by_cand: dict[str, list[dict]] = defaultdict(list)
    for r in scored:
        by_cand[r.get("candidate_id", "?")].append(r)

    for cid, rows in sorted(by_cand.items()):
        values = [value_of(r) for r in rows]
        zeros = sum(1 for v in values if v <= 1e-9)
        print(f"== {cid}  n={len(values)}")
        print(f"   mean {statistics.mean(values):.4f}   "
              f"zero rate {zeros/len(values):.3f}   "
              f"min {min(values):.4f}   max {max(values):.4f}")
        per_task: dict[str, list[float]] = defaultdict(list)
        for r in rows:
            per_task[r.get("task", "?")].append(value_of(r))
        for task, vals in sorted(per_task.items()):
            spread = (f" +/- {statistics.stdev(vals):.4f}" if len(vals) > 1 else "")
            print(f"     {task:<52} {statistics.mean(vals):.4f}{spread}  n={len(vals)}")
        statuses: dict[str, int] = defaultdict(int)
        for r in rows:
            statuses[status_of(r)] += 1
        print(f"   statuses: {dict(statuses)}")
        print()

    if infra:
        print("== harness errors (NOT model failures) ==")
        for r in infra[:10]:
            print(f"   {r.get('task')}: {str(r.get('error'))[:150]}")

    if len(by_cand) > 1:
        print("== paired per-task comparison vs the seed ==")
        cids = sorted(by_cand)
        base = cids[0]
        base_by_task = {r["task"]: value_of(r) for r in by_cand[base]}
        for cid in cids[1:]:
            deltas = []
            for r in by_cand[cid]:
                if r["task"] in base_by_task:
                    deltas.append(value_of(r) - base_by_task[r["task"]])
            if not deltas:
                continue
            mean_d = statistics.mean(deltas)
            spread = statistics.stdev(deltas) if len(deltas) > 1 else 0.0
            # Paired, because the tasks are the same tasks. With n this small the
            # interval is wide on purpose -- reporting it narrow would be the lie.
            half = 1.96 * spread / max(1, len(deltas)) ** 0.5
            print(f"   {cid} - {base}: {mean_d:+.4f} "
                  f"[{mean_d-half:+.4f}, {mean_d+half:+.4f}] n={len(deltas)}"
                  + ("   (CI spans zero)" if (mean_d - half) * (mean_d + half) <= 0 else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
