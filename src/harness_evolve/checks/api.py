"""The check interface, the registry, and the feedback surface.

One fixed signature, ``check(artifact, ctx) -> list[Finding]``, for built-ins
and candidate-authored plugins alike. arXiv:2603.05578 (Tool-Genesis) reports
that autonomous one-shot tool creation fails and that interface errors compound;
a single unchanging signature is the cheapest available defence, and the
sandbox in :mod:`harness_evolve.checks.sandbox` rejects anything that does not
meet it before a rollout is spent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Mapping, Sequence

from harness_evolve.checks.constraints import ConstraintSet
from harness_evolve.simulators.base import Artifact
from harness_evolve.types import Finding

if TYPE_CHECKING:  # pragma: no cover
    from harness_evolve.simulators.base import SimulatorSpec

#: Feedback shapes the stop policy may select. Mirrors ``FEEDBACK_SHAPES`` in
#: ``core/manifest.py``; duplicated rather than imported so ``checks/`` can be
#: vendored into the plugin directory that runs inside the container, where
#: ``core/`` is not present.
FEEDBACK_SHAPES: tuple[str, ...] = ("minimal", "structured_errors", "errors_plus_tables")


@dataclass
class CheckContext:
    """Everything a check may read besides the artifact itself.

    A dataclass rather than a dict because plugins are authored by a proposer:
    a typo in an attribute name is an ``AttributeError`` at vet time, a typo in
    a dict key is a silent ``None`` at run time.
    """

    workspace: Path
    required_sections: tuple[str, ...] = ()
    constraints: ConstraintSet = field(default_factory=ConstraintSet)
    simulator: "SimulatorSpec | None" = None
    feedback_shape: str = "structured_errors"
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_simulator(
        cls,
        simulator: "SimulatorSpec",
        workspace: Path,
        *,
        constraints: ConstraintSet | None = None,
        feedback_shape: str = "structured_errors",
    ) -> "CheckContext":
        """Build a context whose expectations come from the simulator plugin."""
        return cls(
            workspace=Path(workspace),
            required_sections=tuple(simulator.required_sections),
            constraints=constraints or ConstraintSet(),
            simulator=simulator,
            feedback_shape=feedback_shape,
        )


CheckFn = Callable[[Artifact, CheckContext], Sequence[Finding]]


def known_check_names(plugins: Mapping[str, CheckFn] | None = None) -> frozenset[str]:
    """Every check name a stop policy may legally enable, right now.

    ``core/manifest.py`` ships a static ``KNOWN_CHECKS`` set, which cannot know
    about ``cross_section_refs`` or about a candidate-authored plugin that has
    just cleared the fence. Pass this into ``Manifest.validate(known_checks=...)``
    so a policy is validated against the checks that actually exist, rather than
    against a list that has to be edited by hand every time one is added.
    """
    from harness_evolve.checks.builtins import BUILTIN_CHECKS

    return frozenset(BUILTIN_CHECKS) | frozenset(plugins or {})


def run_checks(
    artifact: Artifact,
    ctx: CheckContext,
    enabled: Sequence[str],
    *,
    plugins: Mapping[str, CheckFn] | None = None,
) -> list[Finding]:
    """Run the enabled checks in order.

    A check that raises degrades to a ``warn`` finding instead of propagating.
    Only ``error`` blocks, so a broken check can never trap the agent in a
    retry loop it has no way to escape -- which is strictly worse than not
    having run the check at all.

    An enabled-but-unregistered name is also a ``warn``, not a hard failure:
    stop policies are searched, and a policy naming a check whose plugin was
    rejected must degrade rather than abort the rollout.
    """
    from harness_evolve.checks.builtins import BUILTIN_CHECKS

    registry: dict[str, CheckFn] = {**BUILTIN_CHECKS, **(plugins or {})}
    findings: list[Finding] = []
    for name in enabled:
        fn = registry.get(name)
        if fn is None:
            findings.append(
                Finding("registry", "warn", f"enabled check {name!r} is not registered")
            )
            continue
        try:
            findings.extend(fn(artifact, ctx))
        except Exception as exc:  # noqa: BLE001 -- a plugin may raise anything
            findings.append(
                Finding(name, "warn", f"check raised {type(exc).__name__}: {exc}")
            )
    return findings


def render_feedback(findings: Sequence[Finding], shape: str = "structured_errors") -> str:
    """Render findings as the text the stop hook hands back to the agent.

    ``shape`` is a *searchable* field of the stop policy, which is the point:
    "static hooks raise the floor, feedback the agent can act on raises the
    ceiling" is a claim about exactly this surface, and it cannot be tested
    unless the surface is a variable.

    Empty string means "nothing blocking" -- warnings never block, so a run
    with only warnings must be allowed to stop.
    """
    if shape not in FEEDBACK_SHAPES:
        raise ValueError(f"unknown feedback shape {shape!r}; known: {list(FEEDBACK_SHAPES)}")
    errors = [f for f in findings if f.severity == "error"]
    if not errors:
        return ""
    if shape == "minimal":
        # The floor: the agent is told something is wrong and nothing else.
        # Kept as a real option because it is the honest control condition for
        # any claim that richer feedback raises the ceiling.
        return f"{len(errors)} validation error(s); fix them before finishing."

    lines = [f"{len(errors)} validation error(s) must be fixed before you finish:"]
    lines += [f"  {f.render()}" for f in errors]

    if shape == "errors_plus_tables":
        # geosx prints the full table of valid attributes/tags on an unknown-name
        # error. That table is the highest-quality signal the harness produces,
        # and discarding it is exactly what makes a gate "static".
        tables = [f for f in errors if _carries_table(f)]
        if tables:
            lines.append("")
            lines.append(
                "The validator printed the set of valid names for these. Copy a "
                "name from the list verbatim; do not guess a replacement:"
            )
            for f in tables:
                lines.append(f"  {f.source}: {f.message}")
        else:
            lines.append("")
            lines.append(
                "Where a validator prints a table of valid tags or attributes, "
                "use a name from it verbatim rather than guessing."
            )
    return "\n".join(lines)


def _carries_table(finding: Finding) -> bool:
    """Heuristic: does this message already embed an enumerated valid-name set?"""
    msg = finding.message
    return ("Valid attributes are" in msg or "available tags are" in msg
            or "Defined:" in msg or "children of" in msg)
