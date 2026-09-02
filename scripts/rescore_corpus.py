#!/usr/bin/env python3
"""Re-score rollouts whose workspace looked empty when it was scored.

**F7, 2026-09-02.** The harness copies the agent's workspace out of the
container when a run ends. Killing a run on timeout can catch that copy in
progress, so the score is computed against a directory that is still filling.
Two of the first eighteen rollouts came back ``empty_workspace`` with value
0.0000; re-scoring one of them from the very same path minutes later returned
**0.8250, success**.

A fabricated zero is not a small error here. The **zero rate** is the headline
tail quantity of the whole reliability argument, `build_slices` reads spread and
zero-rate to choose which tasks the search anchors on, and both fabricated zeros
landed on otherwise-high-scoring tasks -- so they inflate variance, deflate
means, and steer the experiment.

Re-scoring from artifacts costs nothing and is exactly what the recording corpus
exists for. Originals are never overwritten in place: the corrected row carries
`rescored_from`, so any number can still be recomputed either way.

    uv run python scripts/rescore_corpus.py --model z-ai/glm-5.3-flash [--apply]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from harness_evolve.simulators.base import SimulatorRegistry  # noqa: E402

SUSPECT = ("empty_workspace", "no_workspace")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=REPO / ".evolve" / "geos_search")
    ap.add_argument("--model", required=True)
    ap.add_argument("--ground-truth-dir", type=Path,
                    default=Path("/home/matt/projects/siga/data/eval/experiments_gt"))
    ap.add_argument("--simulator", default="geos")
    ap.add_argument("--apply", action="store_true",
                    help="write the corrected corpus; without it, report only")
    args = ap.parse_args()

    corpus = args.out / "rollouts.jsonl"
    rows = [json.loads(l) for l in corpus.read_text().splitlines() if l.strip()]
    spec = SimulatorRegistry.get(args.simulator)

    changed = 0
    for r in rows:
        if r.get("model") != args.model:
            continue
        score = r.get("score") or {}
        if score.get("status") not in SUSPECT:
            continue
        d = r.get("artifacts_dir")
        inputs = Path(d) / "inputs" if d else None
        if inputs is None or not inputs.is_dir():
            print(f"{r['task']} seed {r['seed']}: no workspace on disk, left as "
                  f"{score.get('status')}")
            continue
        n = sum(1 for p in inputs.rglob('*') if p.is_file())
        new = spec.score(inputs, args.ground_truth_dir / r["task"], r["task"])
        verdict = "CHANGED" if new.status != score.get("status") else "unchanged"
        print(f"{r['task']:<30} seed {r['seed']}  {score.get('status')} "
              f"{score.get('value'):.4f}  ->  {new.status} {new.value:.4f}   "
              f"({n} files on disk)  {verdict}")
        if new.status in SUSPECT:
            continue
        changed += 1
        if args.apply:
            r["score"] = {
                **new.to_dict(),
                "detail": {**dict(new.detail), "rescored_from": {
                    "status": score.get("status"), "value": score.get("value"),
                    "reason": "F7: scored while the container workspace was still "
                              "being copied out after a timeout kill"}},
            }
            r["rescored"] = True

    print(f"\n{changed} row(s) would change" + (" -- WRITING" if args.apply else ""))
    if args.apply and changed:
        shutil.copy2(corpus, corpus.with_suffix(".jsonl.pre-rescore.bak"))
        corpus.write_text("".join(json.dumps(r) + "\n" for r in rows))
        print(f"backup: {corpus.with_suffix('.jsonl.pre-rescore.bak')}")
        print(f"written: {corpus}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
