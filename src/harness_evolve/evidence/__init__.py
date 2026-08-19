"""Layered evidence: what the proposer sees, and how good the harness's feedback was.

Three pieces, in the order a caller normally reaches for them:

* :mod:`~harness_evolve.evidence.corpus` -- the L0/L1/L2/L3 corpus built from
  ``list[Rollout]`` plus ``Diagnosis`` objects, with L3 fetched on demand for
  one named task.
* :mod:`~harness_evolve.evidence.diagnostics` -- trajectory mining: an
  ``events.jsonl`` stream becomes tool counts, error counts, hook blocks, file
  access patterns, and a positioned stream of feedback events.
* :mod:`~harness_evolve.evidence.efc` -- Effective Feedback Compute, a dense
  per-trajectory objective where the task score gives one sparse scalar per
  ~25-minute rollout.

See docs/ARCHITECTURE.md.
"""

from harness_evolve.evidence.corpus import (
    CorpusConfig,
    RoundEvidence,
    TaskEvidence,
    build_evidence,
)
from harness_evolve.evidence.diagnostics import (
    FeedbackEvent,
    MiningConfig,
    ToolCall,
    TrajectoryFeatures,
    diagnosis_from_tree,
    extract_entities,
    mine_trajectory,
    per_section,
    trajectory_excerpt,
    worst_subtrees,
)
from harness_evolve.evidence.efc import EFCConfig, EFCReport, efc, efc_report

__all__ = [
    "CorpusConfig",
    "EFCConfig",
    "EFCReport",
    "FeedbackEvent",
    "MiningConfig",
    "RoundEvidence",
    "TaskEvidence",
    "ToolCall",
    "TrajectoryFeatures",
    "build_evidence",
    "diagnosis_from_tree",
    "efc",
    "efc_report",
    "extract_entities",
    "mine_trajectory",
    "per_section",
    "trajectory_excerpt",
    "worst_subtrees",
]
