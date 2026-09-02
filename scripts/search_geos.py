#!/usr/bin/env python3
"""A real adapter search against GEOS, with its baselines budgeted in from the start.

This is the driver `scripts/evolve.py`'s docstring promised and did not have. It
wires the four adopted methods to the real evaluator:

* **Self-Harness regression gate** (`core/acceptance.RegressionGate`) -- accept
  only when nothing fell off a cliff, not when the mean rose.
* **AHE decision observability** (`core/decision.DecisionLog`) -- every edit
  carries a falsifiable prediction, checked against the next round.
* **GEPA outer loop** (`core/archive.Archive`) -- Pareto over per-task scores, so
  a candidate that rescues one task survives an unremarkable average.
* **ACE delta updates** (`core/candidate.with_edits` under manifest token caps) --
  itemized edits, hard budget, no monotone growth.

and to the three things this campaign added tonight: a hardened free-roster
backend, a verified reward channel, and a runner that can tell an infrastructure
failure from a model failure.

Three properties this driver has deliberately:

**Everything runs through a `RecordingRunner`.** Rollouts are the only expensive
thing here; once on disk they are replayed for free. A search interrupted by a
throttle, a reboot, or a morning deadline resumes instead of restarting, and every
statistic can be recomputed afterwards without spending anything.

**Baselines are budgeted from the start, not added afterwards.** arXiv:2607.12227
finds automatic harness evolution does not consistently beat best-of-k even where
sampling is cheap. A win that cannot be matched on budget is not a win, so the
search's own rollout spend sets the baselines' k, and the ledger is printed.

**The stop policy's searchable check set is pinned to what the hook implements.**
`required_sections` is a registered check that the *container* hook cannot run
(see worklog 2.6). Searching over it would vary a knob nothing reads, which is
the defect this whole campaign exists to remove.

    python3 scripts/search_geos.py --stage baseline --tasks 4 --seeds 1
    python3 scripts/search_geos.py --stage search   --budget 6
    python3 scripts/search_geos.py --stage baselines
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _geos import DATA, REPO, REPO3, runner as geos_runner  # noqa: E402

REPO3_PLUGIN = REPO3 / "plugin"

sys.path.insert(0, str(REPO / "src"))
from harness_evolve.core.acceptance import RegressionGate  # noqa: E402
from harness_evolve.core.candidate import Candidate  # noqa: E402
from harness_evolve.core.search import Search, SearchConfig  # noqa: E402
from harness_evolve.evaluation.baselines import BudgetLedger, run_matched_suite  # noqa: E402
from harness_evolve.evaluation.slices import build_slices, stats_from_rollouts  # noqa: E402
from harness_evolve.evidence.corpus import build_evidence  # noqa: E402
from harness_evolve.hygiene.corpus import GroundTruthCorpus  # noqa: E402
from harness_evolve.hygiene.gate import (  # noqa: E402
    GateConfig, check_candidate, train_profile,
)
from harness_evolve.integration import DEFAULT_RECEIPT, check_r1  # noqa: E402
from harness_evolve.proposers.backends import free_window_backend  # noqa: E402
from harness_evolve.proposers.llm import LLMProposer, LLMProposerConfig  # noqa: E402
from harness_evolve.runners.parallel import ParallelRunner  # noqa: E402
from harness_evolve.runners.recording import RecordingRunner  # noqa: E402

#: Pinned to what repo3's stop hook actually implements. See module docstring.
HOOK_IMPLEMENTED_CHECKS = ("parse", "geosx_validate")

#: The four ingredients goals §1.3 exists to ablate, each switchable on its own.
#: The deliverable of this project is *which ingredient carries the gain*, not a
#: leaderboard number, so the ablation has to be a flag rather than a branch --
#: an ablation you have to edit code to run is one that gets run once.
ABLATABLE = ("gate", "evidence", "pareto", "delta")


def apply_ablations(search, proposer, ablate: set[str]) -> list[str]:
    """Disable named ingredients on an already-wired search. Returns a manifest.

    Each switch removes exactly one mechanism and leaves the rest intact, so the
    contrast is attributable. What is *not* ablatable here is the reward channel
    itself: a search with no reward is what v1 was, and reproducing it is not an
    ablation, it is the bug.
    """
    notes: list[str] = []
    unknown = ablate - set(ABLATABLE)
    if unknown:
        raise SystemExit(f"unknown ablation(s) {sorted(unknown)}; known: {ABLATABLE}")

    if "gate" in ablate:
        # Self-Harness's regression gate, off: accept every proposal that parses
        # and clears hygiene. This is v1's selection rule, which is to say none.
        search.gate = RegressionGate(
            max_task_regression=1.0, max_mean_regression=1.0,
            max_efficiency_ratio=1e9, require_zero_rate_non_increasing=False,
            max_cumulative_regression=1.0,
        )
        notes.append("gate: regression gate disabled (accept-if-parses)")

    if "evidence" in ablate:
        # AHE's richer evidence, off: the proposer sees L0 (scores only) instead
        # of L2 (validator output, failure categories, trajectory excerpts).
        config = getattr(proposer, "config", None)
        if config is None or not hasattr(config, "evidence_level"):
            # Say so rather than silently running an arm that ablated nothing --
            # a no-op ablation reported as an ablation is a fabricated control.
            raise SystemExit(
                f"--ablate evidence needs a proposer with an evidence_level "
                f"setting; {type(proposer).__name__} has none"
            )
        proposer.config = replace(config, evidence_level=0)
        notes.append("evidence: proposer sees L0 (scores only) not L2")

    if "pareto" in ablate:
        # GEPA's frontier, off: mean-based hill climbing. Predicted to discard
        # single-task rescues, which is where the measured effect in this task
        # actually lives.
        def best_mean_parent(exploratory: bool = False):
            pool = search.archive.accepted or search.archive.entries
            return max(pool, key=lambda e: e.mean) if pool else None

        search._select_parent = best_mean_parent
        notes.append("pareto: frontier replaced by best-mean hill climbing")

    if "delta" in ablate:
        # ACE's hard token cap, off. v1 grew its primer 270 B -> 3159 B in three
        # unmonitored rounds; this is that condition, deliberately.
        notes.append("delta: component token budgets lifted (see --budget-multiplier)")
    return notes


def lift_budgets(candidate: Candidate, factor: float = 100.0) -> Candidate:
    """Return the candidate with its component token caps effectively removed."""
    manifest = candidate.manifest
    components = {
        name: replace(spec, budget_tokens=int((spec.budget_tokens or 0) * factor) or 10**6)
        for name, spec in manifest.components.items()
    }
    return replace(candidate, manifest=replace(manifest, components=components))


def build_runner(out: Path, timeout_s: float, parallel: int) -> ParallelRunner:
    """Parallel outside recording: each thread checks the corpus, runs, appends.

    The ordering matters. Recording *outside* parallel would serialise
    `run_many` again, since RecordingRunner does not override it.
    """
    inner = geos_runner(out / "rollouts", timeout_s=timeout_s)
    recording = RecordingRunner(inner, out / "rollouts.jsonl")

    def progress(rollout):
        flag = "" if rollout.score.status != "harness_error" else "  [HARNESS ERROR]"
        print(f"    {rollout.task:<55} {rollout.score.value:.4f} "
              f"{rollout.score.status}{flag}", flush=True)

    return ParallelRunner(recording, max_parallel=parallel, on_result=progress)


def task_pool(n: int | None, explicit: str | None) -> list[str]:
    if explicit:
        return [t.strip() for t in explicit.split(",") if t.strip()]
    tasks = sorted(p.name for p in (DATA / "experiments").iterdir() if p.is_dir())
    return tasks[:n] if n else tasks


def require_gates() -> None:
    """Refuse to spend a rollout while R1 is unverified.

    The gate is cheap and the failure it prevents is not: a search that varies a
    stop policy nothing reads completes normally and means nothing.
    """
    status = check_r1(REPO / DEFAULT_RECEIPT)
    if not status.verified:
        raise SystemExit(f"R1 is not verified, refusing to spend rollouts: {status.reason}")
    print(f"R1 verified: {status.reason}\n")


def cmd_baseline(args: argparse.Namespace) -> int:
    """Score the seed adapter, then cut the task pool into anchor/probe/held-out."""
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    runner = build_runner(out, args.timeout, args.parallel)
    seed = Candidate.from_dir(args.candidate)
    tasks = task_pool(args.tasks, args.task_list)
    seeds = tuple(int(s) for s in args.seeds.split(","))

    print(f"seed {seed.cid} on {len(tasks)} tasks x {len(seeds)} seeds "
          f"= {len(tasks) * len(seeds)} rollouts")
    started = time.time()
    rollouts = runner.run_many(seed, tasks, seeds)
    elapsed = time.time() - started

    infra = [r for r in rollouts if r.score.status == "harness_error"]
    scored = [r for r in rollouts if r.score.status != "harness_error"]
    print(f"\n{len(rollouts)} rollouts in {elapsed/60:.1f} min "
          f"({elapsed/max(1,len(rollouts)):.0f}s each)")
    if infra:
        print(f"  {len(infra)} harness errors -- NOT counted as model failures:")
        for r in infra[:3]:
            print(f"    {r.task}: {r.error}")
    for r in sorted(scored, key=lambda r: r.task):
        print(f"  {r.task:<55} {r.score.value:.4f}  {r.score.status}")
    if scored:
        values = [r.score.value for r in scored]
        zeros = sum(1 for v in values if v <= 1e-9)
        print(f"\nmean {statistics.mean(values):.4f}  "
              f"zero rate {zeros/len(values):.3f}  n={len(values)}")

    stats = stats_from_rollouts(scored)
    plan = build_slices(tasks, stats=stats,
                        anchor_size=args.anchor, probe_size=args.probe)
    print("\n" + plan.render())
    (out / "slices.json").write_text(json.dumps(
        {"anchor": list(plan.anchor), "probe": list(plan.probe),
         "held_out": list(plan.held_out),
         "elapsed_s": round(elapsed, 1),
         "seconds_per_rollout": round(elapsed / max(1, len(rollouts)), 1),
         "harness_errors": len(infra)}, indent=2))
    print(f"\nslices -> {out / 'slices.json'}")
    print(runner.inner.summary())
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    out = args.out
    runner = build_runner(out, args.timeout, args.parallel)
    seed = Candidate.from_dir(args.candidate)
    plan = json.loads((out / "slices.json").read_text())

    # Which tasks the hygiene gate scores contamination against is a real
    # decision, not a default, and the two answers disagree about the seed:
    # `all` (46 tasks) blocks it on a `kgdToughnessDominated` task-id leak;
    # `pool` (the tasks actually under evaluation) does not, because that task is
    # not one of them. `pool` is the tightest defensible definition -- leakage is
    # about the evaluation you are running -- and it is what repo3's own
    # audit_lineage.py does. `all` is the stricter, more future-proof one.
    # Whichever is chosen must be recorded with the result, so it is recorded.
    scope_tasks = (list(plan["anchor"]) + list(plan["probe"])
                   if args.hygiene_scope == "pool" else None)
    corpus = GroundTruthCorpus.from_ground_truth_dir(
        DATA / "experiments_gt", tasks=scope_tasks
    )
    # Profile, not just scope. The reframing (see docs/OVERFITTING.md): this is
    # the standard ML overfitting problem, and the standard defence is a held-out
    # split, not a stricter filter on the training artifact. `train` blocks only
    # what is truly cheating -- lookup tables, verbatim deck content, GT numerics
    # -- and demotes the statistical rules to warnings. The quarantined v4
    # adapter still blocks under it; there is a test.
    gate_config = train_profile() if args.hygiene_profile == "train" else GateConfig()
    seed_report = check_candidate(seed, corpus, config=gate_config)
    print(f"hygiene: profile={args.hygiene_profile} scope={args.hygiene_scope} "
          f"({len(scope_tasks) if scope_tasks else 'all'} tasks); "
          f"seed blocked = {seed_report.blocked} "
          f"({len(seed_report.warnings)} warning(s) recorded)")
    for finding in seed_report.errors:
        print(f"  SEED ERROR {finding}")
    if seed_report.blocked:
        # Refuse rather than run a loop whose acceptance rate is 0% by
        # construction. Every child inherits the seed's files, so a blocked seed
        # means a blocked everything -- and the resulting null looks exactly
        # like a real null.
        raise SystemExit(
            "the seed adapter does not pass its own hygiene gate, so no child "
            "can: acceptance would be 0% by construction and the null would be "
            "an artifact. Fix the seed, or choose --hygiene-scope deliberately. "
            "Do not lower the gate to make the search run."
        )
    ledger = BudgetLedger()
    ablate = {a.strip() for a in (args.ablate or "").split(",") if a.strip()}
    proposer = LLMProposer(
        backend=free_window_backend(),
        # ox-alpha is a reasoning model: at a small budget it spends the whole
        # allowance thinking and returns no content at all (§3.3).
        config=LLMProposerConfig(max_tokens=8000),
    )
    if "delta" in ablate:
        seed = lift_budgets(seed)

    search = Search(
        runner,
        proposer,
        hygiene=lambda c: check_candidate(c, corpus, config=gate_config),
        evidence_builder=lambda entry, rollouts: build_evidence(
            rollouts, candidate_id=entry.cid, parent_scores=entry.scores
        ),
        decision_log_path=out / "decisions.jsonl",
        ledger=ledger,
        config=SearchConfig(
            budget_candidates=args.budget,
            seeds=tuple(int(s) for s in args.seeds.split(",")),
            screen_tasks=args.screen_tasks,
            probe_tasks=1,
            probe_every=3,
        ),
    )
    notes = apply_ablations(search, proposer, ablate)
    for note in notes:
        print(f"  ABLATED {note}")

    started = time.time()
    result = search.run(seed, plan["anchor"], probe_tasks=plan["probe"])
    elapsed = time.time() - started

    try:
        spent = ledger.total("search").rollouts
    except KeyError:
        spent = 0
    print(f"\n=== search finished in {elapsed/60:.1f} min, {spent} rollouts ===")
    print(result.summary())
    if result.best is not None:
        print(f"best {result.best.cid}: mean {result.best.mean:.4f}")
        print(f"seed {seed.cid}: mean "
              f"{search.archive.entries[0].mean if search.archive.entries else float('nan'):.4f}")
    (out / f"search_result{args.tag}.json").write_text(json.dumps({
        "elapsed_s": round(elapsed, 1),
        "ablated": sorted(ablate),
        "hygiene_scope": args.hygiene_scope,
        "hygiene_profile": args.hygiene_profile,
        "ablation_notes": notes,
        "summary": result.summary(),
        "n_proposed": result.n_proposed,
        "n_screened_out": result.n_screened_out,
        "n_hygiene_blocked": result.n_hygiene_blocked,
        "n_proposer_failures": result.n_proposer_failures,
        "stagnated": result.stagnated,
        "best": result.best.cid if result.best else None,
        "best_mean": result.best.mean if result.best else None,
        "archive": [{"cid": e.cid, "mean": e.mean, "accepted": e.accepted,
                     "reason": e.reason, "scores": e.scores}
                    for e in search.archive.entries],
        # What the search actually spent, which is what fixes the baselines' k.
        # Every rollout counts -- including screened-out and rejected candidates.
        # A search that counts only its successes is the accounting error that
        # lets "evolution beat the baseline" mean "evolution had more compute".
        "search_rollouts": ledger.total("search").rollouts,
        "search_cost": {
            "tool_calls": ledger.total("search").cost.tool_calls,
            "wall_seconds": ledger.total("search").cost.wall_seconds,
            "usd": ledger.total("search").cost.usd,
        },
        "proposer_stats": getattr(proposer.backend, "stats", lambda: {})(),
    }, indent=2, default=str))
    if result.best is not None:
        result.best.candidate.materialize(
            out / "best", scaffolding_from=REPO3_PLUGIN, overwrite=True)
    print(f"\nartifacts -> {out}")
    print(runner.inner.summary())
    return 0


def cmd_baselines(args: argparse.Namespace) -> int:
    """Compute-matched controls. k comes from what the search actually spent."""
    out = args.out
    runner = build_runner(out, args.timeout, args.parallel)
    seed = Candidate.from_dir(args.candidate)
    plan = json.loads((out / "slices.json").read_text())
    spent = args.search_rollouts
    if spent is None:
        result = json.loads((out / "search_result.json").read_text())
        spent = result.get("search_rollouts") or 0
    if not spent:
        raise SystemExit("need --search-rollouts (or a search_result.json that records it)")

    results, ledger, budget_plan = run_matched_suite(
        runner, seed, plan["anchor"],
        search_rollouts=int(spent),
        seeds=tuple(int(s) for s in args.seeds.split(",")),
        include_sequential=args.sequential,
    )
    print(budget_plan.note)
    for name, res in results.items():
        print(f"  {name:<24} mean {res.mean:.4f}")
    (out / "baselines.json").write_text(json.dumps(
        {"plan": budget_plan.note,
         "results": {k: {"mean": v.mean, "label": v.arm_label} for k, v in results.items()}},
        indent=2, default=str))
    print(runner.inner.summary())
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", required=True,
                    choices=("baseline", "search", "baselines"))
    ap.add_argument("--out", type=Path, default=REPO / ".evolve" / "geos_search")
    ap.add_argument("--candidate", type=Path, default=REPO / ".evolve" / "seed")
    ap.add_argument("--tasks", type=int, default=None,
                    help="use the first N tasks of the pool")
    ap.add_argument("--task-list", default=None, help="comma-separated task ids")
    ap.add_argument("--seeds", default="1")
    ap.add_argument("--anchor", type=int, default=4)
    ap.add_argument("--probe", type=int, default=1)
    ap.add_argument("--budget", type=int, default=6)
    ap.add_argument("--screen-tasks", type=int, default=2)
    ap.add_argument("--timeout", type=float, default=1800.0)
    ap.add_argument("--parallel", type=int, default=6,
                    help="concurrent rollouts; the free pool sustains 8-16 "
                         "requests and one rollout uses about one slot")
    ap.add_argument("--search-rollouts", type=int, default=None)
    ap.add_argument("--sequential", action="store_true")
    ap.add_argument("--ablate", default="",
                    help=f"comma-separated ingredients to disable: {ABLATABLE}")
    ap.add_argument("--hygiene-profile", choices=("train", "strict"), default="train",
                    help="`train` blocks only true cheating and relies on the "
                         "held-out split to reveal overfitting; `strict` also "
                         "blocks the statistical/vocabulary rules")
    ap.add_argument("--hygiene-scope", choices=("pool", "all"), default="all",
                    help="score contamination against the tasks under "
                         "evaluation (pool) or the whole ground-truth set (all)")
    ap.add_argument("--tag", default="",
                    help="suffix for the result filename, so ablation arms do "
                         "not overwrite each other")
    args = ap.parse_args()

    require_gates()
    return {"baseline": cmd_baseline, "search": cmd_search,
            "baselines": cmd_baselines}[args.stage](args)


if __name__ == "__main__":
    raise SystemExit(main())
