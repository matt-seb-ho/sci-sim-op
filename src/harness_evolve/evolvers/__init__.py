"""Evolution strategies as interchangeable arms of one matched comparison.

There is no single method here on purpose. The published critique of automatic
harness evolution (arXiv:2607.12227) is that it often fails to beat trivial
baselines and that nobody notices, because the arms are never run under one
protocol at one enforced budget. This package makes the strategy a plugged-in
choice — gated search, SkillOpt, AHE-style component cycling, random search —
and :mod:`~harness_evolve.evolvers.compare` refuses to report any comparison
whose arms did not spend the same.

See ``worklogs/W9_evolvers.md`` for what each method does differently and what
that predicts about when it wins.
"""

from harness_evolve.evolvers.ahe import AHEStyleEvolver, default_schedule
from harness_evolve.evolvers.base import (
    BudgetExhausted,
    BudgetedRunner,
    EditVocabulary,
    Evolver,
    EvolverResult,
    EvolverTrace,
    MoveOutcome,
    RolloutBudget,
    SliceScores,
    SpendEntry,
    TaskSlices,
    TraceStep,
    apply_move,
    budgeted,
    declare,
    evaluate_on,
    exhaust_budget,
)
from harness_evolve.evolvers.compare import (
    ArmOutcome,
    BudgetMismatch,
    Comparison,
    compare_evolvers,
)
from harness_evolve.evolvers.random_search import RandomSearchEvolver
from harness_evolve.evolvers.search import SearchEvolver
from harness_evolve.evolvers.skillopt import SkillOptEvolver

__all__ = [
    "AHEStyleEvolver",
    "ArmOutcome",
    "BudgetExhausted",
    "BudgetMismatch",
    "BudgetedRunner",
    "Comparison",
    "EditVocabulary",
    "Evolver",
    "EvolverResult",
    "EvolverTrace",
    "MoveOutcome",
    "RandomSearchEvolver",
    "RolloutBudget",
    "SearchEvolver",
    "SkillOptEvolver",
    "SliceScores",
    "SpendEntry",
    "TaskSlices",
    "TraceStep",
    "apply_move",
    "budgeted",
    "compare_evolvers",
    "declare",
    "default_schedule",
    "evaluate_on",
    "exhaust_budget",
]
