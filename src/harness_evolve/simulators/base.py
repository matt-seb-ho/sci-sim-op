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


@dataclass(frozen=True)
class SimulatorCapabilities:
    """Which parts of the contract are actually implemented.

    A simulator may legitimately ship without a scorer: for some interfaces
    every cheap proxy measures the wrong thing, and a placeholder number that
    looks like a score is worse than an honest refusal, because a search will
    happily optimise it.
    """

    can_parse: bool = True
    can_validate: bool = True
    can_score: bool = True
    can_diagnose: bool = True
    scoring_note: str = ""

    def gaps(self) -> list[str]:
        out = []
        for attr, label in (
            ("can_parse", "parsing"),
            ("can_validate", "validation"),
            ("can_score", "scoring"),
            ("can_diagnose", "diagnosis"),
        ):
            if not getattr(self, attr):
                out.append(f"{label} is not implemented for this simulator")
        if self.scoring_note:
            out.append(f"scoring caveat: {self.scoring_note}")
        return out

    @property
    def searchable(self) -> bool:
        """Can a search actually run against this simulator?"""
        return self.can_parse and self.can_score


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

    #: Artifact names that carry no extension at all (OpenFOAM's ``controlDict``,
    #: ``fvSchemes``) or carry their type as a prefix (LAMMPS' ``in.melt``).
    #: An extension list structurally cannot express these, and a leak surface
    #: that silently omits a simulator's most common filenames is worse than no
    #: gate, because it reads as coverage.
    leaky_names: tuple[str, ...] = ()

    #: Prefixes that make a following token an artifact name (``in.`` -> ``in.melt``).
    leaky_prefixes: tuple[str, ...] = ()

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
        """Regex matching artifact filenames that must not appear in an adapter.

        Composed from three sources because simulators name their artifacts
        three different ways: by extension, by a fixed bare name, and by a type
        prefix. Overriding this method should rarely be necessary; adding to
        :attr:`leaky_names` or :attr:`leaky_prefixes` usually suffices.
        """
        alts: list[str] = []
        if self.leaky_extensions:
            exts = "|".join(re.escape(e) for e in self.leaky_extensions)
            alts.append(rf"[A-Za-z0-9_][A-Za-z0-9_.\-]*\.(?:{exts})")
        if self.leaky_prefixes:
            pre = "|".join(re.escape(p) for p in self.leaky_prefixes)
            alts.append(rf"(?:{pre})[A-Za-z0-9_.\-]+")
        if self.leaky_names:
            alts.append("|".join(re.escape(n) for n in self.leaky_names))
        if not alts:
            return re.compile(r"(?!x)x")  # matches nothing
        return re.compile(r"\b(" + "|".join(alts) + r")\b")

    # -- capability and environment --------------------------------------
    def capabilities(self) -> "SimulatorCapabilities":
        """What this simulator can do *in principle*, regardless of environment.

        Separate from :meth:`preflight` because the two call for different
        responses. A missing binary is fixable by installing it; an unimplemented
        scorer means the search cannot run here at all, and conflating them
        produces callers that "degrade gracefully" past a capability that is
        never coming back.
        """
        return SimulatorCapabilities()

    def preflight(self) -> list[str]:
        """Reasons the *environment* blocks this simulator. Empty means ready.

        Returning reasons rather than raising lets the caller decide whether to
        degrade to a cached or mock runner instead of dying halfway through a
        search.
        """
        return []

    def blockers(self) -> list[str]:
        """Everything preventing a real search: capability gaps and environment."""
        return self.capabilities().gaps() + self.preflight()

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
