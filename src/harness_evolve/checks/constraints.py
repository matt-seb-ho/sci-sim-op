"""Negative constraints: one declaration, two surfaces.

A cheatsheet that only enumerates positive facts ("for physics X use solver Y")
trades one failure mode for another. The measured lineage shows it directly:
``missing_block`` fell 6 -> 3 while ``extra_block`` rose 9 -> 11 and
``hallucinated_extras`` 4 -> 7. What was missing was the negative half --
"exactly k Constitutive children, no more".

Stating it is not enough either. arXiv:2605.30621 finds weak-tier models fail by
*activating* a harness artifact and then not following it, so a constraint that
is only prose is a constraint that is only sometimes honoured. Hence: one
declaration renders BOTH as cheatsheet prose (:meth:`ConstraintSet.to_prose`)
and as an enforced check at the stop interface
(:meth:`ConstraintSet.findings`). Two surfaces that cannot drift apart because
there is only one source.

The declaration format is a deliberately tiny YAML subset parsed here rather
than by a dependency: the package is stdlib-only, and the subset a proposer
needs is a list of flat mappings. Anything richer would be a search space we
cannot check.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, Sequence

from harness_evolve.checks.xmlview import ElementView
from harness_evolve.types import Finding

#: Constraint kinds. Each one must be (a) mechanically checkable and (b)
#: renderable as a natural-language imperative -- a kind that cannot do both
#: breaks the one-source-two-surfaces property and is not admitted.
CONSTRAINT_KINDS: tuple[str, ...] = ("count", "forbid_attr", "require_attr", "forbid_tag")


class ConstraintError(ValueError):
    """Raised when a constraint declaration is malformed.

    Carries the line number: these are proposer-authored, and a diagnostic the
    proposer cannot locate is a diagnostic it cannot act on.
    """


@dataclass(frozen=True)
class Constraint:
    """One negative constraint.

    Fields are a union over :data:`CONSTRAINT_KINDS`; :meth:`validate` enforces
    which ones each kind requires. A single dataclass rather than a hierarchy
    because the whole point is that every kind renders through the same two
    methods, and a hierarchy invites a kind that implements only one of them.
    """

    kind: str
    tag: str = ""
    parent: str = ""
    child: str = "*"
    attr: str = ""
    min: int | None = None
    max: int | None = None
    note: str = ""

    def validate(self) -> None:
        if self.kind not in CONSTRAINT_KINDS:
            raise ConstraintError(
                f"unknown constraint kind {self.kind!r}; known: {list(CONSTRAINT_KINDS)}"
            )
        if self.kind == "count":
            if not self.parent:
                raise ConstraintError("kind=count requires 'parent'")
            if self.min is None and self.max is None:
                raise ConstraintError("kind=count requires 'min' and/or 'max'")
            if self.min is not None and self.max is not None and self.min > self.max:
                raise ConstraintError(
                    f"kind=count on {self.parent!r}: min {self.min} > max {self.max}"
                )
        elif self.kind in ("forbid_attr", "require_attr"):
            if not self.tag or not self.attr:
                raise ConstraintError(f"kind={self.kind} requires 'tag' and 'attr'")
        elif self.kind == "forbid_tag":
            if not self.tag:
                raise ConstraintError("kind=forbid_tag requires 'tag'")

    # -- surface 1: prose for the cheatsheet -----------------------------
    def to_prose(self) -> str:
        """The cheatsheet rendering. Imperative, because it is read as an instruction."""
        suffix = f" ({self.note})" if self.note else ""
        if self.kind == "count":
            what = "children" if self.child == "*" else f"`<{self.child}>` children"
            if self.min is not None and self.max is not None and self.min == self.max:
                body = f"`<{self.parent}>` has exactly {self.min} {what}, no more"
            elif self.max is not None and self.min is not None:
                body = f"`<{self.parent}>` has between {self.min} and {self.max} {what}"
            elif self.max is not None:
                body = f"`<{self.parent}>` has at most {self.max} {what}; do not add more"
            else:
                body = f"`<{self.parent}>` needs at least {self.min} {what}"
        elif self.kind == "forbid_attr":
            body = f"do NOT set `{self.attr}` on `<{self.tag}>`; it is not used here"
        elif self.kind == "require_attr":
            body = f"every `<{self.tag}>` must set `{self.attr}`"
        else:  # forbid_tag
            body = f"do NOT introduce `<{self.tag}>`; it is not part of this deck"
        return f"- {body}{suffix}."

    # -- surface 2: enforcement at the stop interface --------------------
    def findings(self, view: ElementView) -> list[Finding]:
        """The stop-hook rendering of the *same* declaration."""
        if self.kind == "count":
            return self._count_findings(view)
        if self.kind == "forbid_attr":
            return [
                Finding(
                    "constraints", "error",
                    f"<{self.tag}> must not set {self.attr!r}. {self.to_prose()[2:]}",
                    location=f"{src}:{self.tag}",
                )
                for src, el in view.iter_elements(self.tag)
                if el.get(self.attr) is not None
            ]
        if self.kind == "require_attr":
            return [
                Finding(
                    "constraints", "error",
                    f"<{self.tag}> is missing required attribute {self.attr!r}",
                    location=f"{src}:{self.tag}",
                )
                for src, el in view.iter_elements(self.tag)
                if el.get(self.attr) is None
            ]
        return [
            Finding(
                "constraints", "error",
                f"<{self.tag}> is forbidden here. {self.to_prose()[2:]}",
                location=f"{src}:{self.tag}",
            )
            for src, _el in view.iter_elements(self.tag)
        ]

    def _count_findings(self, view: ElementView) -> list[Finding]:
        n = view.count(self.parent, self.child)
        what = "children" if self.child == "*" else f"<{self.child}> children"
        out: list[Finding] = []
        if self.max is not None and n > self.max:
            out.append(
                Finding(
                    "constraints", "error",
                    f"<{self.parent}> has {n} {what}; at most {self.max} expected. "
                    f"Remove {n - self.max}.",
                    location=self.parent,
                )
            )
        if self.min is not None and n < self.min:
            out.append(
                Finding(
                    "constraints", "error",
                    f"<{self.parent}> has {n} {what}; at least {self.min} expected.",
                    location=self.parent,
                )
            )
        return out


@dataclass
class ConstraintSet:
    """A parsed constraint declaration file."""

    constraints: list[Constraint] = field(default_factory=list)
    source: str = ""

    def __len__(self) -> int:
        return len(self.constraints)

    def __iter__(self) -> Iterator[Constraint]:
        return iter(self.constraints)

    # -- construction ----------------------------------------------------
    @classmethod
    def parse(cls, text: str, *, source: str = "") -> "ConstraintSet":
        """Parse the declaration format.

        Accepted, and nothing else::

            # comment
            - kind: count
              parent: Constitutive
              child: "*"
              max: 3
            - {kind: forbid_attr, tag: SolidMechanicsLagrangianFEM, attr: gravityVector}
        """
        items = _parse_item_list(text)
        constraints: list[Constraint] = []
        for lineno, mapping in items:
            kind = str(mapping.pop("kind", "") or "")
            unknown = sorted(set(mapping) - _CONSTRAINT_FIELDS)
            if unknown:
                raise ConstraintError(
                    f"line {lineno}: unknown constraint field(s) {unknown}; "
                    f"known: {sorted(_CONSTRAINT_FIELDS)}"
                )
            try:
                c = Constraint(
                    kind=kind,
                    tag=str(mapping.get("tag", "") or ""),
                    parent=str(mapping.get("parent", "") or ""),
                    child=str(mapping.get("child", "*") or "*"),
                    attr=str(mapping.get("attr", "") or ""),
                    min=_as_int(mapping.get("min"), lineno, "min"),
                    max=_as_int(mapping.get("max"), lineno, "max"),
                    note=str(mapping.get("note", "") or ""),
                )
                c.validate()
            except ConstraintError as exc:
                raise ConstraintError(f"line {lineno}: {exc}") from None
            constraints.append(c)
        return cls(constraints=constraints, source=source)

    # -- the two surfaces ------------------------------------------------
    def to_prose(self, *, heading: str = "Constraints (do not violate these)") -> str:
        """Cheatsheet section. Empty string when there are no constraints."""
        if not self.constraints:
            return ""
        return "\n".join([f"## {heading}", "", *(c.to_prose() for c in self.constraints)])

    def findings(self, view: ElementView) -> list[Finding]:
        """Every violation, in declaration order."""
        out: list[Finding] = []
        for c in self.constraints:
            out.extend(c.findings(view))
        return out


_CONSTRAINT_FIELDS: frozenset[str] = frozenset(
    {"tag", "parent", "child", "attr", "min", "max", "note"}
)


def _as_int(value: Any, lineno: int, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ConstraintError(f"line {lineno}: {field_name} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ConstraintError(
            f"line {lineno}: {field_name} must be an integer, got {value!r}"
        ) from None


# ---------------------------------------------------------------------------
# the tiny parser
# ---------------------------------------------------------------------------


def _strip_comment(line: str) -> str:
    """Drop a trailing ``#`` comment, respecting quotes."""
    out: list[str] = []
    quote: str | None = None
    for ch in line:
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            out.append(ch)
        elif ch == "#":
            break
        else:
            out.append(ch)
    return "".join(out)


def _scalar(raw: str) -> Any:
    text = raw.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    low = text.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("null", "none", ""):
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def _split_inline(body: str, lineno: int) -> list[str]:
    """Split ``a: 1, b: "x, y"`` on commas outside quotes."""
    parts: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    for ch in body:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch == ",":
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if quote:
        raise ConstraintError(f"line {lineno}: unterminated quote")
    parts.append("".join(buf))
    return [p for p in parts if p.strip()]


def _key_value(chunk: str, lineno: int) -> tuple[str, Any]:
    if ":" not in chunk:
        raise ConstraintError(
            f"line {lineno}: expected 'key: value', got {chunk.strip()!r}"
        )
    key, _, value = chunk.partition(":")
    key = key.strip()
    if not key:
        raise ConstraintError(f"line {lineno}: empty key in {chunk.strip()!r}")
    return key, _scalar(value)


def _parse_item_list(text: str) -> list[tuple[int, dict[str, Any]]]:
    """Parse a list of flat mappings into ``(first_lineno, mapping)`` pairs."""
    items: list[tuple[int, dict[str, Any]]] = []
    current: dict[str, Any] | None = None
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        line = _strip_comment(raw_line).rstrip()
        if not line.strip():
            continue
        stripped = line.strip()
        if stripped.startswith("- "):
            body = stripped[2:].strip()
            current = {}
            items.append((lineno, current))
            if body.startswith("{"):
                if not body.endswith("}"):
                    raise ConstraintError(
                        f"line {lineno}: inline mapping must close on the same line"
                    )
                for chunk in _split_inline(body[1:-1], lineno):
                    k, v = _key_value(chunk, lineno)
                    current[k] = v
            elif body:
                k, v = _key_value(body, lineno)
                current[k] = v
        else:
            if current is None:
                raise ConstraintError(
                    f"line {lineno}: continuation line before any '- ' item: "
                    f"{stripped!r}"
                )
            if not line.startswith((" ", "\t")):
                raise ConstraintError(
                    f"line {lineno}: expected an indented 'key: value' or a new "
                    f"'- ' item, got {stripped!r}"
                )
            k, v = _key_value(stripped, lineno)
            current[k] = v
    return items


def render_constraints_prose(constraints: Sequence[Constraint]) -> str:
    """Convenience wrapper for callers holding a bare sequence."""
    return ConstraintSet(list(constraints)).to_prose()
