#!/usr/bin/env python3
"""Lower-bound check: can the search beat a random-edit control at all?

This runs entirely against the mock simulator and mock runner, so it says
**nothing about GEOS**. What it does say is worth knowing before any real
infrastructure exists:

* The mock world has a *planted* gradient — specific marker phrases raise
  quality, over-long adapters cost more and score less, and zero-score
  terminations are suppressed by declared constraints. The optimum is known.
* If the search cannot beat a random-edit control **here**, on a world where the
  gradient is planted and the noise is controllable, it will certainly not do so
  on a domain-knowledge-bound task with a near-ceiling reward. That makes this a
  cheap falsification test of the machinery, run before spending anything.
* It also exercises the full stack end to end — search, gate, archive, ledger,
  paired statistics, report — which is how we find out that the pieces compose
  into an experiment rather than merely into a library.

The control is not a straw man. `RandomEditProposer` respects every rule the
real proposer does: one bounded edit, a prediction attached, budgets enforced,
same gate. It simply brings no diagnosis. Since harness-*updating* capability is
reported roughly flat across model tiers (arXiv:2605.30621), "does judgement
beat churn under this gate" is a live question with a publishable answer either
way.

Usage:
    python3 scripts/experiment_proposer_control.py [--trials 5] [--budget 12]
"""
from __future__ import annotations

import argparse
import random
import statistics
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from harness_evolve.core.candidate import Candidate  # noqa: E402
from harness_evolve.core.manifest import ComponentSpec, Manifest, StopPolicy  # noqa: E402
from harness_evolve.core.search import Search, SearchConfig  # noqa: E402
from harness_evolve.evaluation.baselines import BudgetLedger  # noqa: E402
from harness_evolve.evaluation.slices import build_slices, stats_from_rollouts  # noqa: E402
from harness_evolve.evaluation.stats import ArmScores, compare  # noqa: E402
from harness_evolve.proposers.scripted import RandomEditProposer  # noqa: E402
from harness_evolve.runners.mock import MockRunner, MockWorld  # noqa: E402
from harness_evolve.simulators.mock import MockSimulator  # noqa: E402

TASKS = [f"task_{i}" for i in range(10)]
GROUPS = {t: ["poro", "frac", "thermal", "flow"][i % 4] for i, t in enumerate(TASKS)}

#: Phrases the mock world rewards. The "diagnostic" arm knows them; the control
#: draws from a pool that mixes them with plausible-but-inert filler, which is
#: the honest analogue of a proposer that reasons versus one that does not.
USEFUL = (
    "- name the required sections explicitly",
    "- set discretization to match a defined method",
    "- every materialList entry must name a Constitutive block",
    "- check targetRegions against defined regions",
    "- do NOT add more blocks than the physics needs",
)
INERT = (
    "- be careful and precise",
    "- read the documentation first",
    "- think step by step about the problem",
    "- consider the physics involved",
    "- double-check your work before finishing",
    "- aim for high quality output",
)


def make_seed() -> Candidate:
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


def make_runner(root: Path, seed: int) -> MockRunner:
    world = MockWorld(
        task_difficulty={"task_0": -0.35, "task_1": -0.30, "task_2": -0.25},
        noise=0.04,
        zero_rate=0.15,
    )
    return MockRunner(MockSimulator(), world=world, root=root / f"run{seed}")


def run_arm(label: str, lines, trials: int, budget: int, root: Path):
    """Run ``trials`` independent searches and return the best candidate of each."""
    per_trial = []
    for trial in range(trials):
        runner = make_runner(root, trial)
        ledger = BudgetLedger()
        search = Search(
            runner,
            RandomEditProposer(lines=lines, rng=random.Random(1000 + trial)),
            ledger=ledger,
            config=SearchConfig(budget_candidates=budget, seeds=(1, 2),
                                screen_tasks=2, screen_seeds=(1,)),
        )
        result = search.run(make_seed(), TASKS)
        # Re-score the winner at fresh seeds so the reported number is not the
        # one selection maximised.
        final = runner.run_many(result.best.candidate, TASKS, (7, 8, 9))
        per_trial.append(
            {
                "trial": trial,
                "best_cid": result.best.cid,
                "search_mean": result.best.mean,
                "final": final,
                "accepted": search.log.acceptance_rate(),
                "rollouts": sum(e.rollouts for e in ledger.entries),
                "generation": result.best.generation,
            }
        )
    return per_trial


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--trials", type=int, default=5)
    ap.add_argument("--budget", type=int, default=12)
    args = ap.parse_args()

    root = Path(tempfile.mkdtemp(prefix="proposer_control_"))
    print(f"mock world, {args.trials} trials x {args.budget} candidates, root={root}\n")

    arms = {
        "informed": run_arm("informed", USEFUL, args.trials, args.budget, root),
        "control": run_arm("control", USEFUL + INERT, args.trials, args.budget, root),
    }

    print(f"{'arm':10s} {'trial':>5s} {'gen':>4s} {'accept':>7s} "
          f"{'rollouts':>9s} {'final mean':>11s}")
    scores = {}
    for label, trials in arms.items():
        finals = []
        for t in trials:
            m = statistics.mean(r.score.value for r in t["final"])
            finals.append(m)
            print(f"{label:10s} {t['trial']:>5d} {t['generation']:>4d} "
                  f"{t['accepted']:>6.0%} {t['rollouts']:>9d} {m:>11.4f}")
        scores[label] = finals
        print(f"{label:10s} {'MEAN':>5s} {'':>4s} {'':>7s} {'':>9s} "
              f"{statistics.mean(finals):>11.4f}\n")

    # Paired comparison on the pooled final rollouts, using the real machinery.
    control_arm = ArmScores.from_rollouts(
        "control", [r for t in arms["control"] for r in t["final"]]
    )
    informed_arm = ArmScores.from_rollouts(
        "informed", [r for t in arms["informed"] for r in t["final"]]
    )
    cmp = compare(control_arm, informed_arm)

    print("=" * 66)
    print("PAIRED COMPARISON  (baseline = control, treatment = informed)")
    print("=" * 66)
    print(f"  mean delta            {cmp.mean_delta:+.4f}")
    print(f"  conclusive            {cmp.conclusive}")
    b = cmp.bootstrap
    print(f"  bootstrap CI          {b.interval or 'REFUSED'}")
    if b.refusal:
        print(f"    refusal: {b.refusal}")
    print(f"  permutation p         {cmp.permutation.p_value:.3f} "
          f"(min achievable {cmp.permutation.min_achievable_p:.3f})")
    w = cmp.wlt
    print(f"  win / loss / tie      {len(w.wins)} / {len(w.losses)} / {len(w.ties)}"
          f"   (noise band {w.noise_band:.3f}, {w.band_source})")

    print("\n  --- reliability, which the mean cannot show ---")
    for name, tail in (("control", cmp.tail_baseline), ("informed", cmp.tail_treatment)):
        ci = tail.zero_rate_ci.interval
        print(f"  {name:9s} zero runs {tail.zero_runs:>3d}/{tail.n_runs}  "
              f"rate {tail.zero_runs / tail.n_runs:.3f} "
              f"CI [{ci.low:.3f}, {ci.high:.3f}]   "
              f"catastrophic {tail.catastrophic_runs:>3d}")
    r = cmp.rescues
    print(f"  rescued {len(r.rescued)} task(s), lost {len(r.lost)}: "
          f"{', '.join(r.rescued) or '-'}")

    # A sanity check that matters more than the comparison: did either arm move
    # at all? A search that cannot improve on a planted gradient is broken, and
    # that is a conclusion about the code, not about the method.
    seed_runner = make_runner(root, 0)
    seed_final = seed_runner.run_many(make_seed(), TASKS, (7, 8, 9))
    seed_mean = statistics.mean(r.score.value for r in seed_final)
    print(f"\nseed adapter at the same final seeds: {seed_mean:.4f}")
    for label, finals in scores.items():
        delta = statistics.mean(finals) - seed_mean
        verdict = "moved" if delta > 0.02 else "did NOT move"
        print(f"  {label:10s} {delta:+.4f}  -> {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
