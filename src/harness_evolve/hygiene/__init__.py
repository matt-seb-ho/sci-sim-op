"""Contamination gate: what a candidate adapter may not reveal.

Blocking and free -- it runs before any rollout is spent, so a leaking
candidate costs nothing to reject. See ``gate.py`` for the rule set and the
two real incidents that motivate it.
"""

from harness_evolve.hygiene.corpus import (
    GroundTruthCorpus,
    canonical_numerics,
    canonicalize_number,
    stem_keys,
)
from harness_evolve.hygiene.gate import (
    ALL_RULES,
    GateConfig,
    HygieneError,
    HygieneReport,
    check_candidate,
    check_texts,
)

__all__ = [
    "ALL_RULES",
    "GateConfig",
    "GroundTruthCorpus",
    "HygieneError",
    "HygieneReport",
    "canonical_numerics",
    "canonicalize_number",
    "check_candidate",
    "check_texts",
    "stem_keys",
]
