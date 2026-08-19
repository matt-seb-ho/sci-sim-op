"""OpenFOAM: case-directory structure, scored on file coverage only.

This is a deliberate partial implementation. It exists to keep
:class:`~harness_evolve.simulators.base.SimulatorSpec` honest -- if the protocol
were secretly GEOS-shaped, an OpenFOAM case would not fit it, and the places
where it *doesn't* fit are recorded here rather than papered over:

* An OpenFOAM case is a **directory layout**, not one document. ``required_sections``
  therefore names paths (``system/controlDict``) rather than XML tags, which the
  protocol supports only because ``present_sections`` is overridable.
* The leak surface is **extension-free basenames** (``controlDict``,
  ``blockMeshDict``). ``leaky_extensions`` cannot express that, so
  :meth:`leak_pattern` is overridden. This is a genuine gap in the base
  contract, not an OpenFOAM quirk -- any simulator with extension-free
  conventional filenames hits it.
* Blocking contamination by *basename* is actively wrong here: every tutorial
  case in the OpenFOAM tree contains a ``controlDict``, so a basename block
  would hide the entire corpus. :meth:`contamination_policy` blocks paths.

What is implemented for real: parsing, required sections, present sections,
file-coverage scoring, diagnosis, contamination, preflight. What is not:
:meth:`validate`, which needs the OpenFOAM toolchain -- see its docstring.
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from harness_evolve.simulators.base import (
    Artifact,
    ContaminationPolicy,
    Diagnosis,
    SimulatorRegistry,
    SimulatorSpec,
)
from harness_evolve.types import Finding, Score, TaskId

#: The three system dictionaries every case needs, plus the two directories a
#: case cannot run without. `0/` holds initial/boundary fields; `constant/`
#: holds mesh and physical properties.
REQUIRED_ENTRIES: tuple[str, ...] = (
    "system/controlDict",
    "system/fvSchemes",
    "system/fvSolution",
    "constant",
    "0",
)

#: Directories that make a directory recognisable as a case root.
CASE_MARKERS: tuple[str, ...] = ("system", "constant")

#: Files that are outputs or scratch, never authored content.
IGNORED_DIR_NAMES: frozenset[str] = frozenset(
    {"processor0", "postProcessing", "dynamicCode", "__pycache__", ".git"}
)

#: Conventional OpenFOAM dictionary basenames carry no extension, so the leak
#: gate has to match the naming convention itself.
_DICT_NAME_RE = re.compile(r"\b([A-Za-z0-9_][A-Za-z0-9_.\-]*Dict)\b")


@dataclass
class CaseLayout:
    """Structural view of an OpenFOAM case: which files sit at which paths."""

    root: Path
    files: set[str] = field(default_factory=set)
    dirs: set[str] = field(default_factory=set)

    def has(self, entry: str) -> bool:
        return entry in self.files or entry in self.dirs


def case_root(workspace: Path) -> Path:
    """The case directory inside ``workspace``.

    Agents commonly create the case one level down (``workspace/cavity/system/``),
    so a single case-shaped subdirectory is descended into. Ambiguity is
    resolved in favour of the workspace itself rather than guessing.
    """
    workspace = Path(workspace)
    if any((workspace / m).is_dir() for m in CASE_MARKERS):
        return workspace
    candidates = [
        d
        for d in sorted(workspace.iterdir())
        if d.is_dir()
        and d.name not in IGNORED_DIR_NAMES
        and any((d / m).is_dir() for m in CASE_MARKERS)
    ] if workspace.is_dir() else []
    return candidates[0] if len(candidates) == 1 else workspace


def read_case(root: Path) -> CaseLayout:
    """Walk a case directory into a :class:`CaseLayout`."""
    root = Path(root)
    layout = CaseLayout(root=root)
    if not root.is_dir():
        return layout
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if any(part in IGNORED_DIR_NAMES for part in rel.parts):
            continue
        if path.is_dir():
            layout.dirs.add(rel.as_posix())
        elif path.is_file():
            layout.files.add(rel.as_posix())
    return layout


@SimulatorRegistry.register
class OpenFoamSimulator(SimulatorSpec):
    """OpenFOAM case authoring. Structure is scored; dictionary contents are not."""

    name = "openfoam"

    #: `.orig` shadows an initial-condition file, `.foam` is the ParaView stub,
    #: `.gz` is how OpenFOAM writes compressed fields. None of these are the
    #: main leak surface -- see :meth:`leak_pattern`.
    leaky_extensions = ("foam", "orig", "gz")

    required_sections = REQUIRED_ENTRIES

    def parse(self, workspace: Path) -> Artifact:
        """Read every authored file in the case; never raises.

        Files are read as text with replacement on decode errors: an OpenFOAM
        case can legitimately contain a binary mesh, and a hygiene check that
        cannot see a file cannot flag it.
        """
        artifact = Artifact()
        root = case_root(workspace)
        layout = read_case(root)
        for rel in sorted(layout.files):
            try:
                artifact.files[rel] = (root / rel).read_text(errors="replace")
            except OSError as exc:
                artifact.parse_errors[rel] = str(exc)
        artifact.tree = layout
        return artifact

    def present_sections(self, artifact: Artifact) -> set[str]:
        layout = artifact.tree
        if not isinstance(layout, CaseLayout):
            return set()
        return {entry for entry in self.required_sections if layout.has(entry)}

    def validate(self, artifact: Artifact, workspace: Path) -> list[Finding]:
        """Not implemented: needs the OpenFOAM toolchain.

        The equivalent of ``geosx --validate-input`` here is not one command.
        It is at least ``foamDictionary -entry <k> <file>`` per dictionary
        (syntax and key resolution), ``blockMesh -dry-run`` or ``checkMesh``
        (mesh definition), and a solver-specific check that the fields in ``0/``
        match the boundary patches the mesh defines. Implementing this requires
        a sourced OpenFOAM environment (``WM_PROJECT_DIR``, ``etc/bashrc``) and
        a decision about which solver a task targets; neither is available here,
        and guessing would produce a validator whose findings do not correspond
        to anything the real toolchain says.
        """
        raise NotImplementedError(
            "OpenFOAM validation needs a sourced OpenFOAM environment: "
            "foamDictionary for dictionary syntax, blockMesh -dry-run / checkMesh "
            "for the mesh, and a solver-specific field/patch consistency check. "
            "Set WM_PROJECT_DIR and implement OpenFoamSimulator.validate before "
            "using this simulator with a live runner."
        )

    def score(self, generated: Path, ground_truth: Path, task: TaskId) -> Score:
        """File coverage: what fraction of the ground-truth case exists.

        This scores *structure only*, which is defensible for OpenFOAM
        specifically -- the documented binding constraint on this interface is
        structural incompleteness, not value correctness -- but it is not the
        whole metric, and a case that reproduces every path with wrong contents
        scores 1.0. Dictionary-content scoring is deliberately absent rather
        than approximated; see the worklog.
        """
        gt = read_case(case_root(Path(ground_truth)))
        gen = read_case(case_root(Path(generated)))
        if not gt.files:
            return Score(task=task, value=0.0, status="missing_ground_truth")
        if not gen.files:
            return Score(task=task, value=0.0, status="empty_workspace")

        covered = gt.files & gen.files
        extra = gen.files - gt.files
        return Score(
            task=task,
            value=round(len(covered) / len(gt.files), 6),
            status="success",
            detail={
                "scoring": "file_coverage_only",
                "covered": sorted(covered),
                "missing": sorted(gt.files - gen.files),
                "extra": sorted(extra),
                "n_extra": len(extra),
            },
        )

    def diagnose(
        self, generated: Path, ground_truth: Path, task: TaskId
    ) -> Diagnosis:
        """Which case files are missing or invented. No per-dictionary scores."""
        result = self.score(generated, ground_truth, task)
        if result.is_failure or result.status != "success":
            return Diagnosis(
                category="partial_implementation", notes=[f"status={result.status}"]
            )
        missing = list(result.detail.get("missing", []))
        extra = list(result.detail.get("extra", []))
        return Diagnosis(
            missing_elements=missing,
            extra_elements=extra,
            n_extra=len(extra),
            category=(
                "missing_block" if missing else
                "hallucinated_extras" if extra else "no_failure"
            ),
            notes=["contents of present files are not scored"],
        )

    def leak_pattern(self) -> re.Pattern[str]:
        """Extend the base pattern with OpenFOAM's extension-free dict names.

        ``controlDict`` has no extension, so the base implementation -- which
        keys entirely off ``leaky_extensions`` -- would never match it.
        """
        base = super().leak_pattern().pattern
        return re.compile(f"(?:{base})|(?:{_DICT_NAME_RE.pattern})")

    def contamination_policy(
        self, task: TaskId, ground_truth_root: Path
    ) -> ContaminationPolicy:
        """Block the task's case *path*, not its basenames.

        Every OpenFOAM tutorial contains files named ``controlDict``,
        ``fvSchemes`` and ``U``. Blocking by basename, which is correct for
        GEOS, would hide the whole tutorial corpus and destroy the task.
        """
        gt_dir = Path(ground_truth_root) / task
        paths = (
            {p.relative_to(ground_truth_root).as_posix()
             for p in gt_dir.rglob("*") if p.is_file()}
            if gt_dir.is_dir()
            else set()
        )
        paths.add(Path(task).as_posix())
        return ContaminationPolicy(
            blocked_paths=paths,
            reason="task ground-truth case directory (paths, not basenames)",
        )

    def preflight(self) -> list[str]:
        reasons: list[str] = []
        if not os.environ.get("WM_PROJECT_DIR"):
            reasons.append("WM_PROJECT_DIR is not set; OpenFOAM env not sourced")
        if shutil.which("foamDictionary") is None:
            reasons.append("foamDictionary not on PATH")
        reasons.append(
            "OpenFoamSimulator.validate is not implemented; scoring is "
            "file-coverage only"
        )
        return reasons
