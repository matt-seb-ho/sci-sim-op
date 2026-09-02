#!/usr/bin/env python3
"""Drive the hardened provider layer against the real free endpoints.

The unit tests prove the policy is implemented. They cannot prove the policy is
*right*, because every fact it encodes -- Nous' User-Agent rejection, the shared
upstream pool's ceiling, whether ox-alpha still reports cost 0 -- is a property of
somebody else's infrastructure at this moment. So this runs the actual
``RoutedBackend`` at real concurrency against the real roster and reports what
happened.

    python3 scripts/free_window_smoke.py --calls 24 --workers 12

Reports goodput, the concurrency limit trajectory, throttle count, and the cost
the provider says it charged. Exit 2 if anything billed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from harness_evolve.proposers.backends import (  # noqa: E402
    OX_ALPHA, CostLedger, RoutedBackend, free_roster,
)

PROMPT = (
    "A GEOS XML input deck declares a Solvers block whose targetRegions names a "
    "region that does not exist. In two sentences: what does GEOS report, and "
    "what is the minimal fix?"
)


def load_env(path: Path = REPO / ".env") -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--calls", type=int, default=24)
    ap.add_argument("--max-tokens", type=int, default=2000)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--model", default=OX_ALPHA)
    ap.add_argument("--out", type=Path, default=REPO / ".evolve" / "free_window_smoke.json")
    args = ap.parse_args()
    load_env()

    backend = RoutedBackend(
        routes=free_roster((args.model,)),
        ledger=CostLedger(path=REPO / ".evolve" / "provider_calls.jsonl"),
        max_tokens=args.max_tokens,
    )
    print(f"roster: {[r.name for r in backend.routes]}")

    trajectory: list[int] = []
    results: list[dict] = []

    def one(i: int) -> dict:
        started = time.time()
        try:
            text = backend(f"{PROMPT} (variation {i})")
            out = {"i": i, "ok": True, "chars": len(text),
                   "latency_s": round(time.time() - started, 1)}
        except Exception as exc:  # noqa: BLE001 - report, do not abort the sweep
            out = {"i": i, "ok": False, "error": f"{type(exc).__name__}: {exc}"[:300],
                   "latency_s": round(time.time() - started, 1)}
        trajectory.append(backend.routes[0].limiter.limit)
        return out

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(one, range(args.calls)))
    elapsed = time.time() - t0

    ok = sum(1 for r in results if r["ok"])
    stats = backend.stats()
    report = {
        "model": args.model,
        "calls": args.calls,
        "workers": args.workers,
        "ok": ok,
        "elapsed_s": round(elapsed, 1),
        "goodput_per_min": round(ok / elapsed * 60, 1) if elapsed else 0.0,
        "limit_trajectory": trajectory,
        "stats": stats,
        "failures": [r for r in results if not r["ok"]][:5],
        "ts": int(time.time()),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != "limit_trajectory"},
                     indent=2))
    print(f"limit trajectory: {trajectory}")
    print(f"report: {args.out}")

    if stats["total_cost"] != 0.0:
        print("\nALARM: a route billed. Free-models-only is violated.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
