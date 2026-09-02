#!/usr/bin/env python3
"""harness-evolve command line.

Subcommands:

    demo       run a full search on the mock simulator — no keys, no Docker, ~30s
    slices     build and print an anchor / probe / held-out plan for a task pool
    audit      run the contamination gate over an adapter directory
    search     run a real search (requires a configured runner and simulator)
    preflight  report everything that would block a real run, and stop

``preflight`` exists because the expensive failure in this kind of system is not
a crash, it is a run that completes and means nothing. Every known way for that
to happen -- a validator the container cannot see, a stop policy the hook never
reads, a hygiene corpus built from nothing -- is checked here up front, where
the answer costs a second instead of a day.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from harness_evolve.core.candidate import Candidate  # noqa: E402
from harness_evolve.core.manifest import (  # noqa: E402
    ComponentSpec, Manifest, StopPolicy, resolve_known_checks,
)
from harness_evolve.core.search import Search, SearchConfig  # noqa: E402
from harness_evolve.evaluation.baselines import BudgetLedger  # noqa: E402
from harness_evolve.evaluation.slices import build_slices, stats_from_rollouts  # noqa: E402
from harness_evolve.evidence.corpus import build_evidence  # noqa: E402
from harness_evolve.hygiene.corpus import GroundTruthCorpus  # noqa: E402
from harness_evolve.integration import DEFAULT_RECEIPT, check_r1  # noqa: E402
from harness_evolve.hygiene.gate import check_candidate  # noqa: E402
from harness_evolve.proposers.scripted import RandomEditProposer  # noqa: E402
from harness_evolve.runners.recording import RecordingRunner  # noqa: E402
from harness_evolve.simulators.base import SimulatorRegistry  # noqa: E402


# ---------------------------------------------------------------------------
# preflight
# ---------------------------------------------------------------------------

def cmd_preflight(args: argparse.Namespace) -> int:
    """Everything that would make a real run meaningless, checked up front."""
    problems: list[str] = []
    notes: list[str] = []

    print("== simulator ==")
    try:
        sim = SimulatorRegistry.get(args.simulator)
    except KeyError as exc:
        print(f"  FAIL {exc}")
        return 2
    caps = sim.capabilities()
    print(f"  {sim.describe()}")
    print(f"  searchable: {caps.searchable}")
    if not caps.searchable:
        problems += [f"simulator: {g}" for g in caps.gaps()]
    for reason in sim.preflight():
        problems.append(f"environment: {reason}")

    print("\n== checks ==")
    known = resolve_known_checks()
    print(f"  registered: {sorted(known)}")
    if len(known) <= 4:
        notes.append(
            "only the fallback check names resolved; the check registry may not "
            "be importable, which silently narrows the search space"
        )

    print("\n== contamination corpus ==")
    if args.ground_truth_dir and Path(args.ground_truth_dir).is_dir():
        corpus = GroundTruthCorpus.from_ground_truth_dir(Path(args.ground_truth_dir))
        print(f"  {corpus.summary()}")
        if corpus.is_empty:
            problems.append(
                "ground-truth corpus is empty: the hygiene gate would pass "
                "everything, which is worse than no gate because it reads as "
                "coverage"
            )
    else:
        problems.append(
            f"ground-truth directory not found ({args.ground_truth_dir}); the "
            "content, numeric and structural hygiene rules would be inert"
        )

    print("\n== stop policy reaches the hook ==")
    policy = StopPolicy(retries=2, feedback_shape="errors_plus_tables",
                        checks=("parse", "geosx_validate"))
    env = policy.to_env()
    for k, v in env.items():
        print(f"  {k}={v}")
    # Not an unconditional blocker any more: R1 is now a receipt written by
    # repo3's verify_r1_feedback_channel.py, and checked here against the SHA of
    # the hook actually on disk. Editing the hook invalidates it, which is the
    # only way a green check on an observation stays honest.
    status = check_r1(REPO_ROOT / DEFAULT_RECEIPT)
    if status.verified:
        print(f"  R1 VERIFIED: {status.reason}")
    else:
        problems.append(f"R1 not verified: {status.reason}")

    print("\n== verdict ==")
    for n in notes:
        print(f"  note: {n}")
    if problems:
        for p in problems:
            print(f"  BLOCKER: {p}")
        print(f"\n{len(problems)} blocker(s). A run started now would complete "
              "and mean less than it appears to.")
        return 1
    print("  ready")
    return 0


# ---------------------------------------------------------------------------
# demo
# ---------------------------------------------------------------------------

def _demo_seed() -> Candidate:
    return Candidate(
        manifest=Manifest(
            components={
                "primer": ComponentSpec("primer", "prose", path="PRIMER.md",
                                        budget_tokens=150),
                "memory": ComponentSpec("memory", "itemized",
                                        path="memory/cheatsheet.md",
                                        budget_tokens=250),
                "stop_policy": ComponentSpec("stop_policy", "config"),
            },
            stop_policy=StopPolicy(retries=2, checks=("parse",)),
        ),
        files={"PRIMER.md": "author a valid deck",
               "memory/cheatsheet.md": "- start from an analogous case"},
    )


def cmd_demo(args: argparse.Namespace) -> int:
    """A complete search on the mock simulator. No API key, no Docker."""
    from harness_evolve.runners.mock import MockRunner, MockWorld
    from harness_evolve.simulators.mock import MockSimulator

    root = Path(tempfile.mkdtemp(prefix="evolve_demo_"))
    tasks = [f"task_{i}" for i in range(8)]
    probe = ["probe_a", "probe_b"]

    # Wrapped in a recorder so the demo exercises the resume path too: re-running
    # with the same --corpus replays instead of re-executing, which is what makes
    # a real multi-hour search survivable.
    inner = MockRunner(
        MockSimulator(),
        world=MockWorld(task_difficulty={"task_0": -0.35, "task_1": -0.30},
                        noise=0.04, zero_rate=0.15),
        root=root,
    )
    runner = RecordingRunner(inner, Path(args.corpus) if args.corpus
                             else root / "rollouts.jsonl")

    print("== baseline, to identify which tasks are in play ==")
    seed = _demo_seed()
    baseline = runner.run_many(seed, tasks, (1, 2, 3))
    stats = stats_from_rollouts(baseline)
    plan = build_slices(tasks, stats=stats, anchor_size=args.anchor, probe_size=2)
    print(plan.render())

    print("\n== search ==")
    ledger = BudgetLedger()
    search = Search(
        runner,
        RandomEditProposer(lines=(
            "- name the required sections explicitly",
            "- set discretization to match a defined method",
            "- do NOT add more blocks than the physics needs",
        )),
        ledger=ledger,
        evidence_builder=lambda entry, rollouts: build_evidence(
            rollouts, candidate_id=entry.cid, parent_scores=entry.scores
        ),
        decision_log_path=root / "decisions.jsonl",
        config=SearchConfig(budget_candidates=args.budget, seeds=(1, 2),
                            screen_tasks=2, probe_tasks=1, probe_every=3),
    )
    result = search.run(seed, plan.anchor, probe_tasks=probe)
    print(result.summary())

    print("\n== the winner, re-scored at fresh seeds ==")
    final = runner.run_many(result.best.candidate, plan.anchor, (7, 8, 9))
    seed_final = runner.run_many(seed, plan.anchor, (7, 8, 9))
    fm = statistics.mean(r.score.value for r in final)
    sm = statistics.mean(r.score.value for r in seed_final)
    fz = sum(1 for r in final if r.score.value <= 1e-9) / len(final)
    sz = sum(1 for r in seed_final if r.score.value <= 1e-9) / len(seed_final)
    print(f"  seed    mean {sm:.4f}   zero rate {sz:.3f}")
    print(f"  best    mean {fm:.4f}   zero rate {fz:.3f}")
    print(f"  delta   {fm - sm:+.4f} mean, {fz - sz:+.3f} zero rate")

    # Selection ran at seeds (1, 2); this re-score runs at (7, 8, 9). The gate
    # can only bound what it measured, so a gap between the two is seed
    # overfitting -- and it is precisely what a held-out re-score exists to
    # reveal. Naming it here keeps it from reading as a bug in the loop.
    search_mean = result.best.mean
    if abs(search_mean - fm) > 0.05:
        print(f"\n  NOTE: the winner scored {search_mean:.4f} at the seeds "
              f"selection used and {fm:.4f} at fresh seeds. That gap is "
              "overfitting to the search seeds, which no gate can bound because "
              "no gate saw those seeds. It is why the protocol re-scores at "
              "held-out seeds before any number is reported.")
    if fz > sz + 0.05:
        print(f"\n  NOTE: the winner's zero rate at fresh seeds ({fz:.3f}) is "
              f"above the seed adapter's ({sz:.3f}). With 2 search seeds and a "
              "stochastic zero rate, some of this is unavoidable; more search "
              "seeds is the only fix that addresses the cause rather than the "
              "symptom.")
    if fm <= sm + 0.02:
        print("\n  The search returned (approximately) its seed. That is a real "
              "outcome, not an error -- see docs/EXPERIMENT_01_proposer_control.md")

    print(f"\n{runner.summary()}")
    print(f"artifacts: {root}")
    print(f"decision log: {root / 'decisions.jsonl'}")
    return 0


# ---------------------------------------------------------------------------
# slices, audit
# ---------------------------------------------------------------------------

def cmd_slices(args: argparse.Namespace) -> int:
    pool = [l.strip() for l in Path(args.tasks).read_text().splitlines()
            if l.strip() and not l.startswith("#")]
    held = [l.strip() for l in Path(args.held_out).read_text().splitlines()
            if l.strip() and not l.startswith("#")] if args.held_out else []
    stats = None
    if args.stats:
        raw = json.loads(Path(args.stats).read_text())
        from harness_evolve.evaluation.slices import TaskStat

        stats = {
            t: TaskStat(t, tuple(v.get("scores", [])), v.get("group", ""))
            for t, v in raw.items()
        }
    plan = build_slices(pool, stats=stats, anchor_size=args.anchor,
                        probe_size=args.probe, held_out=held)
    print(plan.render())
    if args.out:
        Path(args.out).write_text(json.dumps(
            {"anchor": list(plan.anchor), "probe": list(plan.probe),
             "held_out": list(plan.held_out), "roles": plan.roles,
             "rationale": plan.rationale, "warnings": plan.warnings},
            indent=2,
        ))
        print(f"\nwritten to {args.out}")
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    """Which search budgets can their own baselines actually match?"""
    from harness_evolve.evaluation.budget import estimate_cost, plan_budget

    report = plan_budget(
        n_held_out=args.held_out, n_seeds=args.seeds,
        anchor_size=args.anchor, search_seeds=args.search_seeds,
        max_k=args.max_k,
    )
    print(report.render(wanted=args.wanted or None))
    print("\n rough cost of each feasible budget "
          "(order of magnitude, not a quotation):")
    for o in report.feasible():
        est = estimate_cost(o.search_rollouts, workers=args.workers)
        print(f"  {o.search_rollouts:>5d} rollouts "
              f"({report.candidates_for(o):>3d} candidates): "
              f"${est['usd']:>6.2f}, {est['wall_hours']:>5.1f}h at "
              f"{args.workers} workers")
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    from harness_evolve.hygiene.audit import main as audit_main

    sys.argv = ["audit", "--adapter-dir", args.adapter_dir]
    if args.ground_truth_dir:
        sys.argv += ["--ground-truth-dir", args.ground_truth_dir]
    return audit_main()


# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        prog="evolve", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("demo", help="full search on the mock simulator")
    p.add_argument("--budget", type=int, default=10)
    p.add_argument("--anchor", type=int, default=6)
    p.add_argument("--corpus", default="",
                   help="reuse a rollout corpus; re-running with the same path "
                        "replays instead of re-executing")
    p.set_defaults(fn=cmd_demo)

    p = sub.add_parser("preflight", help="report what would block a real run")
    p.add_argument("--simulator", default="mock")
    p.add_argument("--ground-truth-dir", default="")
    p.set_defaults(fn=cmd_preflight)

    p = sub.add_parser("slices", help="build an anchor / probe / held-out plan")
    p.add_argument("--tasks", required=True, help="one task id per line")
    p.add_argument("--held-out", default="")
    p.add_argument("--stats", default="", help="JSON: task -> {scores, group}")
    p.add_argument("--anchor", type=int, default=8)
    p.add_argument("--probe", type=int, default=4)
    p.add_argument("--out", default="")
    p.set_defaults(fn=cmd_slices)

    p = sub.add_parser("plan", help="search budgets whose baselines can match them")
    p.add_argument("--held-out", type=int, default=10)
    p.add_argument("--seeds", type=int, default=5, help="seeds at final evaluation")
    p.add_argument("--anchor", type=int, default=8)
    p.add_argument("--search-seeds", type=int, default=2)
    p.add_argument("--max-k", type=int, default=12)
    p.add_argument("--wanted", type=int, default=0)
    p.add_argument("--workers", type=int, default=4)
    p.set_defaults(fn=cmd_plan)

    p = sub.add_parser("audit", help="contamination gate over an adapter")
    p.add_argument("--adapter-dir", required=True)
    p.add_argument("--ground-truth-dir", default="")
    p.set_defaults(fn=cmd_audit)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
