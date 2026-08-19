"""GEOS: XML decks, TreeSim scoring, and `geosx --validate-input`.

The scoring algorithm (XMLTreeSim) is vendored from `repo3/src/eval/judge_geos.py`
rather than imported, because repo3 is not a dependency of this project and a
metric that silently changes underneath an archive of scored candidates makes
every round-over-round comparison meaningless. The recursion, the greedy
bipartite matching, the tie-breaking, and the constants (alpha=0.3, beta=0.1,
rtol=1e-6) are byte-for-byte equivalent to the original; `tests/
test_simulators_geos.py` pins the numbers.

What is *not* vendored: the legacy dimension scores
(`structural_completeness` / `element_type_match` / `attribute_accuracy` /
`tag_coverage` and their `WEIGHTS`). They were already marked "diagnostic
backward compat" in repo3, nothing downstream consumed them, and their weight
vector no longer corresponds to any headline metric.

Validation shells out to `geosx -i <entry> --validate-input`. Per
`repo3/docs/GEOSX_VALIDATE.md` this loads the deck through GEOS's own
ProblemManager and catches unknown attributes, hallucinated element tags, and
load-time dangling name references -- printing, on an unknown-attribute error,
the *complete table of valid attributes for that element*. That table is the
single highest-value piece of feedback this harness can produce, so
:meth:`GeosSimulator.validate` returns the validator's output verbatim instead
of summarizing it. It does not catch name references GEOS resolves lazily past
the load phase (e.g. `discretization=`); no available command does, and the XSD
has no keyref machinery to express them either.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from harness_evolve.simulators.base import (
    Artifact,
    ContaminationPolicy,
    Diagnosis,
    SimulatorRegistry,
    SimulatorSpec,
)
from harness_evolve.types import Finding, Score, TaskId

# ============================================================
# Constants -- values are load-bearing; see module docstring
# ============================================================

#: Top-level sections a complete GEOS deck defines.
REQUIRED_SECTIONS: tuple[str, ...] = ("Constitutive", "ElementRegions", "Events", "Mesh")

OPTIONAL_SECTIONS: tuple[str, ...] = (
    "Functions", "Tasks", "Solvers", "NumericalMethods",
    "Geometry", "FieldSpecifications", "Outputs",
)

#: Structural plumbing, not content: `Included`/`File` vanish once resolved and
#: `Problem` is the synthetic root of a merged multi-file deck.
IGNORE_TAGS: frozenset[str] = frozenset({"Problem", "Included", "File"})

#: Relative tolerance for numeric attribute comparison.
NUMERIC_RTOL = 1e-6

#: Interior-node blend: weight of a node's own attributes against its subtree.
TREESIM_ALPHA = 0.3

#: Penalty factor for hallucinated (extra) elements.
TREESIM_BETA = 0.1

_SCALAR_RE = re.compile(r"^[+-]?\d+(\.\d*)?([eE][+-]?\d+)?$")

#: Seconds allowed for one `--validate-input` call. repo3 measured ~2-3s on a
#: small single-region deck; the ceiling is a guess for large-mesh decks, so it
#: is generous and overridable.
DEFAULT_VALIDATE_TIMEOUT = float(os.environ.get("GEOSX_VALIDATE_TIMEOUT", "120"))

#: Validator output is returned verbatim, but not without bound: a runaway
#: message would otherwise be pasted straight into an agent's context.
MAX_VALIDATOR_CHARS = 20000


# ============================================================
# Loading, with <Included> resolution
# ============================================================

def _find_parent(root: ET.Element, target: ET.Element) -> ET.Element | None:
    for parent in root.iter():
        for child in list(parent):
            if child is target:
                return parent
    return None


def resolve_included(
    root: ET.Element,
    base_dir: Path,
    _ancestors: frozenset[Path] | None = None,
) -> ET.Element:
    """Splice every ``<Included><File name=.../></Included>`` into ``root``.

    ``_ancestors`` is the chain of files currently being expanded; skipping any
    candidate already in it breaks self- and mutual-include cycles in malformed
    agent output rather than recursing until the interpreter dies.
    """
    if _ancestors is None:
        _ancestors = frozenset()
    for included in list(root.findall(".//Included")):
        parent = _find_parent(root, included)
        if parent is None:
            continue
        children = list(parent)
        try:
            insert_at = children.index(included)
        except ValueError:
            continue
        parent.remove(included)
        for file_tag in included.findall("File"):
            rel = file_tag.get("name") or file_tag.get("Name", "")
            if not rel:
                continue
            candidate = (base_dir / rel).resolve()
            if not candidate.exists() or candidate in _ancestors:
                continue
            try:
                child_root = ET.parse(candidate).getroot()
            except ET.ParseError:
                continue
            child_root = resolve_included(
                child_root, candidate.parent, _ancestors | {candidate}
            )
            for elem in list(child_root):
                parent.insert(insert_at, elem)
                insert_at += 1
    return root


def included_targets(root: ET.Element, base_dir: Path) -> set[Path]:
    """Resolved paths this deck pulls in via ``<Included>``.

    Extension-agnostic on purpose: GEOS decks include `.xml` *and* `.geos`
    dependency files, and treating the latter as invisible is what let their
    basenames reach a shipped adapter in the previous system.
    """
    out: set[Path] = set()
    for file_tag in root.iter("File"):
        rel = file_tag.get("name") or file_tag.get("Name", "")
        if not rel:
            continue
        candidate = (base_dir / rel).resolve()
        if candidate.exists():
            out.add(candidate)
    return out


def load_and_resolve_dir(directory: Path) -> ET.Element:
    """Parse every XML in ``directory`` and return one resolved deck root.

    A directory with exactly one non-included entry file resolves to that
    file's root; anything else is merged under a synthetic ``<Problem>`` so a
    multi-entry workspace still scores rather than erroring.
    """
    directory = Path(directory)
    xml_files = sorted(directory.rglob("*.xml"))
    if not xml_files:
        raise FileNotFoundError(f"No XML files found in {directory}")

    parsed: dict[Path, ET.Element] = {}
    parse_errors: list[str] = []
    for xml_file in xml_files:
        try:
            parsed[xml_file.resolve()] = ET.parse(xml_file).getroot()
        except ET.ParseError as exc:
            parse_errors.append(f"{xml_file.name}: {exc}")

    if parse_errors and not parsed:
        raise ValueError(
            f"Failed to parse XMLs in {directory}: {'; '.join(parse_errors)}"
        )

    referenced: set[Path] = set()
    for file_path, root in parsed.items():
        referenced |= included_targets(root, file_path.parent)

    entries = [fp for fp in parsed if fp not in referenced]
    if len(entries) == 1:
        return resolve_included(
            parsed[entries[0]], entries[0].parent, frozenset({entries[0]})
        )

    merged = ET.Element("Problem")
    for file_path, root in parsed.items():
        resolved = resolve_included(root, file_path.parent, frozenset({file_path}))
        for child in list(resolved):
            merged.append(child)
    return merged


def load_and_resolve_file(xml_path: Path) -> ET.Element:
    xml_path = Path(xml_path)
    root = ET.parse(xml_path).getroot()
    return resolve_included(root, xml_path.parent, frozenset({xml_path.resolve()}))


def entry_files(directory: Path) -> list[Path]:
    """XML files in ``directory`` that nothing else includes.

    These are what `geosx -i` should be pointed at; validating an include
    fragment on its own reports spurious structural errors.
    """
    directory = Path(directory)
    parsed: dict[Path, ET.Element] = {}
    for xml_file in sorted(directory.rglob("*.xml")):
        try:
            parsed[xml_file.resolve()] = ET.parse(xml_file).getroot()
        except ET.ParseError:
            continue
    referenced: set[Path] = set()
    for file_path, root in parsed.items():
        referenced |= included_targets(root, file_path.parent)
    return sorted(fp for fp in parsed if fp not in referenced)


# ============================================================
# Attribute value comparison
# ============================================================

def _parse_scalar(value: str) -> float | None:
    s = value.strip()
    if _SCALAR_RE.match(s):
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _parse_list(value: str) -> list[float] | None:
    tokens = [
        p.strip() for p in value.strip().strip("{").strip("}").split(",") if p.strip()
    ]
    floats: list[float] = []
    for token in tokens:
        parsed = _parse_scalar(token)
        if parsed is None:
            return None
        floats.append(parsed)
    return floats if floats else None


def values_equivalent(v1: str, v2: str, rtol: float = NUMERIC_RTOL) -> bool:
    """Are two GEOS attribute values the same value?

    Handles the three forms GEOS decks use interchangeably: exact strings,
    numbers written differently (``1e6`` vs ``1000000``), and brace-delimited
    numeric lists. Falls back to case-insensitive string equality.
    """
    left = (v1 or "").strip()
    right = (v2 or "").strip()
    if left == right:
        return True

    n1 = _parse_scalar(left)
    n2 = _parse_scalar(right)
    if n1 is not None and n2 is not None:
        if n1 == 0.0 and n2 == 0.0:
            return True
        denom = max(abs(n1), abs(n2))
        return denom == 0.0 or abs(n1 - n2) / denom <= rtol

    l1 = _parse_list(left)
    l2 = _parse_list(right)
    if l1 is not None and l2 is not None and len(l1) == len(l2):
        return all(values_equivalent(str(a), str(b), rtol) for a, b in zip(l1, l2))

    return left.lower() == right.lower()


# ============================================================
# Matching
# ============================================================

def compute_element_similarity(
    gt: ET.Element, gen: ET.Element, rtol: float = NUMERIC_RTOL
) -> float:
    """Pairing score used only to decide *which* elements correspond.

    A matching ``name`` is worth 0.4 because GEOS decks repeat tags
    (``FieldSpecification``, ``PeriodicEvent``) and the name is the only stable
    identity they carry.
    """
    if gt.tag != gen.tag:
        return 0.0

    gt_attrs = dict(gt.attrib)
    gen_attrs = dict(gen.attrib)

    gt_name = gt_attrs.get("name", "")
    gen_name = gen_attrs.get("name", "")
    name_bonus = 0.0
    if gt_name and gen_name:
        name_bonus = 0.4 if gt_name == gen_name else 0.0

    all_keys = (set(gt_attrs) | set(gen_attrs)) - {"name"}
    if not all_keys:
        return 0.6 + name_bonus

    matched = sum(
        1
        for k in all_keys
        if k in gt_attrs
        and k in gen_attrs
        and values_equivalent(gt_attrs[k], gen_attrs[k], rtol)
    )
    attr_score = matched / len(all_keys) * 0.6

    return min(1.0, attr_score + name_bonus)


def _bipartite_match(
    gt_elems: Sequence[ET.Element],
    gen_elems: Sequence[ET.Element],
    rtol: float = NUMERIC_RTOL,
) -> tuple[list[tuple[int, int, float]], list[int], list[int]]:
    """Greedy 1:1 matching by descending similarity.

    Greedy rather than Hungarian: same-tag groups in a GEOS deck are under ~15
    elements and name matching gives a decisive signal, so the optimal
    assignment and the greedy one agree in practice.
    """
    n_gt = len(gt_elems)
    n_gen = len(gen_elems)

    if n_gt == 0:
        return [], [], list(range(n_gen))
    if n_gen == 0:
        return [], list(range(n_gt)), []

    scores: list[tuple[float, int, int]] = []
    for i, gt in enumerate(gt_elems):
        for j, gen in enumerate(gen_elems):
            sim = compute_element_similarity(gt, gen, rtol)
            if sim > 0:
                scores.append((sim, i, j))

    scores.sort(reverse=True)
    used_gt: set[int] = set()
    used_gen: set[int] = set()
    matched: list[tuple[int, int, float]] = []

    for sim, gi, gj in scores:
        if gi not in used_gt and gj not in used_gen:
            matched.append((gi, gj, sim))
            used_gt.add(gi)
            used_gen.add(gj)

    unmatched_gt = [i for i in range(n_gt) if i not in used_gt]
    unmatched_gen = [j for j in range(n_gen) if j not in used_gen]

    return matched, unmatched_gt, unmatched_gen


def _real_children(node: ET.Element) -> list[ET.Element]:
    return [c for c in node if isinstance(c.tag, str) and c.tag not in IGNORE_TAGS]


@dataclass
class AttrMismatch:
    """One matched element pair's attribute-level disagreement."""

    tag: str
    gt_name: str
    gen_name: str
    attrs_matched: int
    attrs_total: int
    mismatches: list[str] = field(default_factory=list)

    def render(self) -> str:
        who = f"{self.tag}[{self.gt_name}]" if self.gt_name else self.tag
        return f"{who}: {'; '.join(self.mismatches)}"


@dataclass
class MatchResult:
    """Flat record of the recursive match, used for attribute-level evidence."""

    paired: list[tuple[ET.Element, ET.Element, float]] = field(default_factory=list)
    gt_unmatched: list[ET.Element] = field(default_factory=list)
    gen_unmatched: list[ET.Element] = field(default_factory=list)
    attr_details: list[AttrMismatch] = field(default_factory=list)


def match_trees(
    gt_root: ET.Element, gen_root: ET.Element, rtol: float = NUMERIC_RTOL
) -> MatchResult:
    """Recursively pair ground-truth and generated elements.

    Kept alongside TreeSim (which computes its own matching) because TreeSim
    returns scores, not *which attribute was wrong*, and `bad_attribute_value`
    is one of the failure categories a proposer is expected to act on.
    """
    result = MatchResult()
    _match_children(gt_root, gen_root, result, rtol)
    return result


def _match_children(
    gt_parent: ET.Element, gen_parent: ET.Element, result: MatchResult, rtol: float
) -> None:
    gt_by_tag: dict[str, list[ET.Element]] = defaultdict(list)
    gen_by_tag: dict[str, list[ET.Element]] = defaultdict(list)
    for c in _real_children(gt_parent):
        gt_by_tag[c.tag].append(c)
    for c in _real_children(gen_parent):
        gen_by_tag[c.tag].append(c)

    for tag in set(gt_by_tag) | set(gen_by_tag):
        gt_group = gt_by_tag.get(tag, [])
        gen_group = gen_by_tag.get(tag, [])
        matched, unmatched_gt, unmatched_gen = _bipartite_match(gt_group, gen_group, rtol)

        for gi, gj, sim in matched:
            gt_elem = gt_group[gi]
            gen_elem = gen_group[gj]
            result.paired.append((gt_elem, gen_elem, sim))

            gt_attrs = dict(gt_elem.attrib)
            gen_attrs = dict(gen_elem.attrib)
            all_keys = set(gt_attrs) | set(gen_attrs)
            n_matched = 0
            mismatches: list[str] = []
            for k in sorted(all_keys):
                if k in gt_attrs and k in gen_attrs:
                    if values_equivalent(gt_attrs[k], gen_attrs[k], rtol):
                        n_matched += 1
                    else:
                        mismatches.append(
                            f"{k}: GT={gt_attrs[k]!r} GEN={gen_attrs[k]!r}"
                        )
                elif k in gt_attrs:
                    mismatches.append(f"{k}: missing in GEN")
                else:
                    mismatches.append(f"{k}: extra in GEN")

            result.attr_details.append(
                AttrMismatch(
                    tag=gt_elem.tag,
                    gt_name=gt_attrs.get("name", ""),
                    gen_name=gen_attrs.get("name", ""),
                    attrs_matched=n_matched,
                    attrs_total=len(all_keys),
                    mismatches=mismatches,
                )
            )
            _match_children(gt_elem, gen_elem, result, rtol)

        for idx in unmatched_gt:
            elem = gt_group[idx]
            result.gt_unmatched.append(elem)
            for desc in elem.iter():
                if desc is not elem and isinstance(desc.tag, str) and desc.tag not in IGNORE_TAGS:
                    result.gt_unmatched.append(desc)
        for idx in unmatched_gen:
            elem = gen_group[idx]
            result.gen_unmatched.append(elem)
            for desc in elem.iter():
                if desc is not elem and isinstance(desc.tag, str) and desc.tag not in IGNORE_TAGS:
                    result.gen_unmatched.append(desc)


# ============================================================
# XMLTreeSim
# ============================================================

def attr_similarity(
    gt: ET.Element, gen: ET.Element, rtol: float = NUMERIC_RTOL
) -> float:
    """|matching attributes| / |union of attributes|; 1.0 if neither has any.

    Union rather than ground-truth-only in the denominator, so inventing extra
    attributes costs score the same way omitting required ones does.
    """
    gt_attrs = dict(gt.attrib)
    gen_attrs = dict(gen.attrib)
    all_keys = set(gt_attrs) | set(gen_attrs)
    if not all_keys:
        return 1.0
    matched = sum(
        1
        for k in all_keys
        if k in gt_attrs
        and k in gen_attrs
        and values_equivalent(gt_attrs[k], gen_attrs[k], rtol)
    )
    return matched / len(all_keys)


@dataclass
class TreeSimDetail:
    """Per-node record of the TreeSim recursion.

    ``children_score`` is -1 for leaves, which is how downstream consumers tell
    "no children to score" apart from "children all scored 0".
    """

    tag: str
    name: str
    score: float
    attr_score: float
    children_score: float
    n_gt_children: int
    n_matched: int
    n_extra: int
    children: list["TreeSimDetail"] = field(default_factory=list)

    def to_dict(self, max_depth: int = 3, _depth: int = 0) -> dict[str, Any]:
        d: dict[str, Any] = {
            "tag": self.tag,
            "name": self.name,
            "score": self.score,
            "attr_score": self.attr_score,
            "n_gt_children": self.n_gt_children,
            "n_matched": self.n_matched,
            "n_extra": self.n_extra,
        }
        if self.children_score >= 0:
            d["children_score"] = self.children_score
        if self.children and _depth < max_depth:
            d["children"] = [c.to_dict(max_depth, _depth + 1) for c in self.children]
        return d


def tree_sim(
    gt_node: ET.Element,
    gen_node: ET.Element,
    alpha: float = TREESIM_ALPHA,
    beta: float = TREESIM_BETA,
    rtol: float = NUMERIC_RTOL,
) -> tuple[float, TreeSimDetail]:
    """Recursive tree similarity in [0, 1].

    Every ground-truth child contributes ``1/N_gt`` of its parent's score, so a
    node's weight is its share of the ground-truth tree rather than of the
    generated one -- an agent cannot dilute a missing section by writing more
    of something else. Matched leaves contribute their attribute similarity;
    matched interior nodes contribute ``alpha * own attrs + (1-alpha) *
    subtree``. Unmatched ground-truth children contribute 0, and extra
    generated children cost ``beta * extras/(N_gt + extras)``.
    """
    gt_children = _real_children(gt_node)
    gen_children = _real_children(gen_node)

    n_gt = len(gt_children)

    if n_gt == 0 and len(gen_children) == 0:
        a_score = attr_similarity(gt_node, gen_node, rtol)
        return a_score, TreeSimDetail(
            tag=gt_node.tag,
            name=gt_node.get("name", ""),
            score=a_score,
            attr_score=a_score,
            children_score=-1,
            n_gt_children=0,
            n_matched=0,
            n_extra=0,
        )

    gt_by_tag: dict[str, list[ET.Element]] = defaultdict(list)
    gen_by_tag: dict[str, list[ET.Element]] = defaultdict(list)
    for c in gt_children:
        gt_by_tag[c.tag].append(c)
    for c in gen_children:
        gen_by_tag[c.tag].append(c)

    child_scores: list[float] = []
    child_details: list[TreeSimDetail] = []
    total_extra = 0

    for tag in sorted(set(gt_by_tag) | set(gen_by_tag)):
        gt_group = gt_by_tag.get(tag, [])
        gen_group = gen_by_tag.get(tag, [])

        matched, unmatched_gt, unmatched_gen = _bipartite_match(gt_group, gen_group, rtol)

        for gi, gj, _sim in matched:
            gt_elem = gt_group[gi]
            gen_elem = gen_group[gj]
            a_score = attr_similarity(gt_elem, gen_elem, rtol)

            if _real_children(gt_elem):
                subtree_score, subtree_detail = tree_sim(
                    gt_elem, gen_elem, alpha, beta, rtol
                )
                child_score = alpha * a_score + (1 - alpha) * subtree_score
                subtree_detail.score = round(child_score, 4)
                subtree_detail.attr_score = round(a_score, 4)
                child_details.append(subtree_detail)
            else:
                child_score = a_score
                child_details.append(
                    TreeSimDetail(
                        tag=gt_elem.tag,
                        name=gt_elem.get("name", ""),
                        score=round(child_score, 4),
                        attr_score=round(a_score, 4),
                        children_score=-1,
                        n_gt_children=0,
                        n_matched=0,
                        n_extra=0,
                    )
                )
            child_scores.append(child_score)

        for idx in unmatched_gt:
            elem = gt_group[idx]
            child_scores.append(0.0)
            child_details.append(
                TreeSimDetail(
                    tag=elem.tag,
                    name=elem.get("name", ""),
                    score=0.0,
                    attr_score=0.0,
                    children_score=-1,
                    n_gt_children=0,
                    n_matched=0,
                    n_extra=0,
                )
            )

        total_extra += len(unmatched_gen)

    matched_score = sum(child_scores) / n_gt if n_gt > 0 else 1.0

    extra_denom = n_gt + total_extra
    extra_penalty = beta * (total_extra / extra_denom) if extra_denom > 0 else 0.0

    node_score = max(0.0, min(1.0, matched_score - extra_penalty))
    own_attr = attr_similarity(gt_node, gen_node, rtol)

    detail = TreeSimDetail(
        tag=gt_node.tag,
        name=gt_node.get("name", ""),
        score=round(node_score, 4),
        attr_score=round(own_attr, 4),
        children_score=round(matched_score, 4),
        n_gt_children=n_gt,
        n_matched=len(child_scores) - sum(1 for s in child_scores if s == 0.0),
        n_extra=total_extra,
        children=child_details,
    )

    return node_score, detail


def tree_sim_section_scores(
    gt_root: ET.Element,
    gen_root: ET.Element,
    alpha: float = TREESIM_ALPHA,
    beta: float = TREESIM_BETA,
    rtol: float = NUMERIC_RTOL,
) -> dict[str, Any]:
    """TreeSim headline plus the per-top-level-section breakdown."""
    score, detail = tree_sim(gt_root, gen_root, alpha, beta, rtol)
    section_scores = {
        (child.name or child.tag): child.score for child in detail.children
    }
    return {
        "treesim": round(score, 4),
        "section_scores": section_scores,
        "detail": detail,
    }


# ============================================================
# Diagnosis helpers (ported from repo3/scripts/bottleneck/extract.py)
# ============================================================

def worst_subtrees(detail: TreeSimDetail, k: int = 8) -> list[dict[str, Any]]:
    """Top-``k`` subtrees by impact = (1 - score) * subtree size.

    Ranking by impact rather than by score is what stops the drill-down from
    being dominated by one wrong attribute on a leaf while a whole missing
    section sits below it. Leaves are excluded; they are covered by the
    missing/extra element summary instead.
    """
    scored: list[dict[str, Any]] = []
    for path, node in _flatten_detail(detail):
        size = node.n_gt_children + 1
        if size <= 1:
            continue
        impact = (1.0 - node.score) * size
        if impact <= 0:
            continue
        scored.append(
            {
                "path": path,
                "score": round(node.score, 4),
                "attr_score": round(node.attr_score, 4),
                "children_score": round(node.children_score, 4),
                "n_gt_children": node.n_gt_children,
                "n_matched": node.n_matched,
                "n_extra": node.n_extra,
                "missing_child_count": max(0, node.n_gt_children - node.n_matched),
                "impact": round(impact, 4),
            }
        )
    scored.sort(key=lambda x: x["impact"], reverse=True)
    return scored[:k]


def _flatten_detail(
    detail: TreeSimDetail, path: str = ""
) -> list[tuple[str, TreeSimDetail]]:
    here = f"{path}/{detail.tag}"
    if detail.name:
        here = f"{here}[{detail.name}]"
    out = [(here, detail)]
    for child in detail.children:
        out.extend(_flatten_detail(child, here))
    return out


def per_section(detail: TreeSimDetail) -> dict[str, dict[str, Any]]:
    """Top-level section summary, keyed by tag."""
    return {
        child.tag: {
            "score": round(child.score, 4),
            "n_gt_children": child.n_gt_children,
            "n_matched": child.n_matched,
            "n_extra": child.n_extra,
        }
        for child in detail.children
    }


# ============================================================
# Evaluation entry points
# ============================================================

def evaluate_xml(
    gt_root: ET.Element, gen_root: ET.Element, rtol: float = NUMERIC_RTOL
) -> dict[str, Any]:
    """Score one resolved deck against one resolved ground-truth deck."""
    ts = tree_sim_section_scores(gt_root, gen_root, rtol=rtol)
    detail: TreeSimDetail = ts["detail"]
    match = match_trees(gt_root, gen_root, rtol)

    gt_types = {e.tag for e in gt_root.iter() if isinstance(e.tag, str)} - IGNORE_TAGS
    gen_types = {e.tag for e in gen_root.iter() if isinstance(e.tag, str)} - IGNORE_TAGS

    return {
        "treesim": ts["treesim"],
        "section_scores": ts["section_scores"],
        "detail": detail,
        "worst_subtrees": worst_subtrees(detail),
        "per_section": per_section(detail),
        "missing_element_types": sorted(gt_types - gen_types),
        "extra_element_types": sorted(gen_types - gt_types),
        "gt_sections": sorted(c.tag for c in gt_root if isinstance(c.tag, str)),
        "gen_sections": sorted(c.tag for c in gen_root if isinstance(c.tag, str)),
        "n_extra": detail.n_extra,
        "match_summary": {
            "paired_elements": len(match.paired),
            "gt_unmatched": len(match.gt_unmatched),
            "gen_unmatched": len(match.gen_unmatched),
        },
        "attr_mismatches": [
            d.render() for d in match.attr_details if d.mismatches
        ][:20],
    }


def evaluate_directories(
    gt_dir: Path, gen_dir: Path, rtol: float = NUMERIC_RTOL
) -> dict[str, Any]:
    """Load both directories (resolving includes) and evaluate."""
    result = evaluate_xml(
        load_and_resolve_dir(gt_dir), load_and_resolve_dir(gen_dir), rtol
    )
    result["gt_dir"] = str(gt_dir)
    result["gen_dir"] = str(gen_dir)
    return result


# ============================================================
# Contamination: variant siblings
# ============================================================

#: Suffixes GEOS example decks use for near-identical variants of one problem.
#: Ordered longest-first so `_base_iterative` is stripped before `_base`.
VARIANT_SUFFIXES: tuple[str, ...] = (
    "_base_iterative",
    "_base_direct",
    "_iterative_base",
    "_direct_base",
    "_iterative",
    "_direct",
    "_benchmark",
    "_smoke",
    "_base",
)

#: Stems too generic to key on: blocking every `base.xml` in the GEOS tree
#: would hide most of the corpus, not just this task's answer.
GENERIC_STEMS: frozenset[str] = frozenset(
    {"base", "benchmark", "input", "inputs", "problem", "model", "smoke"}
)

#: Below this length a stem is treated as generic even if it is not in the list
#: above. Ported from repo3; it is a heuristic, not a measured threshold.
MIN_STEM_LENGTH = 10


def variant_stem_keys(filename: str) -> set[str]:
    """Normalized stem keys for a deck filename.

    ``Foo_base.xml``, ``Foo_benchmark.xml`` and ``Foo_base_iterative.xml`` all
    reduce to ``{"foo"}``, which is how a sibling variant of the answer gets
    blocked along with the answer itself.
    """
    stem = Path(filename).stem.lower()
    keys: set[str] = set()
    pending = [stem]
    while pending:
        s = pending.pop()
        if s in keys:
            continue
        keys.add(s)
        for suffix in VARIANT_SUFFIXES:
            if s.endswith(suffix):
                stripped = s[: -len(suffix)]
                if stripped and stripped not in keys:
                    pending.append(stripped)
    return {k for k in keys if len(k) >= MIN_STEM_LENGTH and k not in GENERIC_STEMS}


def expand_with_variants(
    basenames: Iterable[str],
    source_dir: Path,
    extensions: Iterable[str] = ("xml", "geos"),
) -> set[str]:
    """Add every variant sibling of ``basenames`` found under ``source_dir``.

    Scans `.geos` as well as `.xml`, unlike the repo3 original: a `.geos`
    dependency file of a blocked deck leaks the same content, and the `.xml`-only
    assumption is the exact shape of the leak the previous system shipped.
    """
    lowered = {b.lower() for b in basenames}
    keys: set[str] = set()
    for name in lowered:
        keys |= variant_stem_keys(name)
    if not keys:
        return lowered

    expanded = set(lowered)
    source_dir = Path(source_dir)
    if not source_dir.is_dir():
        return expanded
    for ext in extensions:
        for path in source_dir.rglob(f"*.{ext}"):
            if path.is_file() and variant_stem_keys(path.name) & keys:
                expanded.add(path.name.lower())
    return expanded


# ============================================================
# The simulator
# ============================================================

@SimulatorRegistry.register
class GeosSimulator(SimulatorSpec):
    """GEOS deck authoring: TreeSim scoring, geosx validation, variant blocking."""

    name = "geos"

    #: `.geos` belongs here. The previous system's leak gate hardcoded `.xml`,
    #: so ground-truth `.geos` dependency filenames reached a shipped adapter.
    leaky_extensions = ("xml", "geos")

    required_sections = REQUIRED_SECTIONS

    def __init__(
        self,
        geosx_executable: str | None = None,
        geos_source_dir: str | Path | None = None,
        validate_timeout: float = DEFAULT_VALIDATE_TIMEOUT,
    ) -> None:
        self.geosx_executable = geosx_executable or os.environ.get("GEOSX_EXECUTABLE", "")
        source = geos_source_dir or os.environ.get("GEOS_SOURCE_DIR", "")
        self.geos_source_dir = Path(source) if source else None
        self.validate_timeout = validate_timeout

    # -- parsing ---------------------------------------------------------
    def parse(self, workspace: Path) -> Artifact:
        """Collect deck text and resolve it to one tree; never raises.

        `.geos` files are captured in ``files`` even though only `.xml` files
        are entry-point candidates, because a hygiene check that cannot see
        them cannot flag them.
        """
        artifact = Artifact()
        workspace = Path(workspace)
        if not workspace.is_dir():
            artifact.parse_errors["<workspace>"] = f"not a directory: {workspace}"
            return artifact

        for ext in ("xml", "geos"):
            for path in sorted(workspace.rglob(f"*.{ext}")):
                rel = path.relative_to(workspace).as_posix()
                try:
                    artifact.files[rel] = path.read_text(errors="replace")
                except OSError as exc:
                    artifact.parse_errors[rel] = str(exc)
                    continue
                try:
                    ET.parse(path)
                except ET.ParseError as exc:
                    artifact.parse_errors[rel] = str(exc)

        try:
            artifact.tree = load_and_resolve_dir(workspace)
        except (FileNotFoundError, ValueError) as exc:
            artifact.parse_errors.setdefault("<deck>", str(exc))
        return artifact

    def present_sections(self, artifact: Artifact) -> set[str]:
        root = artifact.tree
        if not isinstance(root, ET.Element):
            return set()
        return {c.tag for c in root if isinstance(c.tag, str)}

    # -- validation ------------------------------------------------------
    def validate(self, artifact: Artifact, workspace: Path) -> list[Finding]:
        """Run `geosx -i <entry> --validate-input` over each entry deck.

        The validator's combined stdout/stderr is returned verbatim in the
        finding message. GEOS prints the complete table of valid attributes for
        the offending element on an unknown-attribute error and the full list of
        legal child tags on an unknown-element error; summarizing that away is
        precisely what turns a live validator into a static gate.
        """
        workspace = Path(workspace)
        findings: list[Finding] = [
            Finding("xml_parse", "error", msg, location=rel)
            for rel, msg in sorted(artifact.parse_errors.items())
            if rel != "<deck>"
        ]

        reasons = self.preflight()
        if reasons:
            findings.append(
                Finding("geosx_validate", "info", "; ".join(reasons))
            )
            return findings

        entries = entry_files(workspace)
        if not entries:
            findings.append(
                Finding(
                    "geosx_validate",
                    "error",
                    "no entry XML deck found to validate",
                    location=str(workspace),
                )
            )
            return findings

        for entry in entries:
            findings.append(self._validate_one(entry, workspace))
        return findings

    def _validate_one(self, entry: Path, workspace: Path) -> Finding:
        cmd = [self.geosx_executable, "-i", str(entry), "--validate-input"]
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
                "geosx_validate",
                "error",
                f"validation timed out after {self.validate_timeout:g}s",
                location=entry.name,
            )
        except OSError as exc:
            return Finding(
                "geosx_validate", "error", f"could not run geosx: {exc}",
                location=entry.name,
            )

        output = _combined_output(proc.stdout, proc.stderr)
        if proc.returncode == 0:
            return Finding(
                "geosx_validate", "info", "input validation passed",
                location=entry.name,
            )
        return Finding(
            "geosx_validate",
            "error",
            output or f"geosx exited {proc.returncode} with no output",
            location=entry.name,
        )

    # -- scoring ---------------------------------------------------------
    def score(self, generated: Path, ground_truth: Path, task: TaskId) -> Score:
        """TreeSim in [0,1], failures-as-zero.

        Every way of not producing a scorable deck -- empty workspace,
        unparseable XML, missing ground truth -- lands on 0.0 with a distinct
        ``status``, because the *rate* of those is the quantity the whole
        reliability argument is about.
        """
        try:
            result = evaluate_directories(Path(ground_truth), Path(generated))
        except FileNotFoundError as exc:
            status = (
                "missing_ground_truth"
                if not _has_xml(Path(ground_truth))
                else "empty_workspace"
            )
            return Score(task=task, value=0.0, status=status, detail={"error": str(exc)})
        except (ET.ParseError, ValueError) as exc:
            return Score(
                task=task, value=0.0, status="parse_error", detail={"error": str(exc)}
            )

        return Score(
            task=task,
            value=float(result["treesim"]),
            status="success",
            detail={
                "section_scores": result["section_scores"],
                "missing_element_types": result["missing_element_types"],
                "extra_element_types": result["extra_element_types"],
                "n_extra": result["n_extra"],
                "match_summary": result["match_summary"],
                "gt_sections": result["gt_sections"],
                "gen_sections": result["gen_sections"],
            },
        )

    def diagnose(
        self, generated: Path, ground_truth: Path, task: TaskId
    ) -> Diagnosis:
        """Per-section scores, worst subtrees, and a failure-category guess."""
        try:
            result = evaluate_directories(Path(ground_truth), Path(generated))
        except (FileNotFoundError, ET.ParseError, ValueError) as exc:
            return Diagnosis(
                category="partial_implementation", notes=[f"unscorable: {exc}"]
            )

        missing_sections = [
            s for s in self.required_sections if s not in result["gen_sections"]
        ]
        notes = list(result["attr_mismatches"])
        if missing_sections:
            notes.insert(0, f"required sections absent: {', '.join(missing_sections)}")

        return Diagnosis(
            section_scores=dict(result["section_scores"]),
            worst_subtrees=result["worst_subtrees"],
            missing_elements=result["missing_element_types"],
            extra_elements=result["extra_element_types"],
            n_extra=int(result["n_extra"]),
            category=_classify(result, missing_sections),
            notes=notes,
        )

    # -- contamination ---------------------------------------------------
    def contamination_policy(
        self, task: TaskId, ground_truth_root: Path
    ) -> ContaminationPolicy:
        """Block the task's ground truth *and* its variant siblings.

        A benchmark that blocks `Foo_base.xml` but leaves `Foo_benchmark.xml`
        readable in the source tree has stopped measuring authoring capability
        and started measuring file search.
        """
        gt_dir = Path(ground_truth_root) / task
        exact = {
            p.name.lower()
            for p in gt_dir.rglob("*")
            if p.is_file() and p.suffix.lower().lstrip(".") in self.leaky_extensions
        } if gt_dir.is_dir() else set()

        if self.geos_source_dir and self.geos_source_dir.is_dir():
            blocked = expand_with_variants(
                exact, self.geos_source_dir, self.leaky_extensions
            )
            reason = "task ground truth + variant siblings in the GEOS source"
        else:
            blocked = exact
            reason = "task ground truth (GEOS source dir unavailable; no variant expansion)"

        return ContaminationPolicy(blocked_basenames=blocked, reason=reason)

    # -- environment -----------------------------------------------------
    def preflight(self) -> list[str]:
        """Report, never raise: the caller may legitimately fall back to mock."""
        if not self.geosx_executable:
            return ["GEOSX_EXECUTABLE is not set; geosx --validate-input unavailable"]
        exe = Path(self.geosx_executable)
        if exe.is_absolute() or exe.parent != Path("."):
            if not exe.exists():
                return [f"geosx binary not found at {self.geosx_executable}"]
        elif shutil.which(self.geosx_executable) is None:
            return [f"geosx binary {self.geosx_executable!r} not on PATH"]
        return []


def _combined_output(stdout: str, stderr: str) -> str:
    parts = [p.strip() for p in (stderr, stdout) if p and p.strip()]
    text = "\n".join(parts)
    if len(text) > MAX_VALIDATOR_CHARS:
        return text[:MAX_VALIDATOR_CHARS] + f"\n...[truncated at {MAX_VALIDATOR_CHARS} chars]"
    return text


def _has_xml(directory: Path) -> bool:
    return directory.is_dir() and any(directory.rglob("*.xml"))


def _classify(result: dict[str, Any], missing_sections: Sequence[str]) -> str:
    """Heuristic failure category, in the vocabulary of ``types.FailureCategory``.

    Deliberately coarse: it exists so evidence, proposals and reports share one
    label, not to be a classifier. The LLM-side classifier refines it.
    """
    if missing_sections:
        return "missing_block"
    if result["missing_element_types"]:
        return "partial_implementation"
    if result["n_extra"] and len(result["extra_element_types"]) > 2:
        return "hallucinated_extras"
    if result["attr_mismatches"]:
        return "bad_attribute_value"
    if result["treesim"] >= 0.999:
        return "no_failure"
    return "structural_mismatch"
