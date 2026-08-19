"""Core search machinery: what a candidate is, how candidates are kept, and how one is chosen."""

from harness_evolve.core.candidate import Candidate, CandidateError, Prediction  # noqa: F401
from harness_evolve.core.manifest import (  # noqa: F401
    ComponentSpec, Manifest, ManifestError, StopPolicy,
)

__all__ = [
    "Candidate", "CandidateError", "Prediction",
    "ComponentSpec", "Manifest", "ManifestError", "StopPolicy",
]
