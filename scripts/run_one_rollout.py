#!/usr/bin/env python3
"""One real GEOS rollout, inspected by hand.

INTEGRATION_REQUIREMENTS R3: `SubprocessRunner` has never run in this
environment. Every branch except the four-line process launcher is tested
against an injected fake, so the first real use should be one task, with the
resulting `Rollout` looked at rather than aggregated.

It is also the measurement the whole night's schedule depends on: how long one
rollout takes, and what it costs, decides how large a search is affordable
inside the free window.

    python3 scripts/run_one_rollout.py --task ExampleMandel [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _geos import REPO, runner  # noqa: E402

sys.path.insert(0, str(REPO / "src"))
from harness_evolve.core.candidate import Candidate  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--task", default="ExampleMandel")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--candidate", type=Path, default=REPO / ".evolve" / "seed")
    ap.add_argument("--results", type=Path, default=REPO / ".evolve" / "rollouts")
    ap.add_argument("--timeout", type=float, default=1800.0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    candidate = Candidate.from_dir(args.candidate)
    print(f"candidate {candidate.cid}: {sorted(candidate.files)}")
    print(f"stop policy: {candidate.manifest.stop_policy}")

    extra = ("--dry-run",) if args.dry_run else ()
    run = runner(args.results, timeout_s=args.timeout, extra_args=extra)

    started = time.time()
    rollout = run.run(candidate, args.task, seed=args.seed)
    elapsed = time.time() - started

    print(f"\n=== rollout in {elapsed:.0f}s ===")
    print(f"score:  {rollout.score.value:.4f}  status={rollout.score.status}")
    print(f"cost:   {rollout.cost}")
    print(f"error:  {rollout.error}")
    print(f"artifacts: {rollout.artifacts_dir}")
    print(f"validator events: {len(rollout.validator_events)}")
    for event in rollout.validator_events[:6]:
        print(f"  - {json.dumps(event)[:220]}")
    if rollout.score.detail:
        print(f"detail: {json.dumps(rollout.score.detail)[:800]}")

    out = args.results / f"one_rollout_{args.task}_s{args.seed}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "task": args.task, "seed": args.seed, "elapsed_s": round(elapsed, 1),
        "score": rollout.score.value, "status": rollout.score.status,
        "detail": rollout.score.detail,
        "cost": {"tool_calls": rollout.cost.tool_calls,
                 "wall_seconds": rollout.cost.wall_seconds,
                 "input_tokens": rollout.cost.input_tokens,
                 "output_tokens": rollout.cost.output_tokens,
                 "usd": rollout.cost.usd},
        "error": rollout.error, "artifacts_dir": rollout.artifacts_dir,
        "validator_events": rollout.validator_events[:40],
    }, indent=2, default=str))
    print(f"\nwrote {out}")
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
