"""geomodel_bench CLI.

  python -m geomodel_bench build-truth [--truth DIR]
  python -m geomodel_bench baselines   [--truth DIR] [--out DIR]
  python -m geomodel_bench score SUBMISSION_DIR [--truth DIR] [--baseline DIR] [--out FILE]
  python -m geomodel_bench table NAME=SCORE.json ...

`score` prints JSON with every metric and the naive baseline's value next to it
(the baseline defaults to <truth>/../baselines/naive).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import baselines, score as S, truth as T


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="geomodel_bench")
    sp = ap.add_subparsers(dest="cmd", required=True)
    b = sp.add_parser("build-truth")
    b.add_argument("--truth", default=str(T.DEFAULT_TRUTH))
    bl = sp.add_parser("baselines")
    bl.add_argument("--truth", default=str(T.DEFAULT_TRUTH))
    bl.add_argument("--out", default=None)
    s = sp.add_parser("score")
    s.add_argument("submission")
    s.add_argument("--truth", default=str(T.DEFAULT_TRUTH))
    s.add_argument("--baseline", default=None, help="naive submission dir; 'none' to skip")
    s.add_argument("--out", default=None)
    t = sp.add_parser("table")
    t.add_argument("pairs", nargs="+", help="NAME=score.json")
    a = ap.parse_args(argv)

    if a.cmd == "build-truth":
        print(json.dumps(T.build_truth(a.truth), indent=1))
        return 0
    if a.cmd == "baselines":
        tr = T.load_truth(a.truth)
        out = Path(a.out or Path(a.truth).parent / "baselines")
        print(baselines.write_naive(out / "naive", tr, baselines.read_1101_t_profile(Path(a.truth).parent)))
        print(baselines.write_expert(out / "expert2019", tr))
        print(baselines.write_expert(out / "expert2019_1160", tr, state="1160"))
        return 0
    if a.cmd == "score":
        tr = T.load_truth(a.truth)
        res = S.score(a.submission, tr)
        base = a.baseline or str(Path(a.truth).parent / "baselines" / "naive")
        if base != "none" and Path(base).is_dir():
            S.attach_baseline(res, S.score(base, tr))
            res["baseline"] = base
        txt = json.dumps(res, indent=1)
        if a.out:
            Path(a.out).write_text(txt)
        print(txt)
        return 0
    if a.cmd == "table":
        res = {}
        for p in a.pairs:
            name, path = p.split("=", 1)
            res[name] = json.loads(Path(path).read_text())
        print(S.headline_table(res))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
