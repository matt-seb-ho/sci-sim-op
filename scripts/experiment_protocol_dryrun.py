#!/usr/bin/env python3
"""Dry-run the full evaluation protocol on the mock, end to end.

This produces the *shape* of the document the real experiment would produce:
search, compute-matched baselines, slice discipline, paired statistics, tail
statistics, budget ledger, and a verdict — from the real machinery, on a
synthetic world.

Why bother before any real run exists: the protocol is the part of this project
that decides whether a result gets believed, and a protocol that has never been
executed is a plan, not a protocol. Running it against a world whose answer we
already know is how we find out that the pieces produce a coherent document, that
the verdict logic fires, and that the numbers land where the design says they
should — none of which is worth discovering with a real budget attached.

The predecessor system reported a headline gain with no compute-matched baseline
anywhere. This is the machinery that makes that impossible to repeat by
accident.

Usage:
    python3 scripts/experiment_protocol_dryrun.py [--budget 10] [--out report.md]
"""
from __future__ import annotations

import argparse
import statistics
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from harness_evolve.core.candidate import Candidate  # noqa: E402
from harness_evolve.core.manifest import ComponentSpec, Manifest, StopPolicy  # noqa: E402
from harness_evolve.core.search import Search, SearchConfig  # noqa: E402
from harness_evolve.evaluation.baselines import (  # noqa: E402
    BaselineError, BudgetLedger, run_matched_suite,
)
from harness_evolve.evaluation.protocol import EvaluationProtocol  # noqa: E402
from harness_evolve.evaluation.report import ArmConfig, EvaluationReport  # noqa: E402
from harness_evolve.evaluation.slices import build_slices, stats_from_rollouts  # noqa: E402
from harness_evolve.evaluation.stats import ArmScores, compare  # noqa: E402
from harness_evolve.evidence.corpus import build_evidence  # noqa: E402
from harness_evolve.proposers.scripted import RandomEditProposer  # noqa: E402
from harness_evolve.runners.mock import MockRunner, MockWorld  # noqa: E402
from harness_evolve.simulators.mock import MockSimulator  # noqa: E402

MODEL = "mock-v1"
HARNESS = "harness-evolve/mock"
POOL = [f"task_{i}" for i in range(14)]
HELD_OUT = [f"task_{i}" for i in range(10, 14)]

USEFUL_LINES = (
    "- name the required sections explicitly",
    "- set discretization to match a defined method",
    "- every materialList entry must name a Constitutive block",
    "- do NOT add more blocks than the physics needs",
)


def seed_candidate() -> Candidate:
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--budget", type=int, default=10)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    root = Path(tempfile.mkdtemp(prefix="protocol_dryrun_"))
    runner = MockRunner(
        MockSimulator(),
        world=MockWorld(
            task_difficulty={"task_0": -0.35, "task_1": -0.30, "task_10": -0.35,
                             "task_11": -0.30},
            noise=0.04, zero_rate=0.15,
        ),
        root=root,
    )
    seed = seed_candidate()

    # -- slices, from a baseline that identifies what is in play -----------
    print("== 1. baseline and slice construction ==")
    search_pool = [t for t in POOL if t not in HELD_OUT]
    baseline_rollouts = runner.run_many(seed, search_pool, (1, 2, 3))
    plan = build_slices(
        POOL, stats=stats_from_rollouts(baseline_rollouts),
        anchor_size=6, probe_size=3, held_out=HELD_OUT,
    )
    print(plan.render())

    protocol = EvaluationProtocol(
        anchor=tuple(plan.anchor), probe=tuple(plan.probe),
        held_out=tuple(plan.held_out),
    )

    # -- search ------------------------------------------------------------
    print("\n== 2. search (anchor slice only) ==")
    ledger = BudgetLedger()
    search = Search(
        runner,
        RandomEditProposer(lines=USEFUL_LINES),
        ledger=ledger,
        evidence_builder=lambda entry, rollouts: build_evidence(
            rollouts, candidate_id=entry.cid, parent_scores=entry.scores
        ),
        config=SearchConfig(budget_candidates=args.budget, seeds=(1, 2),
                            screen_tasks=2, probe_tasks=1, probe_every=4),
    )
    anchor = protocol.request("anchor", "selection", requester="search")
    probe = protocol.request("probe", "evidence", requester="search")
    result = search.run(seed, anchor, probe_tasks=probe)
    print(result.summary())

    search_rollouts = sum(e.rollouts for e in ledger.entries if e.arm == "search")
    print(f"\nsearch spent {search_rollouts} rollouts")

    # -- held-out, touched once -------------------------------------------
    print("\n== 3. held-out evaluation, at a matched budget ==")
    release = protocol.release_held_out(
        requester="protocol dry run",
        candidate_id=result.best.cid,
        note="final comparison, one candidate",
    )
    eval_tasks = tuple(getattr(release, "tasks", release))
    final_seeds = (7, 8, 9)

    # The sequential arm is expressed through the harness's own stop policy,
    # which caps retries. Past a certain search budget the matched k exceeds that
    # cap, and matching it would mean changing the harness -- which unfreezes the
    # thing the whole claim holds fixed. When that happens the arm is reported as
    # missing rather than quietly dropped, because "we could not construct a
    # comparable sequential baseline at this budget" is itself a finding about
    # the comparison, not a detail of it.
    missing_arms: list[str] = []
    try:
        baselines, ledger, budget_plan = run_matched_suite(
            runner, seed, eval_tasks,
            search_rollouts=search_rollouts, seeds=final_seeds, ledger=ledger,
        )
    except BaselineError as exc:
        print(f"  sequential arm unavailable: {exc}")
        missing_arms.append(f"sequential refinement — {exc}")
        baselines, ledger, budget_plan = run_matched_suite(
            runner, seed, eval_tasks,
            search_rollouts=search_rollouts, seeds=final_seeds, ledger=ledger,
            include_sequential=False,
        )
    print(f"matched k = {budget_plan.k} ({budget_plan.note}); "
          f"surplus {budget_plan.surplus:+d} rollouts")

    evolved = runner.run_many(result.best.candidate, eval_tasks, final_seeds)
    ledger.record_rollouts("evolved", evolved, note="held-out evaluation")
    treatment = ArmScores.from_rollouts("evolved adapter", evolved)

    comparisons = {}
    for key, res in baselines.items():
        comparisons[key] = compare(res.arm(), treatment)
        print(f"  vs {key:22s} mean delta {comparisons[key].mean_delta:+.4f}  "
              f"conclusive={comparisons[key].conclusive}")

    # -- report ------------------------------------------------------------
    configs = {
        "evolved": ArmConfig(
            key="evolved", label="evolved adapter", model=MODEL, harness=HARNESS,
            adapter_cid=result.best.cid, generation=result.best.generation,
            stop_policy=str(result.best.candidate.manifest.stop_policy.feedback_shape),
            simulator="mock", seeds=final_seeds, scaling="harness evolution",
        ),
    }
    for key, res in baselines.items():
        configs[key] = ArmConfig(
            key=key, label=res.arm_label, model=MODEL, harness=HARNESS,
            adapter_cid=seed.cid, simulator="mock", seeds=final_seeds,
            scaling=getattr(res, "scaling", "test-time"),
        )

    report = EvaluationReport(
        title="Protocol dry run — mock simulator",
        treatment_key="evolved",
        configs=configs,
        comparisons=comparisons,
        ledger=ledger,
        plan=budget_plan,
        protocol=protocol,
        caveats=tuple(
            [
                "Synthetic world with a planted gradient. Says nothing about "
                "any real simulator.",
                "The proposer is a random-edit control drawing from a useful "
                "line pool, not a reasoning proposer.",
            ]
            + [f"ARM MISSING: {m}" for m in missing_arms]
        ),
    )
    text = report.render()
    print("\n" + "=" * 70)
    print(text)

    if args.out:
        Path(args.out).write_text(text)
        print(f"\nwritten to {args.out}")

    v = report.verdict()
    print(f"\nVERDICT: {getattr(v, 'outcome', v)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
