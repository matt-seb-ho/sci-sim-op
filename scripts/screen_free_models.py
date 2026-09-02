#!/usr/bin/env python3
"""Which additional free models clear the quality bar AND are actually free?

Two independent tests, and a candidate must pass both.

**Capability.** The bar is an Artificial Analysis intelligence index at or very
near ``deepseek-v4-flash-0420`` (the 0420 release, index 42 -- not 0731, which is
50). A panel of weak models manufactures noise rather than evidence, and which
inference model you run on partly determines the measured gain
(arXiv:2605.30621), so a panel member has to be able to produce an informative
result. The index is passed in on the command line because it comes from a human
reading a leaderboard, not from an API.

**Price.** A catalogue price of 0 is evidence about the listing, not about what
the next call costs. So each candidate gets one real completion and its
``usage.cost`` is read back. Non-zero means the model is dropped, immediately and
permanently, which is the campaign's entire budget policy.

    python3 scripts/screen_free_models.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from _geos import load_env  # noqa: E402
from harness_evolve.proposers.backends import (  # noqa: E402
    CostLedger, OpenRouterBackend,
)

#: Bar: deepseek-v4-flash-0420 scores 42. Indices read 2026-08-26 from
#: artificialanalysis.ai. "at or very near" is read as >= 41.
BAR = 42.0
NEAR = 41.0

CANDIDATES = [
    # (slug, AA intelligence index, context, note)
    ("z-ai/glm-5.2:free", 51.0, "256k", "#1 open-weight on AA index v4.1"),
    ("nvidia/nemotron-3-ultra-550b-a55b:free", 48.0, "1M", ""),
    ("minimax/minimax-m3:free", 44.0, "1M", ""),
    ("thinkingmachines/inkling:free", 42.0, "1M", "launched at 41, xhigh 42"),
    ("deepseek/deepseek-v4-flash:free", 50.0, "128k", "the 0731 release; bar is 0420=42"),
]

PROMPT = ("In one sentence: what does the targetRegions attribute do in a GEOS "
          "solver block?")


def main() -> int:
    load_env()
    ledger = CostLedger(path=REPO / ".evolve" / "provider_calls.jsonl")
    rows = []
    for slug, index, ctx, note in CANDIDATES:
        clears = index >= NEAR
        row = {"model": slug, "aa_index": index, "context": ctx, "note": note,
               "clears_bar": clears}
        if not clears:
            row["verdict"] = f"rejected: AA index {index} < {NEAR}"
            rows.append(row)
            continue
        backend = OpenRouterBackend(model=slug, max_tokens=2000, ledger=ledger,
                                    require_zero_cost=True, max_attempts=2)
        started = time.time()
        try:
            text = backend(PROMPT)
            cost = backend.last_usage.get("cost")
            row.update({
                "reachable": True, "cost": cost,
                "free": cost == 0,
                "latency_s": round(time.time() - started, 1),
                "chars": len(text),
                "verdict": ("ADOPTABLE" if cost == 0
                            else f"rejected: billed {cost}"),
            })
        except Exception as exc:  # noqa: BLE001 - the point is to record why
            row.update({"reachable": False,
                        "latency_s": round(time.time() - started, 1),
                        "verdict": f"rejected: {type(exc).__name__}: {exc}"[:220]})
        rows.append(row)
        print(f"{slug:<42} AA={index:<5} {row['verdict']}")

    out = REPO / ".evolve" / "model_screen.json"
    out.write_text(json.dumps({"bar": BAR, "near": NEAR, "rows": rows,
                               "ts": int(time.time())}, indent=2))
    print(f"\nledger: {ledger.calls} calls, total cost ${ledger.total_cost}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
