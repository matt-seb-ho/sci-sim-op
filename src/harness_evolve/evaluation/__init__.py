"""Evaluation protocol: compute-matched baselines, paired statistics, reports.

The deliverable of this package is not a number but a *comparison a reader can
check*: which model x harness configurations were run, on which slice, at what
budget, against which task-level search baselines, and under a criterion stated
before the numbers. See docs/ARCHITECTURE.md and worklogs/W5_evaluation.md.
"""

from harness_evolve.evaluation.baselines import (
    BaselineError,
    BaselineResult,
    BestOfK,
    BudgetEntry,
    BudgetLedger,
    BudgetMatch,
    BudgetPlan,
    SeedControl,
    SequentialRefinement,
    ValidatorBest,
    oracle_best,
    plan_matched_k,
    run_matched_suite,
    validator_best,
)
from harness_evolve.evaluation.protocol import (
    AccessRecord,
    EvaluationProtocol,
    HeldOutRelease,
    SliceViolation,
)
from harness_evolve.evaluation.report import (
    ArmConfig,
    EvaluationReport,
    Verdict,
    VerdictCriterion,
    decide,
)
from harness_evolve.evaluation.stats import (
    ArmScores,
    BootstrapResult,
    Comparison,
    EffectSizes,
    Interval,
    PairedDelta,
    PermutationResult,
    RescueLedger,
    TailStats,
    WinLossTie,
    compare,
    paired_bootstrap_ci,
    paired_deltas,
    paired_permutation_test,
    rescue_ledger,
    tail_stats,
    win_loss_tie,
)

__all__ = [
    "AccessRecord",
    "ArmConfig",
    "ArmScores",
    "BaselineError",
    "BaselineResult",
    "BestOfK",
    "BootstrapResult",
    "BudgetEntry",
    "BudgetLedger",
    "BudgetMatch",
    "BudgetPlan",
    "Comparison",
    "EffectSizes",
    "EvaluationProtocol",
    "EvaluationReport",
    "HeldOutRelease",
    "Interval",
    "PairedDelta",
    "PermutationResult",
    "RescueLedger",
    "SeedControl",
    "SequentialRefinement",
    "SliceViolation",
    "TailStats",
    "ValidatorBest",
    "Verdict",
    "VerdictCriterion",
    "WinLossTie",
    "compare",
    "decide",
    "oracle_best",
    "paired_bootstrap_ci",
    "paired_deltas",
    "paired_permutation_test",
    "plan_matched_k",
    "rescue_ledger",
    "run_matched_suite",
    "tail_stats",
    "validator_best",
    "win_loss_tie",
]
