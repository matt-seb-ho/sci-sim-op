"""LAMMPS: input scripts parse and gate, but deliberately do not score.

LAMMPS is the interface where the architecture's fifth fact bites. On GEOS and
OpenFOAM the binding constraint is structural completeness, which is cheap to
measure. On LAMMPS the agent already emits structurally complete, runnable
scripts; what it gets wrong is *values* -- a timestep, a cutoff, a thermostat
damping constant. There is no cheap defensible metric for that:

* Directive coverage would score ~1.0 for both a correct and an incorrect
  script, so optimizing against it optimizes nothing.
* Text similarity to the reference script rewards transcription, not physics,
  and would make the benchmark measure retrieval of the answer.
* The only honest metrics are behavioural -- compare thermo output or a short
  trajectory against a reference run -- which means actually running ``lmp``.

So :meth:`LammpsSimulator.score` raises rather than returning a number that
would look like signal. Everything that *can* be done without a physics
judgement is done: parsing, required-command completeness, validation via
``lmp -skiprun``, and the leak surface.

This module is the evidence that the ``SimulatorSpec`` protocol is not
GEOS-shaped: a simulator can implement the structural half of the contract and
refuse the scoring half, and the loop is told so explicitly by
:meth:`preflight` rather than discovering it as a wrong number.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from harness_evolve.simulators.base import (
    Artifact,
    Diagnosis,
    SimulatorRegistry,
    SimulatorSpec,
)
from harness_evolve.types import Finding, Score, TaskId

#: Commands without which a LAMMPS script cannot run at all. Chosen to be
#: unambiguous single commands; the "atom definition" stage is deliberately
#: absent because it can be satisfied by `read_data`, `read_restart`, or
#: `create_atoms`, and `required_sections` has no notion of alternatives.
REQUIRED_COMMANDS: tuple[str, ...] = ("units", "atom_style", "pair_style", "run")

#: Commands that define the simulated atoms, any one of which suffices.
ATOM_DEFINITION_COMMANDS: frozenset[str] = frozenset(
    {"read_data", "read_restart", "create_atoms", "create_box"}
)

#: Filename conventions for LAMMPS artifacts. `in.melt` and `data.polymer` carry
#: their type as a *prefix*, which `leaky_extensions` cannot express.
_SCRIPT_NAME_RE = re.compile(r"\b((?:in|data|restart)\.[A-Za-z0-9_][A-Za-z0-9_.\-]*)\b")

#: Glob patterns for files treated as input scripts.
SCRIPT_GLOBS: tuple[str, ...] = ("in.*", "*.in", "*.lmp", "*.lammps")

#: Seconds allowed for one `lmp -skiprun` call.
DEFAULT_VALIDATE_TIMEOUT = float(os.environ.get("LAMMPS_VALIDATE_TIMEOUT", "120"))


@dataclass(frozen=True)
class Directive:
    """One LAMMPS command line: ``fix 1 all nvt temp 300 300 0.1``."""

    command: str
    args: tuple[str, ...]
    line: int
    source: str

    def render(self) -> str:
        return " ".join((self.command,) + self.args)


@dataclass
class ScriptModel:
    """Parsed view of every input script in a workspace."""

    directives: list[Directive] = field(default_factory=list)

    @property
    def commands(self) -> set[str]:
        return {d.command for d in self.directives}

    def with_command(self, command: str) -> list[Directive]:
        return [d for d in self.directives if d.command == command]


def parse_script(text: str, source: str) -> list[Directive]:
    """Split a LAMMPS input script into directives.

    Handles the two syntactic features that matter for structure: ``#``
    comments and ``&`` line continuation. Variable expansion (``${x}``) is left
    alone -- resolving it needs the interpreter, and structural checks do not
    need it resolved.
    """
    directives: list[Directive] = []
    buffer = ""
    start_line = 0
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if not buffer:
            start_line = lineno
        if line.endswith("&"):
            buffer += line[:-1].strip() + " "
            continue
        buffer += line
        tokens = buffer.split()
        buffer = ""
        if tokens:
            directives.append(
                Directive(
                    command=tokens[0],
                    args=tuple(tokens[1:]),
                    line=start_line,
                    source=source,
                )
            )
    if buffer.strip():
        tokens = buffer.split()
        directives.append(
            Directive(tokens[0], tuple(tokens[1:]), start_line, source)
        )
    return directives


@SimulatorRegistry.register
class LammpsSimulator(SimulatorSpec):
    """LAMMPS script authoring: structure only, scoring deliberately unimplemented."""

    name = "lammps"

    #: `.lmp`/`.lammps`/`.in` cover the extension-bearing conventions; the
    #: `in.*` / `data.*` prefix convention is handled in :meth:`leak_pattern`.
    leaky_extensions = ("lmp", "lammps", "in")

    required_sections = REQUIRED_COMMANDS

    def __init__(
        self,
        lammps_executable: str | None = None,
        validate_timeout: float = DEFAULT_VALIDATE_TIMEOUT,
    ) -> None:
        self.lammps_executable = lammps_executable or os.environ.get(
            "LAMMPS_EXECUTABLE", ""
        )
        self.validate_timeout = validate_timeout

    def parse(self, workspace: Path) -> Artifact:
        artifact = Artifact()
        workspace = Path(workspace)
        if not workspace.is_dir():
            artifact.parse_errors["<workspace>"] = f"not a directory: {workspace}"
            return artifact

        model = ScriptModel()
        seen: set[Path] = set()
        for pattern in SCRIPT_GLOBS:
            for path in sorted(workspace.rglob(pattern)):
                if not path.is_file() or path in seen:
                    continue
                seen.add(path)
                rel = path.relative_to(workspace).as_posix()
                try:
                    text = path.read_text(errors="replace")
                except OSError as exc:
                    artifact.parse_errors[rel] = str(exc)
                    continue
                artifact.files[rel] = text
                model.directives.extend(parse_script(text, rel))
        artifact.tree = model
        return artifact

    def present_sections(self, artifact: Artifact) -> set[str]:
        model = artifact.tree
        if not isinstance(model, ScriptModel):
            return set()
        return model.commands & set(self.required_sections)

    def check_completeness(self, artifact: Artifact) -> list[Finding]:
        """Required commands, plus the "atoms must come from somewhere" rule.

        The alternatives rule cannot be expressed in ``required_sections``, so it
        is added here rather than being dropped.
        """
        findings = super().check_completeness(artifact)
        model = artifact.tree
        if isinstance(model, ScriptModel) and not (
            model.commands & ATOM_DEFINITION_COMMANDS
        ):
            findings.append(
                Finding(
                    "completeness",
                    "error",
                    "script defines no atoms: expected one of "
                    + ", ".join(sorted(ATOM_DEFINITION_COMMANDS)),
                )
            )
        return findings

    def validate(self, artifact: Artifact, workspace: Path) -> list[Finding]:
        """Run ``lmp -in <script> -skiprun``, returning its output verbatim.

        ``-skiprun`` makes LAMMPS parse and set up the simulation but skip every
        ``run``/``minimize``, which is the closest analogue to
        ``geosx --validate-input``. As with GEOS, the message carries the
        validator's own text unmodified: LAMMPS names the offending command and
        line, and that is the feedback the harness exists to route back.

        Not verified against a real LAMMPS binary in this environment -- the
        flag and its semantics are from the LAMMPS command-line documentation,
        not from an observed run. Confirm before trusting a green result.
        """
        workspace = Path(workspace)
        findings: list[Finding] = []
        reasons = self.preflight()
        if reasons:
            return [Finding("lammps_validate", "info", "; ".join(reasons))]

        scripts = [rel for rel in sorted(artifact.files) if _is_script(rel)]
        if not scripts:
            return [
                Finding(
                    "lammps_validate", "error", "no LAMMPS input script found",
                    location=str(workspace),
                )
            ]
        for rel in scripts:
            findings.append(self._validate_one(workspace / rel, workspace))
        return findings

    def _validate_one(self, script: Path, workspace: Path) -> Finding:
        cmd = [
            self.lammps_executable, "-in", str(script), "-log", "none", "-skiprun",
        ]
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(workspace),
                capture_output=True,
                text=True,
                timeout=self.validate_timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return Finding(
                "lammps_validate", "error",
                f"validation timed out after {self.validate_timeout:g}s",
                location=script.name,
            )
        except OSError as exc:
            return Finding(
                "lammps_validate", "error", f"could not run lmp: {exc}",
                location=script.name,
            )
        output = "\n".join(
            p.strip() for p in (proc.stderr, proc.stdout) if p and p.strip()
        )
        severity = "info" if proc.returncode == 0 else "error"
        return Finding(
            "lammps_validate",
            severity,
            output or f"lmp exited {proc.returncode} with no output",
            location=script.name,
        )

    def score(self, generated: Path, ground_truth: Path, task: TaskId) -> Score:
        """Not implemented, on purpose. See the module docstring.

        The binding constraint on LAMMPS is parameter-value correctness, and
        every cheap proxy for it (directive coverage, text similarity) measures
        something else while looking like a score. Implementing this needs a
        behavioural comparison against a reference run, or a curated per-task
        rubric of which parameters matter.
        """
        raise NotImplementedError(
            "LAMMPS scoring is not implemented: the failure mode on this "
            "interface is parameter values, not structure, and no cheap proxy "
            "for it is defensible. Implement either (a) a behavioural comparison "
            "of thermo output against a reference `lmp` run, or (b) a per-task "
            "rubric naming the parameters that matter, before scoring LAMMPS. "
            "parse(), check_completeness() and validate() work today."
        )

    def diagnose(
        self, generated: Path, ground_truth: Path, task: TaskId
    ) -> Diagnosis:
        """Not implemented: there is no score here to explain."""
        raise NotImplementedError(
            "LAMMPS diagnosis follows LAMMPS scoring; see LammpsSimulator.score. "
            "For structural feedback use parse() + check_completeness()."
        )

    def directive_coverage(self, generated: Path, ground_truth: Path) -> float:
        """Fraction of the reference script's commands the generated one uses.

        Exposed as a *named diagnostic*, never as :meth:`score`: on LAMMPS this
        number sits near 1.0 for correct and incorrect scripts alike, which is
        exactly why it must not be optimized against.
        """
        gt = self.parse(Path(ground_truth)).tree
        gen = self.parse(Path(generated)).tree
        if not isinstance(gt, ScriptModel) or not gt.commands:
            return 0.0
        if not isinstance(gen, ScriptModel):
            return 0.0
        return len(gt.commands & gen.commands) / len(gt.commands)

    def leak_pattern(self) -> re.Pattern[str]:
        """Extend the base pattern with the ``in.*`` / ``data.*`` conventions."""
        base = super().leak_pattern().pattern
        return re.compile(f"(?:{base})|(?:{_SCRIPT_NAME_RE.pattern})")

    def preflight(self) -> list[str]:
        reasons: list[str] = []
        if not self.lammps_executable:
            reasons.append("LAMMPS_EXECUTABLE is not set; lmp -skiprun unavailable")
        elif shutil.which(self.lammps_executable) is None and not Path(
            self.lammps_executable
        ).exists():
            reasons.append(f"lmp binary {self.lammps_executable!r} not found")
        reasons.append("LammpsSimulator.score is not implemented")
        return reasons


def _is_script(rel_path: str) -> bool:
    name = Path(rel_path).name
    return (
        name.startswith("in.")
        or name.endswith(".in")
        or name.endswith(".lmp")
        or name.endswith(".lammps")
    )
