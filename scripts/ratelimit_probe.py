#!/usr/bin/env python3
"""Measure the actual rate limits, per (provider, model), by ramping concurrency.

Provider documentation and the ``x-ratelimit-*`` headers both describe the
*account's* allowance. Neither describes what you will actually get, because for
a model served out of a shared upstream pool the binding constraint is that pool,
not the account. On 2026-08-26 the Nous account allowance was 180 rpm / 720k tpm
and the observed ceiling for ``stealth/ox-alpha`` was roughly an eighth of that:
everything above it came back 429 from *upstream*, with the account quota barely
touched.

So this ramps concurrency and reports goodput -- successful completions per
minute -- rather than trusting either the docs or the headers. Goodput peaks and
then falls; the peak is the number worth designing the search around.

    python3 scripts/ratelimit_probe.py                  # every pair
    python3 scripts/ratelimit_probe.py --pairs nous:stealth/ox-alpha
    python3 scripts/ratelimit_probe.py --aggregate      # all providers at once
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / ".evolve" / "ratelimits.jsonl"

# Not decoration. Nous' edge rejects the *default* urllib User-Agent
# ("Python-urllib/3.x") outright; any other value, including none at all, passes.
# Every HTTP client in this repo therefore sets one explicitly.
UA = "sci-sim-op/0.1 (harness-evolve rate probe)"

PROVIDERS = {
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "nous": ("https://inference-api.nousresearch.com/v1", "NOUS_API_KEY"),
    "venice": ("https://api.venice.ai/api/v1", "VENICE_API_KEY"),
}

PAIRS = [
    ("openrouter", "stealth/ox-alpha"),
    ("openrouter", "tencent/hy3"),
    ("nous", "stealth/ox-alpha"),
    ("nous", "tencent/hy3:free"),
    ("venice", "stealth-ox-alpha"),
]

# Long enough that the model must actually think, short enough that a ramp
# finishes. A trivial prompt would measure the edge, not the pool.
PROMPT = (
    "A GEOS XML input deck declares a Solvers block with no target regions. "
    "Name the two attributes most likely missing and why. Two sentences."
)


@dataclass
class Call:
    ok: bool
    code: int | str
    latency: float
    tokens: int = 0
    cost: float = 0.0
    headers: dict | None = None


def load_env(path: Path = REPO / ".env") -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


def one(provider: str, model: str, max_tokens: int = 1200) -> Call:
    base, key_env = PROVIDERS[provider]
    key = os.environ.get(key_env, "")
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": PROMPT}],
        "max_tokens": max_tokens,
    }).encode()
    req = urllib.request.Request(
        f"{base}/chat/completions", data=body,
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json",
                 "User-Agent": UA},
    )
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            hdrs = {k.lower(): v for k, v in resp.headers.items()
                    if "ratelimit" in k.lower() or k.lower() == "retry-after"}
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return Call(False, exc.code, time.time() - t)
    except Exception as exc:  # noqa: BLE001
        return Call(False, type(exc).__name__, time.time() - t)

    # An error can arrive inside a 200 body on every one of these providers.
    if data.get("error"):
        err = data["error"]
        code = err.get("code") if isinstance(err, dict) else "error"
        return Call(False, code or "error", time.time() - t, headers=hdrs)

    usage = data.get("usage") or {}
    return Call(True, 200, time.time() - t,
                usage.get("total_tokens", 0) or 0,
                usage.get("cost", 0) or 0, hdrs)


def burst(provider: str, model: str, conc: int, n: int) -> dict:
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=conc) as ex:
        calls = list(ex.map(lambda _: one(provider, model), range(n)))
    elapsed = time.time() - t0
    ok = [c for c in calls if c.ok]
    codes: dict[str, int] = {}
    for c in calls:
        codes[str(c.code)] = codes.get(str(c.code), 0) + 1
    lat = sorted(c.latency for c in ok)
    hdrs = next((c.headers for c in ok if c.headers), None)
    return {
        "provider": provider, "model": model, "concurrency": conc,
        "requests": n, "ok": len(ok), "elapsed_s": round(elapsed, 1),
        "goodput_per_min": round(len(ok) / elapsed * 60, 1) if elapsed else 0,
        "tokens_per_min": round(sum(c.tokens for c in ok) / elapsed * 60) if elapsed else 0,
        "cost": round(sum(c.cost for c in ok), 6),
        "p50_s": round(statistics.median(lat), 1) if lat else None,
        "codes": codes, "limit_headers": hdrs, "ts": int(time.time()),
    }


def ramp(provider: str, model: str, levels: list[int]) -> list[dict]:
    rows = []
    print(f"\n### {provider} / {model}", flush=True)
    print(f"{'conc':>5} {'ok/req':>9} {'goodput/min':>12} {'tok/min':>9} "
          f"{'p50':>6}  codes", flush=True)
    for c in levels:
        r = burst(provider, model, c, c * 3)
        rows.append(r)
        print(f"{c:>5} {r['ok']:>4}/{r['requests']:<4} {r['goodput_per_min']:>12} "
              f"{r['tokens_per_min']:>9} {str(r['p50_s']):>6}  "
              f"{json.dumps(r['codes'])}", flush=True)
        if r["limit_headers"]:
            print(f"        headers: {json.dumps(r['limit_headers'])}", flush=True)
        # Everything failed: either the pair is dead or we are hard-limited.
        # Ramping further tells us nothing and just generates load.
        if r["ok"] == 0:
            print("        all requests failed -- stopping this ramp", flush=True)
            break
    best = max(rows, key=lambda r: r["goodput_per_min"])
    print(f"  -> peak goodput {best['goodput_per_min']}/min at concurrency "
          f"{best['concurrency']}", flush=True)
    return rows


def aggregate(models: list[tuple[str, str]], conc_each: int, n_each: int) -> None:
    """Do three providers give more ox-alpha throughput than the best one alone?

    This is the claim worth testing directly rather than inferring from the
    ``provider`` field: if the pools are shared, the aggregate matches the best
    single provider; if they are not, it approaches the sum.
    """
    print(f"\n### AGGREGATE: {len(models)} routes concurrently, "
          f"{conc_each} each", flush=True)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=conc_each * len(models)) as ex:
        futs = {ex.submit(burst, p, m, conc_each, n_each): (p, m) for p, m in models}
        rows = [f.result() for f in futs]
    elapsed = time.time() - t0
    total_ok = sum(r["ok"] for r in rows)
    for r in rows:
        print(f"  {r['provider']:<11} {r['model']:<20} {r['ok']:>3}/{r['requests']:<3} "
              f"{json.dumps(r['codes'])}", flush=True)
    print(f"  -> aggregate {total_ok} completions in {elapsed:.1f}s = "
          f"{total_ok/elapsed*60:.1f}/min", flush=True)
    with OUT.open("a") as fh:
        fh.write(json.dumps({"kind": "aggregate", "elapsed_s": round(elapsed, 1),
                             "total_ok": total_ok, "rows": rows,
                             "ts": int(time.time())}) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pairs", nargs="*", help="provider:model, default all")
    ap.add_argument("--levels", default="1,2,4,8,16")
    ap.add_argument("--aggregate", action="store_true",
                    help="run every ox-alpha route at once to test pool sharing")
    args = ap.parse_args()
    load_env()
    OUT.parent.mkdir(parents=True, exist_ok=True)

    levels = [int(x) for x in args.levels.split(",")]
    pairs = ([tuple(p.split(":", 1)) for p in args.pairs] if args.pairs else PAIRS)

    if args.aggregate:
        ox = [(p, m) for p, m in PAIRS if "ox-alpha" in m]
        aggregate(ox, conc_each=4, n_each=12)
        return 0

    for provider, model in pairs:
        try:
            rows = ramp(provider, model, levels)
        except Exception as exc:  # noqa: BLE001
            print(f"  {provider}/{model}: ramp failed: {exc}", flush=True)
            continue
        with OUT.open("a") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
