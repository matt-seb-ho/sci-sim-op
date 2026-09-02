#!/usr/bin/env python3
"""Choose the task pool the search runs on, from *this model's* measured noise.

`docs/2026-08-26_BUDGET_PLAN.md` §3.1 established the method: dropping the two
noisiest tasks costs a third fewer rollouts and improves the minimum detectable
effect roughly 3x (0.144 -> 0.047). The method is adopted here unchanged.

Its *inputs* are not. Those sigma were measured on `stealth/ox-alpha`, whose
free window closed on 2026-08-26, and the 2026-08-26 worklog §25.4 states the
rule directly: per-task sigma is a property of *model x task*, not of the task.
Pruning tonight's pool with last week's model's noise would repeat, in the slice
plan, the same substitution that F1 caught in the corpus.

So this reads the corpus, filtered to one model, and reports the minimum
detectable effect for each candidate pool -- which is the quantity the decision
actually turns on.

    uv run python scripts/prune_pool.py --model z-ai/glm-5.3-flash --drop 2
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def mde(sigmas: list[float], n_seeds: int, *, arms: int = 1) -> float:
    """Two-sided 95% minimum detectable effect.

    Pooled as the root-mean-square of per-task sigma, because the variance of a
    mean over tasks is the mean of the variances -- averaging sigma itself would
    understate exactly the pools this is meant to discriminate against.

    ``arms=1`` is the interval on a single arm's mean. ``arms=2`` is the one
    that matters for a claim: the smallest *difference between two arms* that
    could be distinguished from zero, assuming the two arms' noise is
    independent. That is conservative -- a paired design over identical tasks
    and seeds is positively correlated, so the true figure sits between the two
    -- and conservative is the right direction for a number whose job is to say
    what we cannot detect.

    Note this convention differs from `docs/2026-08-26_BUDGET_PLAN.md` §3.1,
    which does not state its own. The *ratio* between pools agrees to three
    figures (3.07x vs 3.06x for dropping the two noisiest), so the two differ by
    a constant factor and rank pools identically; only the absolute scale moves.
    """
    if not sigmas:
        return float("nan")
    pooled = math.sqrt(sum(s * s for s in sigmas) / len(sigmas))
    return 1.96 * pooled * math.sqrt(arms) / math.sqrt(len(sigmas) * n_seeds)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=REPO / ".evolve" / "geos_search")
    ap.add_argument("--model", required=True)
    ap.add_argument("--drop", type=int, default=2)
    args = ap.parse_args()

    rows = [json.loads(l) for l in (args.out / "rollouts.jsonl").read_text().splitlines() if l.strip()]
    rows = [r for r in rows if (r.get("model") or "") == args.model]
    scored = [r for r in rows if (r.get("score") or {}).get("status") != "harness_error"]
    if not scored:
        print(f"no scored rollouts for model {args.model!r}")
        return 1

    by_task: dict[str, list[float]] = defaultdict(list)
    for r in scored:
        by_task[r["task"]].append(float(r["score"]["value"]))

    stats = []
    for task, vals in by_task.items():
        sd = statistics.stdev(vals) if len(vals) > 1 else float("nan")
        zeros = sum(1 for v in vals if v <= 1e-9) / len(vals)
        stats.append((task, statistics.mean(vals), sd, zeros, min(vals), len(vals)))
    stats.sort(key=lambda s: (s[2] if s[2] == s[2] else -1))

    n_seeds = max(len(v) for v in by_task.values())
    print(f"model {args.model}   {len(scored)} scored rollouts, {len(by_task)} tasks\n")
    print(f"{'task':<34}{'mean':>8}{'sigma':>9}{'zero':>7}{'min':>8}{'n':>4}")
    for t, m, sd, z, lo, n in stats:
        print(f"{t:<34}{m:8.4f}{sd:9.4f}{z:7.0%}{lo:8.4f}{n:4d}")

    print(f"\nminimum detectable effect (95%, {n_seeds} seeds):")
    print(f"  {'pool':<32}{'one arm':>10}{'arm vs arm':>12}")
    keep_all = [s[2] for s in stats]
    print(f"  {f'all {len(stats)} tasks':<32}{mde(keep_all, n_seeds):10.4f}"
          f"{mde(keep_all, n_seeds, arms=2):12.4f}")
    for d in range(1, args.drop + 1):
        kept = stats[:-d]
        sig = [s[2] for s in kept]
        print(f"  {f'drop {d} noisiest ({len(kept)} tasks)':<32}"
              f"{mde(sig, n_seeds):10.4f}{mde(sig, n_seeds, arms=2):12.4f}"
              f"   dropped: {', '.join(s[0] for s in stats[-d:])}")

    kept = stats[:-args.drop] if args.drop else stats
    pool = [s[0] for s in kept]
    print(f"\npool ({len(pool)}): {','.join(pool)}")
    (args.out / "pool.json").write_text(json.dumps(
        {"model": args.model, "n_seeds": n_seeds,
         "kept": pool, "dropped": [s[0] for s in stats[len(kept):]],
         "per_task": {s[0]: {"mean": s[1], "sigma": s[2], "zero_rate": s[3],
                             "min": s[4], "n": s[5]} for s in stats},
         "mde_kept_one_arm": mde([s[2] for s in kept], n_seeds),
         "mde_kept_two_arm": mde([s[2] for s in kept], n_seeds, arms=2),
         "mde_all_one_arm": mde(keep_all, n_seeds),
         "mde_all_two_arm": mde(keep_all, n_seeds, arms=2)}, indent=2))
    print(f"-> {args.out / 'pool.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
