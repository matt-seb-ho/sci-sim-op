#!/usr/bin/env python3
"""Buy more rollouts for a candidate that only exists inside the corpus.

**Why this needs to exist (F11).** A candidate's adapter is written to disk for
every rollout, but `Candidate.from_dir` on that directory does not give back the
candidate: `materialize()` appends a trailing newline to any file lacking one,
so the content hash moves and the corpus -- which is keyed on that hash -- treats
the reloaded adapter as a different candidate. Rollouts bought that way would not
pair with the cells already on disk.

The champion is reconstructed instead from the parent's manifest plus the
child's files, searching the small space of per-file trailing-newline states for
the one that reproduces the recorded id. If no combination reproduces it the
script refuses rather than buying rollouts under a near-miss id, because a
near-miss is exactly the silent-substitution defect this campaign keeps finding.

    uv run python scripts/replicate_cell.py --cid cand_xxx \
        --tasks ExampleMandel --seeds 3,1000,1001,2000
"""

from __future__ import annotations

import argparse
import itertools
import sys
from dataclasses import replace
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from harness_evolve.core.candidate import Candidate  # noqa: E402


def reconstruct(cid: str, adapters_root: Path, parent_dir: Path) -> Candidate:
    """Rebuild the candidate whose recorded id is ``cid``. Raises if it cannot."""
    hits = sorted(adapters_root.glob(f"*{cid}*"))
    if not hits:
        raise SystemExit(f"no materialized adapter for {cid} under {adapters_root}")
    mat = Candidate.from_dir(hits[0])
    parent = Candidate.from_dir(parent_dir)
    keys = sorted(mat.files)
    for combo in itertools.product([False, True], repeat=len(keys)):
        files = {
            k: (mat.files[k][:-1]
                if (s and mat.files[k].endswith("\n")) else mat.files[k])
            for k, s in zip(keys, combo)
        }
        cand = replace(parent, files=files,
                       parent_id=mat.parent_id, generation=mat.generation)
        if cand.cid == cid:
            print(f"reconstructed {cid} from {hits[0].name}")
            print(f"  newline-stripped: "
                  f"{[k for k, s in zip(keys, combo) if s] or 'none'}")
            return cand
    raise SystemExit(
        f"could not reconstruct {cid} from {hits[0]}: no trailing-newline "
        f"combination reproduces the recorded id. Refusing to buy rollouts under "
        f"a different id -- they would not pair with the cells already on disk."
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=REPO / ".evolve" / "geos_search")
    ap.add_argument("--cid", required=True)
    ap.add_argument("--parent", type=Path, default=REPO / ".evolve" / "seed")
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--seeds", required=True)
    ap.add_argument("--parallel", type=int, default=8)
    ap.add_argument("--timeout", type=float, default=2400.0)
    args = ap.parse_args()

    import search_geos as sg  # noqa: PLC0415 - shares the runner/guard stack

    cand = reconstruct(args.cid, args.out / "rollouts" / "adapters", args.parent)
    tasks = [t.strip() for t in args.tasks.split(",") if t.strip()]
    seeds = tuple(int(s) for s in args.seeds.split(",") if s.strip())

    guard = sg.build_guard(args.out, args.parallel)
    runner = sg.build_runner(args.out, args.timeout, args.parallel, guard)
    print(f"{cand.cid}: {len(tasks)} task(s) x {len(seeds)} seed(s) "
          f"= {len(tasks) * len(seeds)} rollout(s)")
    rollouts = runner.run_many(cand, tasks, seeds)
    for r in sorted(rollouts, key=lambda r: (r.task, r.seed)):
        print(f"  {r.task:<32} seed {r.seed:>5}  {r.score.value:.4f}  {r.score.status}")
    print(runner.inner.summary())
    print(guard.render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
