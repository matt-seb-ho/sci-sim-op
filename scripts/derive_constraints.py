#!/usr/bin/env python3
"""Improve an adapter from rollouts that were already paid for.

This is the harness-improvement pass that costs **no additional rollouts**.

The matched-budget critique of automatic harness evolution (arXiv:2607.12227)
bites because evolution spends rollouts to search: give a task-level baseline
the same budget and it often does better. A mechanism that spends *no* rollouts
is not subject to that comparison at all — at any matched budget it is strictly
additive to whatever the baseline does with its own.

Our simulator's validator, on rejecting a deck, does not merely say "invalid".
It prints the full table of valid attributes, or the ~50 legal tag names, or the
set of names actually defined — it names the **correct action space at the point
of failure**. That output is a by-product of every rollout ever run, including
the baseline rollouts one must run regardless in order to have a baseline.
Turning it into a negative constraint costs one parse and one aggregation, both
CPU-only.

So this script takes a corpus written by ``RecordingRunner`` — rollouts spent for
some other purpose entirely — and emits an improved candidate, without executing
anything.

What it does *not* establish is that the result helps. That is an empirical
question, which is why ``actionable_fraction`` is reported prominently: a
validator that only ever emits verdicts yields 0%, and the honest response to
that is to stop claiming this mechanism applies.

Usage:
    python3 scripts/derive_constraints.py \\
        --corpus runs/rollouts.jsonl \\
        --adapter .evolve/seed \\
        --out .evolve/seed_plus_derived
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from harness_evolve.core.candidate import Candidate, estimate_tokens  # noqa: E402
from harness_evolve.core.decision import Prediction  # noqa: E402
from harness_evolve.evidence.directives import (  # noqa: E402
    ConstraintLedger, render_constraints,
)
from harness_evolve.runners.cached import CachedRunner  # noqa: E402


def load_corpus(path: Path) -> list:
    """Every recorded rollout, whatever it was originally run for."""
    runner = CachedRunner(corpus_dir=path if path.is_dir() else None,
                          records=[] if path.is_dir() else _read_file(path))
    return [rec.to_rollout() for rec in runner._records.values()]


def _read_file(path: Path) -> list:
    from harness_evolve.runners.cached import RolloutRecord

    out = []
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(RolloutRecord.from_dict(json.loads(line), source=str(path)))
        except Exception:
            continue
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", required=True, type=Path,
                    help="rollouts.jsonl written by RecordingRunner")
    ap.add_argument("--adapter", required=True, type=Path,
                    help="adapter directory to improve")
    ap.add_argument("--out", type=Path, help="where to write the improved adapter")
    ap.add_argument("--component", default="constraints",
                    help="component the derived constraints are written into")
    ap.add_argument("--min-support", type=int, default=2,
                    help="observations of the same complaint before it becomes a rule")
    ap.add_argument("--plugin-dir", type=Path, default=REPO_ROOT / "plugin",
                    help="scaffolding source when materialising")
    args = ap.parse_args()

    if not args.corpus.exists():
        print(f"no corpus at {args.corpus}", file=sys.stderr)
        return 2

    rollouts = load_corpus(args.corpus)
    print(f"corpus: {len(rollouts)} rollout(s), spent for other purposes")

    ledger = ConstraintLedger(min_support=args.min_support)
    events = [ev for r in rollouts for ev in r.validator_events]
    ledger.observe(events)
    print(f"validator events: {len(events)}")
    print(f"  {ledger.summary()}")

    if not ledger.directives:
        print("\nNo validator output in this corpus. Either the runs did not "
              "enable the validator, or the runner did not record its events — "
              "check that before concluding the mechanism does not apply here.")
        return 1

    if ledger.actionable_fraction == 0.0:
        print("\nThis validator emits verdicts, not repair directives: it says a "
              "deck is wrong without naming what would have been right. The "
              "mechanism does not apply to it, and no constraint can be derived "
              "at zero cost. That is a real answer, not a failure.")
        return 1

    constraints = ledger.constraints()
    print(f"\nderived {len(constraints)} constraint(s) at support >= {args.min_support}:")
    for c in constraints:
        print(f"  [{c.support}x] {c.prose}")

    if not constraints:
        print(f"\nNothing repeated {args.min_support} times. A single complaint is "
              "one agent's slip; encoding it would be the over-specification "
              "failure. Re-run with more rollouts rather than lowering support.")
        return 1

    if not args.out:
        print("\n(no --out given; nothing written)")
        return 0

    candidate = Candidate.from_dir(args.adapter)
    spec = candidate.manifest.components.get(args.component)
    if spec is None or not spec.path:
        print(f"\nadapter has no writable component {args.component!r}; "
              f"available: {sorted(candidate.manifest.components)}", file=sys.stderr)
        return 2

    existing = candidate.files.get(spec.path, "")
    block = render_constraints(constraints)
    merged = f"{existing.rstrip()}\n\n{block}\n" if existing.strip() else block

    if spec.budget_tokens and estimate_tokens(merged) > spec.budget_tokens:
        # The budget is a hard gate everywhere else and it stays one here. A
        # mechanism that is free in rollouts is not free in the tokens every
        # future rollout must read.
        print(f"\nderived constraints would take {args.component} to "
              f"~{estimate_tokens(merged)} tokens, over its budget of "
              f"{spec.budget_tokens}. Raise the budget deliberately or raise "
              "--min-support; do not silently overflow it.", file=sys.stderr)
        return 2

    child = candidate.with_edits(
        {spec.path: merged},
        predictions=[Prediction(
            component=args.component,
            targets_category="bad_attribute_value",
            rationale=(
                f"{len(constraints)} constraint(s) the validator already stated, "
                f"mined from {len(rollouts)} rollouts spent for other purposes"
            ),
            evidence_refs=tuple(f"validator:{c.entry.get('kind')}" for c in constraints),
        )],
    )
    child.validate()
    child.materialize(args.out, scaffolding_from=args.plugin_dir, overwrite=True)

    print(f"\nwrote {child.cid} to {args.out}")
    print(f"  {args.component}: ~{estimate_tokens(existing)} -> "
          f"~{estimate_tokens(merged)} tokens")
    print("  additional rollouts spent: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
