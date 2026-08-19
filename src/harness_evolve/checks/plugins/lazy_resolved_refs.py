"""Name references the simulator's own validator resolves too late to catch.

``geosx -i deck.xml --validate-input`` loads the deck through the real
ProblemManager, so it catches unknown attributes, hallucinated element tags, and
cross-references resolved during data-repository construction. It does *not*
catch references resolved lazily past the load phase. The confirmed case
(``docs/GEOSX_VALIDATE.md``, tested against the real binary): a solver carrying
``discretization="TPFA_DOES_NOT_EXIST"``, matching no ``NumericalMethods``
child, **validates clean and exits 0**.

The XSD cannot close the gap either. ``discretization`` is typed
``groupNameRef`` -- a plain string, not an enum -- and ``schema.xsd`` declares
zero ``xsd:key``/``xsd:keyref``, so it has no machinery to express "this string
must equal a sibling's name". Running xmllint alongside geosx adds nothing here.
The only complete answer is to run the deck past loading, which is far too slow
for a per-turn check.

So this is the residual class, and it is exactly the shape a cheap structural
check handles well: both halves of the reference are in the deck, and matching
them is a set membership test. It costs microseconds against geosx's seconds.

Reported as an error because the agent can always act on it: the message
enumerates the names that *are* defined.
"""

from __future__ import annotations

from harness_evolve.checks.api import CheckContext
from harness_evolve.checks.xmlview import ElementView
from harness_evolve.simulators.base import Artifact
from harness_evolve.types import Finding

#: Attribute -> the section whose descendants may satisfy it. Only entries whose
#: laziness is confirmed against the real binary belong here.
LAZY_REFS: dict[str, str] = {"discretization": "NumericalMethods"}

#: Attributes naming another solver. Whether GEOS resolves these at load time is
#: not confirmed, so they are only reported when the name matches *nothing*
#: anywhere in the deck -- a name that appears nowhere cannot resolve under any
#: scheme, which keeps this half of the check free of false positives.
SOLVER_REFS: tuple[str, ...] = ("flowSolverName", "solidSolverName", "poromechanicsSolverName")


def check(artifact: Artifact, ctx: CheckContext) -> list[Finding]:
    """Report references that name no definition in the deck."""
    view = ElementView.of(artifact)
    if view.is_empty:
        return []
    findings: list[Finding] = []
    findings += _check_section_scoped(view)
    findings += _check_globally_unknown(view)
    return findings


def _check_section_scoped(view: ElementView) -> list[Finding]:
    """References that must be satisfied inside one named section."""
    out: list[Finding] = []
    for attr, section in LAZY_REFS.items():
        defined = view.descendant_names_under(section)
        if not defined:
            # No section at all is `required_sections`' finding to report, not
            # this one; duplicating it would bury the reference error.
            continue
        for src, el in _elements_with(view, attr):
            value = (el.get(attr) or "").strip()
            if value and value not in defined:
                out.append(
                    Finding(
                        "lazy_resolved_refs", "error",
                        f"{attr}={value!r} names no <{section}> definition. "
                        f"Defined under <{section}>: {sorted(defined)}. "
                        f"geosx --validate-input does not catch this: it resolves "
                        f"{attr} only during the run loop.",
                        location=f"{src}:{el.tag}[{el.get('name') or '?'}]",
                    )
                )
    return out


def _check_globally_unknown(view: ElementView) -> list[Finding]:
    """References whose target does not exist anywhere in the deck."""
    all_names = _all_names(view)
    if not all_names:
        return []
    out: list[Finding] = []
    for attr in SOLVER_REFS:
        for src, el in _elements_with(view, attr):
            value = (el.get(attr) or "").strip()
            if value and value not in all_names:
                out.append(
                    Finding(
                        "lazy_resolved_refs", "error",
                        f"{attr}={value!r} names nothing defined anywhere in the "
                        f"deck. Defined names: {sorted(all_names)}.",
                        location=f"{src}:{el.tag}[{el.get('name') or '?'}]",
                    )
                )
    return out


def _elements_with(view: ElementView, attr: str):
    """Every element carrying ``attr``, from every root."""
    for src, root in view.roots.items():
        for el in root.iter():
            if isinstance(el.tag, str) and el.get(attr) is not None:
                yield src, el


def _all_names(view: ElementView) -> set[str]:
    out: set[str] = set()
    for root in view.roots.values():
        for el in root.iter():
            name = el.get("name")
            if name:
                out.add(name)
    return out


__all__ = ["check", "LAZY_REFS", "SOLVER_REFS"]
