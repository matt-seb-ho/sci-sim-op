#!/usr/bin/env python3
"""Per-rollout cost, tokens, tool calls and wall-clock, from the agent transcripts.

The rollout corpus records score and error but not resource use; OpenRouter's
account endpoints record spend but not which rollout spent it. This joins the
two: token and tool-call counts come from each rollout's own Claude transcript,
dollars from the model's list price, and wall-clock from the transcript span.

`--baseline` compares against the pre-2026-09-08 configuration, where the agent
ran full GEOS solves.
"""
from __future__ import annotations

import argparse, collections, glob, json, os, statistics, sys
from pathlib import Path

# z-ai/glm-5.3-flash list price, verified live 2026-09-02 and 2026-09-08.
IN_USD, OUT_USD = 0.075 / 1e6, 0.250 / 1e6
# Cached input is billed at a discount; measured blend on 2026-09-02 was ~0.27
# of the naive all-fresh estimate. Applied only to the cache_read component.
CACHE_READ_DISCOUNT = 0.10


def transcript_stats(artifacts_dir: str) -> dict:
    tok = collections.Counter()
    tools = collections.Counter()
    turns = 0
    ts: list[float] = []
    pat = os.path.join(artifacts_dir, ".claude_home/.claude/projects/-workspace/*.jsonl")
    for f in glob.glob(pat):
        for line in open(f, errors="ignore"):
            try:
                o = json.loads(line)
            except ValueError:
                continue
            m = o.get("message") or {}
            u = m.get("usage") or o.get("usage")
            if isinstance(u, dict):
                turns += 1
                for k in ("input_tokens", "output_tokens",
                          "cache_read_input_tokens", "cache_creation_input_tokens"):
                    if isinstance(u.get(k), int):
                        tok[k] += u[k]
            c = m.get("content")
            if isinstance(c, list):
                for b in c:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        tools[b.get("name")] += 1
            if isinstance(o.get("timestamp"), str):
                ts.append(o["timestamp"])
    fresh_in = tok["input_tokens"] + tok["cache_creation_input_tokens"]
    cached_in = tok["cache_read_input_tokens"]
    cost = fresh_in * IN_USD + cached_in * IN_USD * CACHE_READ_DISCOUNT + tok["output_tokens"] * OUT_USD
    span = None
    if len(ts) > 1:
        import datetime
        try:
            parsed = sorted(datetime.datetime.fromisoformat(x.replace("Z", "+00:00")) for x in ts)
            span = (parsed[-1] - parsed[0]).total_seconds()
        except ValueError:
            span = None
    return {
        "wall_s": span,
        "turns": turns, "tool_calls": sum(tools.values()), "tools": dict(tools),
        "fresh_in": fresh_in, "cached_in": cached_in, "out": tok["output_tokens"],
        "est_cost_usd": cost,
    }


def solve_evidence(artifacts_dir: str) -> int:
    """Count Bash tool_use blocks that invoke geosx WITHOUT --validate-input."""
    n = 0
    pat = os.path.join(artifacts_dir, ".claude_home/.claude/projects/-workspace/*.jsonl")
    for f in glob.glob(pat):
        for line in open(f, errors="ignore"):
            if "geosx" not in line and "bin/geos" not in line:
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            c = (o.get("message") or {}).get("content")
            if not isinstance(c, list):
                continue
            for b in c:
                if not (isinstance(b, dict) and b.get("type") == "tool_use"):
                    continue
                cmd = str((b.get("input") or {}).get("command", ""))
                if ("geosx" in cmd or "bin/geos " in cmd) and "--validate-input" not in cmd:
                    n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus", type=Path, help="rollouts.jsonl")
    ap.add_argument("--label", default="arm")
    ap.add_argument("--json-out", type=Path, default=None)
    a = ap.parse_args()

    rows = [json.loads(l) for l in open(a.corpus)]
    out = []
    for r in rows:
        d = r.get("artifacts_dir")
        if not d or not os.path.isdir(d):
            continue
        s = transcript_stats(d)
        s.update(task=r["task"], seed=r.get("seed"), model=r.get("model"),
                 error=r.get("error"), solves=solve_evidence(d))
        sc = r.get("score")
        s["score"] = sc.get("value") if isinstance(sc, dict) else sc
        out.append(s)

    if not out:
        print("no rollouts with readable transcripts", file=sys.stderr)
        return 1

    def agg(key):
        v = [x[key] for x in out if isinstance(x.get(key), (int, float))]
        return (statistics.mean(v), statistics.median(v), min(v), max(v)) if v else (0, 0, 0, 0)

    print(f"\n=== {a.label} — n={len(out)} rollouts ===")
    print(f"{'metric':<22}{'mean':>12}{'median':>12}{'min':>12}{'max':>12}")
    for k, fmt in (("turns", "{:.1f}"), ("tool_calls", "{:.1f}"), ("fresh_in", "{:.0f}"),
                   ("cached_in", "{:.0f}"), ("out", "{:.0f}"),
                   ("est_cost_usd", "{:.4f}"), ("wall_s", "{:.0f}"), ("solves", "{:.2f}")):
        m, md, lo, hi = agg(k)
        print(f"{k:<22}" + "".join(f"{fmt.format(x):>12}" for x in (m, md, lo, hi)))

    tools = collections.Counter()
    for x in out:
        tools.update(x["tools"])
    tot = sum(tools.values())
    print(f"\ntool mix ({tot} calls, {tot/len(out):.1f}/rollout):")
    for k, v in tools.most_common(10):
        print(f"    {str(k):<36}{v:>6}  {100*v/max(tot,1):>5.1f}%")

    solves = sum(x["solves"] for x in out)
    print(f"\nNON-validate geosx invocations: {solves}"
          f"  ({'CLEAN' if solves == 0 else 'CONSTRAINT VIOLATED'})")
    errs = collections.Counter(x["error"] for x in out)
    print(f"errors: {dict(errs)}")

    if a.json_out:
        a.json_out.write_text(json.dumps(out, indent=1))
        print(f"\nwrote {a.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
