"""The built-in checks: the reference implementations a proposer sees.

Ordered by cost. ``parse`` is free and catches the largest single block
category observed in the run7/run9 lineage; ``required_sections`` targets
``missing_block``, the category adapters demonstrably do fix;
``cross_section_refs`` and ``constraints`` target the categories that got
*worse* when the cheatsheet grew (``extra_block`` 9 -> 11,
``hallucinated_extras`` 4 -> 7).

``geosx_validate`` is registered here too, but only as a bridge to
``SimulatorSpec.validate`` -- booting the real validator is two orders of
magnitude more expensive than everything else in this module, and which
validator that is belongs to the simulator plugin, not to the check registry.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from harness_evolve.checks.api import CheckContext, CheckFn
from harness_evolve.checks.xmlview import ElementView
from harness_evolve.simulators.base import Artifact
from harness_evolve.types import Finding

if TYPE_CHECKING:  # pragma: no cover
    pass

#: Separators GEOS accepts inside list-valued attributes such as ``materialList``.
_LIST_SPLIT_RE = re.compile(r"[\s,{}]+")


def check_parse(artifact: Artifact, ctx: CheckContext) -> list[Finding]:
    """Cheapest gate: something exists, and it parses.

    An empty workspace is an error rather than a silent pass. The failures-as-
    zero convention means an unscorable artifact is a 0, and a gate that lets
    an empty workspace through has converted a recoverable turn into a zero.
    """
    if artifact.is_empty:
        return [Finding("parse", "error", "the workspace contains no artifact files")]
    view = ElementView.of(artifact)
    return [
        Finding("parse", "error", f"file does not parse: {err}", location=name)
        for name, err in sorted(view.parse_errors.items())
    ]


def check_required_sections(artifact: Artifact, ctx: CheckContext) -> list[Finding]:
    """Completeness gate. Targets ``missing_block``.

    Deliberately schema-free. The OpenFOAM transfer is evidence that what
    generalises is "a completeness check at end of turn", not "XSD validation";
    a gate that needs an XSD is a gate that does not port.

    Section expectations come from the simulator plugin via
    :attr:`CheckContext.required_sections`, and the simulator's own
    ``present_sections`` wins when it defines one -- only it knows where its
    sections live in its own tree.
    """
    required = tuple(ctx.required_sections)
    if not required:
        return []
    present = set()
    if ctx.simulator is not None:
        present = set(ctx.simulator.present_sections(artifact))
    if not present:
        present = ElementView.of(artifact).top_level_tags()
    return [
        Finding("required_sections", "error", f"artifact defines no <{s}> section")
        for s in required
        if s not in present
    ]


def check_cross_section_refs(artifact: Artifact, ctx: CheckContext) -> list[Finding]:
    """``materialList`` entries must name real ``<Constitutive>`` children.

    Kept as a built-in even though ``geosx --validate-input`` catches the
    load-time cases, because it is two orders of magnitude cheaper than booting
    GEOS and because the message it produces enumerates the defined names --
    which is the form of feedback the agent can actually act on.
    """
    view = ElementView.of(artifact)
    defined = view.child_names_of("Constitutive")
    if not defined:
        # No definitions parsed at all means either a different simulator or a
        # deck so broken that `parse`/`required_sections` already said so.
        # Reporting every reference as dangling here would bury those.
        return []
    findings: list[Finding] = []
    for src, regions in view.iter_elements("ElementRegions"):
        for region in regions:
            raw = region.get("materialList")
            if not raw:
                continue
            for mat in _LIST_SPLIT_RE.split(raw):
                if mat and mat not in defined:
                    findings.append(
                        Finding(
                            "cross_section_refs", "error",
                            f"materialList names {mat!r}, which is not a "
                            f"<Constitutive> child. Defined: {sorted(defined)}",
                            location=f"{src}:{region.get('name') or region.tag}",
                        )
                    )
    return findings


def check_constraints(artifact: Artifact, ctx: CheckContext) -> list[Finding]:
    """Enforce the negative constraints the cheatsheet also states in prose.

    The declaration is parsed once into :class:`~harness_evolve.checks.
    constraints.ConstraintSet`; this is its enforcement surface and
    ``ConstraintSet.to_prose()`` is its cheatsheet surface. Neither can drift,
    because there is only one declaration.
    """
    if not len(ctx.constraints):
        return []
    return ctx.constraints.findings(ElementView.of(artifact))


def check_simulator_validate(artifact: Artifact, ctx: CheckContext) -> list[Finding]:
    """Bridge to the simulator's own validator (``geosx --validate-input``).

    Registered under the historical name so a searched stop policy naming
    ``geosx_validate`` resolves. Without a simulator in the context this is a
    warn, never an error: an unavailable validator must not block the agent.
    """
    if ctx.simulator is None:
        return [
            Finding(
                "geosx_validate", "warn",
                "no simulator in the check context; validator not run",
            )
        ]
    return list(ctx.simulator.validate(artifact, ctx.workspace))


BUILTIN_CHECKS: dict[str, CheckFn] = {
    "parse": check_parse,
    "required_sections": check_required_sections,
    "cross_section_refs": check_cross_section_refs,
    "constraints": check_constraints,
    "geosx_validate": check_simulator_validate,
}
