"""Bounded edit operations.

The predecessor's proposer emitted whole replacement files. Two things go wrong
with that, and both showed up in its lineage:

* **Nothing is attributable.** A rewritten cheatsheet differs from its parent in
  a dozen ways at once, so an accept/reject verdict cannot say which of them
  mattered. After three rounds nobody could name what any change had done.
* **It only ever grows.** A model asked to "produce the new cheatsheet" reliably
  produces the old one plus something. That artifact went 270 B to 3159 B in
  three rounds.

A bounded vocabulary -- add, delete, replace, one unit at a time -- fixes both
structurally rather than by asking nicely. It is the edit model SkillOpt
(arXiv:2605.23904) uses to optimise a single skill document for a frozen agent,
and it makes deletion a first-class move rather than a thing a model must
volunteer.

The unit is a line, because these artifacts are line-structured lists of
assertions and a line is what a negative constraint occupies.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Sequence


class Op(StrEnum):
    ADD = "add"
    DELETE = "delete"
    REPLACE = "replace"


class EditError(ValueError):
    """An edit could not be applied to the component it names."""


@dataclass(frozen=True)
class Edit:
    """One bounded change to one component.

    ``anchor`` identifies the existing line for ``delete`` and ``replace``. It is
    matched leniently -- exact first, then normalised, then closest fuzzy match
    above a threshold -- because a model asked to reproduce a line verbatim will
    occasionally re-wrap or re-punctuate it, and failing the whole proposal over
    a stray space wastes a call for no benefit. It will not match something
    merely similar, which would silently edit the wrong assertion.
    """

    component: str
    op: Op
    text: str = ""
    anchor: str = ""

    def describe(self) -> str:
        if self.op is Op.ADD:
            return f"add to {self.component}: {self.text.strip()[:80]}"
        if self.op is Op.DELETE:
            return f"delete from {self.component}: {self.anchor.strip()[:80]}"
        return (
            f"replace in {self.component}: {self.anchor.strip()[:50]} "
            f"-> {self.text.strip()[:50]}"
        )


#: A fuzzy anchor match below this ratio is treated as no match at all. Chosen
#: to tolerate re-wrapping and punctuation drift while refusing to edit a
#: different assertion that happens to share vocabulary.
ANCHOR_MATCH_FLOOR = 0.82


def _normalize(line: str) -> str:
    return re.sub(r"\s+", " ", line.strip().lstrip("-*• ").rstrip(".")).lower()


def find_anchor(lines: Sequence[str], anchor: str) -> int:
    """Index of the line ``anchor`` refers to, or -1."""
    if not anchor.strip():
        return -1
    for i, line in enumerate(lines):
        if line == anchor:
            return i
    target = _normalize(anchor)
    for i, line in enumerate(lines):
        if _normalize(line) == target:
            return i
    best_i, best_ratio = -1, 0.0
    for i, line in enumerate(lines):
        ratio = difflib.SequenceMatcher(None, _normalize(line), target).ratio()
        if ratio > best_ratio:
            best_i, best_ratio = i, ratio
    return best_i if best_ratio >= ANCHOR_MATCH_FLOOR else -1


def apply_edit(current: str, edit: Edit) -> str:
    """Apply one edit to a component's text.

    Raises rather than degrading to a no-op: an edit that silently does nothing
    would be evaluated, gated, and recorded as a real proposal, spending a full
    round to learn that the artifact did not change.
    """
    lines = current.splitlines()

    if edit.op is Op.ADD:
        if not edit.text.strip():
            raise EditError("add with empty text")
        if any(_normalize(l) == _normalize(edit.text) for l in lines):
            raise EditError(f"add duplicates an existing line: {edit.text.strip()[:60]}")
        return "\n".join([*lines, edit.text.rstrip()])

    idx = find_anchor(lines, edit.anchor)
    if idx < 0:
        raise EditError(
            f"anchor not found in {edit.component}: {edit.anchor.strip()[:80]!r}"
        )

    if edit.op is Op.DELETE:
        return "\n".join(lines[:idx] + lines[idx + 1:])

    if not edit.text.strip():
        raise EditError("replace with empty text; use delete")
    return "\n".join(lines[:idx] + [edit.text.rstrip()] + lines[idx + 1:])


EDIT_RE = re.compile(
    r'<edit\s+component="(?P<component>[^"]+)"\s+op="(?P<op>add|delete|replace)"'
    r'(?:\s+anchor="(?P<anchor>[^"]*)")?\s*>(?P<text>.*?)</edit>',
    re.DOTALL | re.IGNORECASE,
)


def parse_edits(response: str) -> list[Edit]:
    """Extract every ``<edit>`` block from a proposer response."""
    out = []
    for m in EDIT_RE.finditer(response):
        out.append(
            Edit(
                component=m.group("component").strip(),
                op=Op(m.group("op").lower()),
                text=(m.group("text") or "").strip(),
                anchor=(m.group("anchor") or "").strip(),
            )
        )
    return out
