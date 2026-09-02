#!/usr/bin/env python3
"""Measure the real cost of a GEOS rollout, per model, for budget planning.

Estimating from a price sheet and a token count is not good enough to put in
front of an advisor: an agent rollout's spend is dominated by how many turns it
takes and how much of the context is cached, neither of which is on the price
sheet. So this brackets real rollouts with the OpenRouter account's own usage
counter and reports the difference.

    python3 scripts/cost_probe.py --model z-ai/glm-5.3-flash --tasks A,B --seeds 1

Writes a JSON record per run to .evolve/cost_probe/.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))
from _geos import load_env  # noqa: E402


def account_usage() -> dict:
    """The account's own spend counter -- the authoritative number."""
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/key",
        headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
                 "User-Agent": "sci-sim-op/0.1"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())["data"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", required=True)
    ap.add_argument("--tasks", required=True, help="comma-separated task ids")
    ap.add_argument("--seeds", default="1")
    ap.add_argument("--parallel", type=int, default=2)
    ap.add_argument("--timeout", type=float, default=3000.0)
    ap.add_argument("--out", type=Path,
                    default=REPO / ".evolve" / "cost_probe")
    args = ap.parse_args()
    load_env()

    tasks = [t for t in args.tasks.split(",") if t]
    n_rollouts = len(tasks) * len(args.seeds.split(","))
    slug = args.model.replace("/", "_")
    run_dir = args.out / slug
    run_dir.mkdir(parents=True, exist_ok=True)

    before = account_usage()
    started = time.time()
    print(f"model {args.model}: {n_rollouts} rollout(s), "
          f"usage before ${before['usage']:.6f}")

    env = {**os.environ, "HARNESS_EVOLVE_MODEL": args.model}
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "search_geos.py"),
         "--stage", "baseline", "--task-list", args.tasks,
         "--seeds", args.seeds, "--anchor", str(max(1, len(tasks) - 1)),
         "--probe", "1", "--parallel", str(args.parallel),
         "--timeout", str(args.timeout), "--out", str(run_dir)],
        env=env, capture_output=True, text=True, timeout=args.timeout * 3,
    )
    elapsed = time.time() - started
    after = account_usage()
    spent = after["usage"] - before["usage"]

    corpus = run_dir / "rollouts.jsonl"
    rows = []
    if corpus.is_file():
        rows = [json.loads(l) for l in corpus.read_text().splitlines() if l.strip()]
    scored = [r for r in rows if r["score"]["status"] != "harness_error"]
    infra = len(rows) - len(scored)

    tok_in = sum(r.get("cost", {}).get("input_tokens", 0) or 0 for r in scored)
    tok_out = sum(r.get("cost", {}).get("output_tokens", 0) or 0 for r in scored)
    calls = sum(r.get("cost", {}).get("tool_calls", 0) or 0 for r in scored)

    record = {
        "model": args.model,
        "tasks": tasks,
        "seeds": args.seeds,
        "rollouts_attempted": n_rollouts,
        "rollouts_scored": len(scored),
        "harness_errors": infra,
        "usd_total": round(spent, 6),
        "usd_per_scored_rollout": round(spent / len(scored), 6) if scored else None,
        "elapsed_s": round(elapsed, 1),
        "wall_min_per_rollout": round(elapsed / 60 / max(1, len(scored)), 1),
        "tokens_in": tok_in,
        "tokens_out": tok_out,
        "tool_calls": calls,
        "scores": {r["task"]: r["score"]["value"] for r in scored},
        "statuses": {r["task"]: r["score"]["status"] for r in scored},
        "returncode": proc.returncode,
        "stdout_tail": proc.stdout[-1500:],
        "ts": int(time.time()),
    }
    out_file = run_dir / "cost.json"
    out_file.write_text(json.dumps(record, indent=2))
    print(json.dumps({k: v for k, v in record.items()
                      if k not in ("stdout_tail",)}, indent=2))
    print(f"wrote {out_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
