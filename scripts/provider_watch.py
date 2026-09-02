#!/usr/bin/env python3
"""Is the free window still open?

The campaign this supports is only worth running while `stealth/ox-alpha` and
`tencent/hy3` are free. "Free" is not a property of the model, it is a property
of a *(provider, slug)* pair at a moment in time, and it has already changed
once: OpenRouter's `tencent/hy3:free` now answers

    "This model is unavailable for free. The paid version is available now"

so a catalogue that says `pricing.prompt == "0"` is evidence about the listing,
not about what the next call will cost. This probes both: the advertised price
*and* the `usage.cost` an actual completion reports back. They disagree in both
directions -- Venice advertises $0 and refuses to serve on a $0 balance; Nous
serves `hy3:free` and bills a few micro-dollars for it.

Exit code is the alarm: 0 while every watched pair is still free, 2 when one
has flipped or gone unreachable. That makes it usable as a cron gate around a
long search rather than something a human has to read.

    python3 scripts/provider_watch.py               # probe once, print a table
    python3 scripts/provider_watch.py --watch 900   # loop, alarm on change
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LEDGER = REPO / ".evolve" / "provider_ledger.jsonl"

# A User-Agent is not optional. Nous' edge returns 403 on every request without
# one -- including requests that are otherwise perfectly valid and well under
# quota -- so omitting it looks exactly like an auth failure.
UA = "sci-sim-op/0.1 (harness-evolve provider watch)"


@dataclass(frozen=True)
class Target:
    provider: str
    base_url: str
    key_env: str
    model: str
    note: str = ""


TARGETS = (
    Target("openrouter", "https://openrouter.ai/api/v1",
           "OPENROUTER_API_KEY", "stealth/ox-alpha",
           "free but on a shared upstream pool; 429s heavily above ~3 concurrent"),
    Target("nous", "https://inference-api.nousresearch.com/v1",
           "NOUS_API_KEY", "stealth/ox-alpha",
           "the workhorse: cost=0, 180 rpm / 720k tpm, ~24/32 concurrent"),
    Target("nous", "https://inference-api.nousresearch.com/v1",
           "NOUS_API_KEY", "tencent/hy3:free",
           "billed despite the :free suffix -- watch the cost column"),
    Target("venice", "https://api.venice.ai/api/v1",
           "VENICE_API_KEY", "stealth-ox-alpha",
           "priced at $0 but blocked while the account balance is $0"),
)


def load_env(path: Path = REPO / ".env") -> None:
    """Populate os.environ from .env without requiring python-dotenv."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


def _post(url: str, key: str, payload: dict, timeout: float = 120.0) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json",
                 "User-Agent": UA},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def probe(t: Target, attempts: int = 3) -> dict:
    """One real completion. Cheapest possible, but a real one.

    The listed price is checked too, but the returned ``usage.cost`` is the
    authority: it is what the account was actually charged, and it is the only
    signal that catches a provider quietly reclassifying a slug.
    """
    key = os.environ.get(t.key_env, "")
    out = {"provider": t.provider, "model": t.model, "ts": int(time.time())}
    if not key:
        return {**out, "status": "no_key", "free": False}

    for attempt in range(attempts):
        result = _probe_once(t, key, out)
        if result["status"] != "throttled" or attempt == attempts - 1:
            return result
        time.sleep(2 ** attempt * 5)
    return result


def _probe_once(t: Target, key: str, out: dict) -> dict:
    started = time.time()
    try:
        data = _post(f"{t.base_url}/chat/completions", key, {
            "model": t.model,
            "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
            "max_tokens": 1024,
        })
    except urllib.error.HTTPError as exc:
        body = exc.read()[:200].decode("utf8", "replace")
        # 429 is a statement about capacity, not about price. Conflating the two
        # would raise the "it stopped being free" alarm every time our own search
        # saturated the endpoint -- which is the normal operating condition here,
        # and would train us to ignore the one alarm that matters.
        status = "throttled" if exc.code == 429 else f"http_{exc.code}"
        return {**out, "status": status, "free": None if exc.code == 429 else False,
                "detail": body, "latency_s": round(time.time() - started, 1)}
    except Exception as exc:  # noqa: BLE001 - any transport failure is "unreachable"
        return {**out, "status": type(exc).__name__, "free": False,
                "latency_s": round(time.time() - started, 1)}

    latency = round(time.time() - started, 1)
    # An OpenAI-compatible error can arrive inside a 200 body; OpenRouter's
    # "unavailable for free" reclassification is delivered exactly that way.
    if data.get("error"):
        return {**out, "status": "error", "free": False, "latency_s": latency,
                "detail": json.dumps(data["error"])[:200]}

    usage = data.get("usage") or {}
    cost = usage.get("cost")
    # Venice reports no cost field at all; absence is not evidence of zero, so
    # only an explicit 0 counts as free.
    free = cost == 0 or cost == 0.0
    return {**out, "status": "ok", "free": free, "cost": cost,
            "latency_s": latency, "tokens": usage.get("total_tokens"),
            "byok": usage.get("is_byok")}


def render(rows: list[dict]) -> str:
    w = max(len(f"{r['provider']}/{r['model']}") for r in rows)
    lines = [f"{'pair'.ljust(w)}  {'free':<5} {'status':<10} {'cost':<12} lat"]
    for r in rows:
        pair = f"{r['provider']}/{r['model']}".ljust(w)
        cost = "-" if r.get("cost") is None else f"${r['cost']:.8f}"
        mark = {True: "yes", False: "NO", None: "?"}[r["free"]]
        lines.append(f"{pair}  {mark:<5} {r['status']:<10} {cost:<12} "
                     f"{r.get('latency_s', '-')}")
        if r.get("detail"):
            lines.append(f"{' ' * w}    -> {r['detail'][:120]}")
    return "\n".join(lines)


def record(rows: list[dict]) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--watch", type=int, metavar="SECONDS",
                    help="loop forever, probing every SECONDS")
    ap.add_argument("--require", nargs="*", default=["nous/stealth/ox-alpha"],
                    help="pairs that must stay free for exit 0")
    args = ap.parse_args()
    load_env()

    while True:
        rows = [probe(t) for t in TARGETS]
        record(rows)
        print(time.strftime("[%Y-%m-%d %H:%M:%S]"))
        print(render(rows))

        by_pair = {f"{r['provider']}/{r['model']}": r for r in rows}
        # None (throttled) is explicitly not an alarm -- only a definite False is.
        broken = [p for p in args.require
                  if by_pair.get(p, {}).get("free") is False
                  or p not in by_pair]
        if broken:
            print(f"\nALARM: no longer free: {', '.join(broken)}",
                  file=sys.stderr)
            if not args.watch:
                return 2
        if not args.watch:
            return 0
        time.sleep(args.watch)


if __name__ == "__main__":
    raise SystemExit(main())
