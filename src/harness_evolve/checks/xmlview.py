"""A uniform element view over whatever a simulator put in ``Artifact.tree``.

``Artifact.tree`` is deliberately ``Any`` in the simulator contract -- an XML
element for GEOS, a case-directory map for OpenFOAM, a directive list for
LAMMPS -- and the core loop is not allowed to look inside it. Check plugins are
not the core loop, but they are shared code, so they get an adapter instead of
reaching into a particular simulator's representation.

Consequence worth stating plainly: the tree-shaped built-ins (
``required_sections``, ``cross_section_refs``, ``constraints``) only have
anything to say about simulators whose artifacts are element trees. On a
simulator where :meth:`ElementView.of` finds nothing they return no findings
rather than false ones -- silence is the correct answer when the check does not
apply, and inventing findings from a representation you do not understand is
how a gate starts blocking on things the agent cannot act on.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Iterator

from harness_evolve.simulators.base import Artifact


@dataclass
class ElementView:
    """Named element roots plus the parse errors that stopped others existing."""

    roots: dict[str, ET.Element] = field(default_factory=dict)
    parse_errors: dict[str, str] = field(default_factory=dict)
    files: dict[str, str] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not self.roots

    @classmethod
    def of(cls, artifact: Artifact) -> "ElementView":
        """Adapt an :class:`Artifact`, tolerating the three shapes ``tree`` takes.

        Falls back to parsing ``artifact.files`` itself so a simulator that
        parses lazily (or not at all) still gets the tree-shaped checks. Parse
        failures discovered here are merged into ``parse_errors`` rather than
        raised: the ``parse`` check is the thing that reports them.
        """
        view = cls(files=dict(artifact.files), parse_errors=dict(artifact.parse_errors))
        tree: Any = artifact.tree
        if isinstance(tree, ET.Element):
            view.roots["<tree>"] = tree
            return view
        if isinstance(tree, dict) and any(
            isinstance(v, ET.Element) for v in tree.values()
        ):
            view.roots = {
                str(k): v for k, v in tree.items() if isinstance(v, ET.Element)
            }
            return view
        for name, text in sorted(artifact.files.items()):
            if name in view.parse_errors or not _looks_like_xml(name, text):
                continue
            try:
                view.roots[name] = ET.fromstring(text)
            except ET.ParseError as exc:
                view.parse_errors[name] = str(exc)
        return view

    # -- queries used by the built-ins -----------------------------------
    def iter_elements(self, tag: str) -> Iterator[tuple[str, ET.Element]]:
        """Every element with ``tag``, including roots themselves."""
        if not tag:
            return
        for name, root in self.roots.items():
            if root.tag == tag:
                yield name, root
            for el in root.iter(tag):
                yield name, el

    def top_level_tags(self) -> set[str]:
        """Root tags and their immediate children -- the "sections" of a deck."""
        out: set[str] = set()
        for root in self.roots.values():
            if isinstance(root.tag, str):
                out.add(root.tag)
            out |= {c.tag for c in root if isinstance(c.tag, str)}
        return out

    def count(self, parent_tag: str, child_tag: str = "*") -> int:
        """Count ``child_tag`` children of every ``parent_tag`` element.

        ``child_tag="*"`` counts all children; an empty ``child_tag`` counts the
        parents themselves.
        """
        total = 0
        for _, el in self.iter_elements(parent_tag):
            if not child_tag:
                total += 1
            elif child_tag == "*":
                total += len(list(el))
            else:
                total += sum(1 for c in el if c.tag == child_tag)
        return total

    def names_of(self, tag: str) -> set[str]:
        """The ``name`` attribute of every ``tag`` element."""
        return {
            n for _, el in self.iter_elements(tag) if (n := el.get("name")) is not None
        }

    def child_names_of(self, tag: str) -> set[str]:
        """The ``name`` attribute of every child of every ``tag`` element."""
        out: set[str] = set()
        for _, el in self.iter_elements(tag):
            out |= {n for c in el if (n := c.get("name")) is not None}
        return out

    def descendant_names_under(self, tag: str) -> set[str]:
        """``name`` of every descendant of ``tag``, at any depth.

        Needed because simulators nest definitions unevenly:
        ``NumericalMethods/FiniteVolume/TwoPointFluxApproximation`` is two levels
        down, ``Constitutive/ElasticIsotropic`` is one.
        """
        out: set[str] = set()
        for _, el in self.iter_elements(tag):
            for d in el.iter():
                if d is el:
                    continue
                n = d.get("name")
                if n is not None:
                    out.add(n)
        return out


def _looks_like_xml(name: str, text: str) -> bool:
    return name.lower().endswith(".xml") or text.lstrip().startswith("<")
