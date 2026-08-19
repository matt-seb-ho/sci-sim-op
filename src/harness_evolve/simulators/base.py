"""The portability contract: what it takes to ground an agent in *a* simulator.

The single most transferable empirical finding from the SIGA work is that
**which grounding component binds is interface-dependent**. On GEOS and
OpenFOAM the failure mode is structural incompleteness, so the termination-time
completeness gate dominates; on LAMMPS the agent already emits complete,
structurally valid scripts and the bottleneck is parameter *values*, so
procedural memory and retrieval dominate instead.

A loop hard-coded to GEOS cannot express that, let alone discover it. So the
simulator is a plugin, and every part of the system that could have been
GEOS-specific -- scoring, validation, structural expectations, contamination
policy, leak surface -- is a method on this protocol instead.

Implementing a new simulator means writing one subclass. That is the concrete
form of the "adaptation over reconstruction" stance: the thing that ports is
this interface, not a bespoke agent.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from harness_evolve.types import Finding, Score, TaskId


@dataclass
class Artifact:
    """A parsed view of whatever the agent wrote into its workspace.

    ``tree`` is the simulator's own structural representation (an XML element
    for GEOS, a case-directory map for OpenFOAM, a directive list for LAMMPS).
    The core loop never inspects it; only the owning
    :class:`SimulatorSpec` does.
    """

    files: dict[str, str] = field(default_factory=dict)
    tree: Any = None
    parse_errors: dict[str, str] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not self.files

    @property
    def parses(self) -> bool:
        return bool(self.files) and not self.parse_errors


@dataclass
class Diagnosis:
    """Structured account of *why* a generated artifact lost score.

    This is the substrate of the evidence layer. v1's proposer received a
    truncated list of tool names and no reward at all; everything here exists
    so a proposer can be told what actually went wrong, at a granularity it can
    act on.
    """

    section_scores: dict[str, float] = field(default_factory=dict)
    worst_subtrees: list[dict[str, Any]] = field(default_factory=list)
    missing_elements: list[str] = field(default_factory=list)
    extra_elements: list[str] = field(default_factory=list)
    n_extra: int = 0
    category: str | None = None
    notes: list[str] = field(default_factory=list)

    def weakest_sections(self, k: int = 5) -> list[tuple[str, float]]:
        return sorted(self.section_scores.items(), key=lambda kv: kv[1])[:k]


@dataclass
class ContaminationPolicy:
    """Which files must be hidden from the agent for a given task.

    Kept alongside the simulator because the notion of a "variant sibling"
    (``Foo_base.xml`` implying ``Foo_benchmark.xml``, ``Foo_smoke.xml``) is
    simulator-specific, and getting it wrong is how a benchmark silently stops
    measuring capability.
    """

    blocked_basenames: set[str] = field(default_factory=set)
    blocked_paths: set[str] = field(default_factory=set)
    reason: str = ""


class SimulatorSpec(ABC):
    """One simulator's executable contract."""

    #: Short identifier used in run names, reports, and manifest defaults.
    name: str = "unnamed"

    #: File extensions whose *basenames* must never appear in an adapter
    #: artifact. The v1 gate hardcoded `.xml` only, which is how ground-truth
    #: `.geos` dependency filenames reached the shipped adapter.
    leaky_extensions: tuple[str, ...] = ("xml",)

    #: Top-level structures a complete artifact is expected to define. Drives
    #: the completeness check -- the cheapest reliable adapter component.
    required_sections: tuple[str, ...] = ()

    # -- parsing ---------------------------------------------------------
    @abstractmethod
    def parse(self, workspace: Path) -> Artifact:
        """Read and structurally parse the agent's output directory."""

    # -- validation (the X / S interfaces) -------------------------------
    @abstractmethod
    def validate(self, artifact: Artifact, workspace: Path) -> list[Finding]:
        """Run the simulator's own validator over the artifact.

        For GEOS this is ``geosx -i <entry> --validate-input``, which loads the
        deck through the real ProblemManager. Implementations should return
        validator output *verbatim* in the message where the validator produces
        something actionable (e.g. GEOS prints the full table of valid
        attributes on an unknown-attribute error) -- that text is the highest
        quality feedback signal the harness produces, and discarding it is what
        makes a gate "static".
        """

    def check_completeness(self, artifact: Artifact) -> list[Finding]:
        """Default completeness gate: are the required sections present?

        Deliberately schema-free so it transfers to any simulator with a notion
        of required top-level structure, not just ones shipping an XSD.
        """
        if not self.required_sections:
            return []
        present = self.present_sections(artifact)
        return [
            Finding("completeness", "error", f"artifact defines no {s!r} section")
            for s in self.required_sections
            if s not in present
        ]

    def present_sections(self, artifact: Artifact) -> set[str]:
        """Which required-section names the artifact defines. Override per simulator."""
        return set()

    # -- scoring ---------------------------------------------------------
    @abstractmethod
    def score(self, generated: Path, ground_truth: Path, task: TaskId) -> Score:
        """Score a generated artifact against ground truth, failures-as-zero."""

    def diagnose(self, generated: Path, ground_truth: Path, task: TaskId) -> Diagnosis:
        """Explain a score. Default: nothing beyond the score itself."""
        return Diagnosis()

    # -- contamination and hygiene ---------------------------------------
    def contamination_policy(
        self, task: TaskId, ground_truth_root: Path
    ) -> ContaminationPolicy:
        """Files to hide from the agent for ``task``.

        Default blocks exactly the task's own ground-truth files. Simulators
        with variant-sibling conventions must override and expand.
        """
        gt = Path(ground_truth_root) / task
        names = {p.name.lower() for p in gt.rglob("*") if p.is_file()} if gt.is_dir() else set()
        return ContaminationPolicy(
            blocked_basenames=names, reason="task ground truth"
        )

    def leak_pattern(self) -> re.Pattern[str]:
        """Regex matching artifact filenames that must not appear in an adapter."""
        exts = "|".join(re.escape(e) for e in self.leaky_extensions)
        return re.compile(rf"\b([A-Za-z0-9_][A-Za-z0-9_.\-]*\.(?:{exts}))\b")

    # -- environment -----------------------------------------------------
    def preflight(self) -> list[str]:
        """Reasons this simulator cannot be exercised in the current environment.

        Empty list means ready. Returning reasons rather than raising lets the
        caller decide whether to degrade to a cached or mock runner instead of
        dying halfway through a search.
        """
        return []

    def describe(self) -> str:
        return (
            f"{self.name}: {len(self.required_sections)} required sections, "
            f"leak extensions {list(self.leaky_extensions)}"
        )


class SimulatorRegistry:
    """Name -> SimulatorSpec, so configs and CLIs can refer to simulators by string."""

    _specs: dict[str, type[SimulatorSpec]] = {}

    @classmethod
    def register(cls, spec_cls: type[SimulatorSpec]) -> type[SimulatorSpec]:
        cls._specs[spec_cls.name] = spec_cls
        return spec_cls

    @classmethod
    def get(cls, name: str, **kw: Any) -> SimulatorSpec:
        if name not in cls._specs:
            raise KeyError(
                f"unknown simulator {name!r}; registered: {sorted(cls._specs)}"
            )
        return cls._specs[name](**kw)

    @classmethod
    def names(cls) -> list[str]:
        return sorted(cls._specs)
