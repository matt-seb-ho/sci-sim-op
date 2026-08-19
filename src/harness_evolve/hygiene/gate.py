"""The contamination rule set: one function per rule, one report per candidate.

Ground-truth decks live in the same source tree the agent explores, and the
search loop mines adapter content out of execution trajectories. Leakage into
the adapter is therefore a demonstrated failure mode of the predecessor system,
not a hypothetical one, and it has two documented shapes:

1. A basename filter that only knew ``.xml`` let ground-truth *dependency*
   filenames (``tables/time.geos``) through into a shipped adapter, across
   three files. :func:`rule_filenames` covers every extension the simulator
   declares leaky, and :func:`rule_path_components` covers the directory names
   that survive a basename-only strip.
2. A cheatsheet that was a task-name to canonical-deck lookup table for all
   evaluation tasks, which converts the agent's search problem into a table
   lookup. :func:`rule_task_ids` catches it by name and
   :func:`rule_lookup_tables` catches its *shape*, so a renamed or paraphrased
   table does not walk through.

Everything past that pair is defence against the leak we have not seen yet: an
adapter that carries the answer without carrying the strings. Content overlap,
IDF-weighted rare-token overlap, structural fingerprinting, near-miss stems and
numeric leakage each cover a different way of doing that.

Severity is calibrated, not maximal. ``error`` blocks; ``warn`` is for signals
that are individually explainable by legitimate content and only damning in
aggregate; ``info`` is context that makes a report actionable. A gate that
blocks on everything gets routed around, and a gate that is routed around is
worse than no gate -- so the rules that fire on ordinary domain prose are
deliberately non-blocking, and :class:`GateConfig` exposes an explicit override
map so an operator retunes the gate instead of disabling it.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from harness_evolve.hygiene.corpus import (
    GENERIC_STEMS,
    MIN_STEM_LEN,
    VARIANT_SUFFIXES,
    GroundTruthCorpus,
    canonical_numerics,
    ngram_set,
    word_tokens,
)
from harness_evolve.types import Finding, Severity


class HygieneError(ValueError):
    """Raised when a candidate fails the contamination gate."""


@dataclass(frozen=True)
class GateConfig:
    """Thresholds and severities for one gate run.

    Defaults are tuned against the two real incidents plus a hand-written
    legitimate cheatsheet: both incidents block, the legitimate artifact
    produces no ``error``. Thresholds are fields rather than constants because
    the right value depends on how much ground truth the corpus actually
    carries -- a corpus built from a blocklist has no deck text, so the content
    rules are inert and the name rules carry the whole load.
    """

    #: Distinct shared n-grams with one ground-truth deck.
    ngram_error: int = 3
    ngram_warn: int = 1
    #: Distinct ground-truth numeric literals present in one artifact.
    numeric_error: int = 6
    numeric_warn: int = 3
    #: Shared structural fingerprints (element sub-sequences) with one deck.
    fingerprint_error: int = 4
    fingerprint_warn: int = 2
    #: Distinct rare (high-IDF) ground-truth tokens present in one artifact.
    rare_token_error: int = 8
    rare_token_warn: int = 4
    #: Fraction of decks a token may appear in and still count as rare.
    rare_token_df_fraction: float = 0.1
    #: Shortest token length considered for rare-token and near-miss matching.
    min_token_len: int = 6
    #: difflib ratio above which a token is a near-miss for a ground-truth stem.
    near_miss_ratio: float = 0.86
    #: Task-shaped rows required before a table is called a lookup table.
    lookup_table_rows: int = 3
    #: Severity for a simulator-artifact filename that is *not* a known ground
    #: truth. Blocking by default: incident 1 is precisely the case where the
    #: leaked name was absent from the blocklist the gate was checking against.
    unknown_filename_severity: Severity = "error"
    #: Severity for a single task id. Naming one evaluation task in an
    #: always-on artifact is task-specific tuning even when it leaks no file.
    task_id_severity: Severity = "error"
    #: Per rule, per file. Keeps a report readable instead of a 200-line dump.
    max_findings_per_rule: int = 8
    #: Rule name -> severity, applied after all rules run.
    severity_overrides: Mapping[str, Severity] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------


@dataclass
class HygieneReport:
    """Per-rule findings plus the blocking verdict for one artifact set."""

    findings: list[Finding] = field(default_factory=list)
    checked_paths: list[str] = field(default_factory=list)
    rules_run: tuple[str, ...] = ()
    corpus_summary: Mapping[str, int] = field(default_factory=dict)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "warn"]

    @property
    def blocked(self) -> bool:
        """True when at least one finding is an ``error``. This is the verdict."""
        return bool(self.errors)

    @property
    def passed(self) -> bool:
        return not self.blocked

    def by_rule(self) -> dict[str, list[Finding]]:
        out: dict[str, list[Finding]] = {}
        for f in self.findings:
            out.setdefault(f.source, []).append(f)
        return out

    def by_path(self) -> dict[str, list[Finding]]:
        out: dict[str, list[Finding]] = {}
        for f in self.findings:
            out.setdefault(f.location.split(":")[0], []).append(f)
        return out

    def raise_if_blocked(self) -> None:
        """Raise :class:`HygieneError` listing every blocking finding."""
        if self.blocked:
            raise HygieneError(
                f"{len(self.errors)} blocking hygiene finding(s):\n  "
                + "\n  ".join(f.render() for f in self.errors)
            )

    def render(self) -> str:
        """Human-readable report, ordered so blocking findings come first."""
        order = {"error": 0, "warn": 1, "info": 2}
        lines = [f.render() for f in sorted(self.findings, key=lambda f: order[f.severity])]
        lines.append(
            f"{len(self.checked_paths)} file(s) checked against "
            f"{self.corpus_summary.get('blocked_basenames', 0)} blocked basename(s), "
            f"{self.corpus_summary.get('task_ids', 0)} task id(s), "
            f"{self.corpus_summary.get('decks', 0)} deck(s): "
            f"{len(self.errors)} blocking, {len(self.warnings)} warning(s)"
        )
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "n_blocking": len(self.errors),
            "n_warnings": len(self.warnings),
            "findings": [f.to_dict() for f in self.findings],
            "checked_paths": list(self.checked_paths),
            "rules_run": list(self.rules_run),
            "corpus": dict(self.corpus_summary),
        }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _line_at(text: str, index: int) -> int:
    """1-based line number of ``index``, so a finding points at a place to edit."""
    return text.count("\n", 0, index) + 1


def _loc(path: str, line: int | None = None) -> str:
    return f"{path}:{line}" if line else path


def _cap(findings: list[Finding], cfg: GateConfig, rule: str, path: str) -> list[Finding]:
    """Truncate a rule's output, leaving a marker so the count is not lost."""
    if len(findings) <= cfg.max_findings_per_rule:
        return findings
    kept = findings[: cfg.max_findings_per_rule]
    kept.append(
        Finding(
            rule,
            kept[0].severity,
            f"and {len(findings) - cfg.max_findings_per_rule} further {rule} hit(s) "
            "not listed",
            _loc(path),
        )
    )
    return kept


def _strip_variants(token: str) -> str:
    """Reduce a bare identifier to its variant-free stem."""
    changed = True
    while changed:
        changed = False
        for suffix in VARIANT_SUFFIXES:
            if token.endswith(suffix) and len(token) > len(suffix):
                token = token[: -len(suffix)]
                changed = True
                break
    return token


_IDENT_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{3,}")


def _identifier_tokens(text: str) -> dict[str, int]:
    """Lowercased identifier-ish tokens mapped to their first offset."""
    out: dict[str, int] = {}
    for m in _IDENT_RE.finditer(text):
        tok = m.group(0).lower()
        out.setdefault(tok, m.start())
    return out


# ---------------------------------------------------------------------------
# rules
# ---------------------------------------------------------------------------


def rule_filenames(
    path: str, text: str, corpus: GroundTruthCorpus, cfg: GateConfig
) -> list[Finding]:
    """Any simulator-artifact filename, over every extension the simulator declares.

    The predecessor gate hardcoded ``.xml``; ``tables/time.geos``,
    ``tables/radialStress.geos`` and ``tables/axialStrain.geos`` reached the
    shipped adapter through that hole. An unknown filename is blocking too, by
    default: the leaked names were not on the blocklist being checked, so
    "known ground truth" is not a safe precondition for blocking.
    """
    pattern = corpus.leak_pattern()
    seen: dict[str, int] = {}
    for m in pattern.finditer(text):
        seen.setdefault(m.group(1), m.start())
    findings: list[Finding] = []
    for name, idx in sorted(seen.items(), key=lambda kv: kv[1]):
        known = name.lower() in corpus.blocked_basenames
        findings.append(
            Finding(
                "filename" if known else "filename_generic",
                "error" if known else cfg.unknown_filename_severity,
                (
                    f"names ground-truth artifact {name!r}"
                    if known
                    else f"names simulator artifact file {name!r}; adapters must "
                    "describe the interface, never point at a specific deck"
                ),
                _loc(path, _line_at(text, idx)),
            )
        )
    return _cap(findings, cfg, "filename", path)


def rule_path_components(
    path: str, text: str, corpus: GroundTruthCorpus, cfg: GateConfig
) -> list[Finding]:
    """Ground-truth directory components, which survive a basename-only strip.

    The predecessor's redaction turned ``poromechanics/Foo_base.xml`` into
    ``poromechanics/<file>`` and shipped it: the physics family, the directory
    to search, and the fact that a canonical deck lives there all survive. A
    bare mention of a directory name is warn-level -- ``poromechanics`` is also
    an ordinary word in this domain -- but using it as a path prefix
    (``poromechanics/Something``) is a pointer, and blocks.
    """
    findings: list[Finding] = []
    for part in sorted(corpus.blocked_path_parts):
        m = re.search(rf"(?<![A-Za-z0-9_]){re.escape(part)}(?![A-Za-z0-9_])", text, re.I)
        if not m:
            continue
        as_prefix = re.search(
            rf"(?<![A-Za-z0-9_]){re.escape(part)}/[A-Za-z0-9_*]", text, re.I
        )
        findings.append(
            Finding(
                "path_component",
                "error" if as_prefix else "warn",
                (
                    f"uses ground-truth directory {part!r} as a path prefix"
                    if as_prefix
                    else f"names ground-truth directory component {part!r}"
                ),
                _loc(path, _line_at(text, (as_prefix or m).start())),
            )
        )
    return _cap(findings, cfg, "path_component", path)


def rule_task_ids(
    path: str, text: str, corpus: GroundTruthCorpus, cfg: GateConfig
) -> list[Finding]:
    """Evaluation task identifiers, and especially two or more in one artifact.

    Two-or-more is the signature of the quarantined cheatsheet: a table keyed
    by task name is the highest-value leak an adapter can carry, because it
    replaces the search the benchmark is measuring with a lookup. It is
    reported as one finding rather than N so the report says what the artifact
    *is*, not just which strings it contains.
    """
    hits: list[tuple[str, int]] = []
    for task in sorted(corpus.task_ids):
        m = re.search(
            rf"(?<![A-Za-z0-9_]){re.escape(task)}(?![A-Za-z0-9_])", text, re.I
        )
        if m:
            hits.append((task, m.start()))
    if not hits:
        return []
    if len(hits) >= 2:
        names = ", ".join(t for t, _ in hits[:4])
        more = "..." if len(hits) > 4 else ""
        return [
            Finding(
                "task_id_table",
                "error",
                f"names {len(hits)} evaluation task ids ({names}{more}); this is a "
                "task -> answer lookup table, not interface guidance",
                _loc(path, _line_at(text, min(i for _, i in hits))),
            )
        ]
    task, idx = hits[0]
    return [
        Finding(
            "task_id",
            cfg.task_id_severity,
            f"names evaluation task id {task!r}",
            _loc(path, _line_at(text, idx)),
        )
    ]


def rule_blocklist(
    path: str, text: str, corpus: GroundTruthCorpus, cfg: GateConfig
) -> list[Finding]:
    """Substring match against the runner's own blocklist.

    Kept separate from :func:`rule_filenames` even though they overlap: this
    one needs no tokenization, so it still fires when a blocked name is
    embedded in a larger token or split across markup. It is also the rule that
    ties the hygiene verdict to the exact list the runtime gate hides.
    """
    lowered = text.lower()
    findings: list[Finding] = []
    for name in sorted(corpus.blocked_basenames):
        idx = lowered.find(name)
        if idx >= 0:
            findings.append(
                Finding(
                    "blocklist",
                    "error",
                    f"contains blocked ground-truth basename {name!r}",
                    _loc(path, _line_at(text, idx)),
                )
            )
    return _cap(findings, cfg, "blocklist", path)


def rule_content_overlap(
    path: str, text: str, corpus: GroundTruthCorpus, cfg: GateConfig
) -> list[Finding]:
    """Verbatim n-gram overlap with ground-truth deck text.

    The predecessor gate could not see content at all -- it was a filename
    filter, so an adapter could embed a deck fragment verbatim and pass. Uses
    the corpus's precomputed reference index, so cost is one tokenization of
    the candidate plus a set intersection per deck.
    """
    if not corpus.deck_ngrams:
        return []
    cand = ngram_set(word_tokens(text), corpus.ngram_n)
    if not cand:
        return []
    findings: list[Finding] = []
    for key, ref in corpus.deck_ngrams.items():
        shared = len(cand & ref)
        if shared < cfg.ngram_warn:
            continue
        findings.append(
            Finding(
                "content_overlap",
                "error" if shared >= cfg.ngram_error else "warn",
                f"shares {shared} distinct {corpus.ngram_n}-gram(s) with ground-truth "
                f"deck {key}",
                _loc(path),
            )
        )
    findings.sort(key=lambda f: f.message, reverse=True)
    return _cap(findings, cfg, "content_overlap", path)


def rule_numeric_leakage(
    path: str, text: str, corpus: GroundTruthCorpus, cfg: GateConfig
) -> list[Finding]:
    """Canonicalized ground-truth numeric literals.

    Value correctness is the residual failure mode once structure is handled,
    so an adapter that memorises "permeability 1e-12 for this family" is
    teaching the answer rather than the interface -- the exact substitution the
    exposure literature quantifies as score inflation. Canonicalization is
    notation-blind (``1e-4``, ``1.0E-04``, ``$1.0\\times10^{-4}$``,
    ``1.0x10⁻⁴``) because prose adapters copy whatever notation the trajectory
    used, and trivial values are suppressed so ordinary numbered prose is
    silent.
    """
    if not corpus.numeric_literals:
        return []
    shared = canonical_numerics(text) & corpus.numeric_literals
    if len(shared) < cfg.numeric_warn:
        return []
    sample = ", ".join(sorted(shared)[:6])
    more = "..." if len(shared) > 6 else ""
    return [
        Finding(
            "numeric_leak",
            "error" if len(shared) >= cfg.numeric_error else "warn",
            f"{len(shared)} ground-truth numeric literal(s) present ({sample}{more})",
            _loc(path),
        )
    ]


def rule_near_miss_filenames(
    path: str, text: str, corpus: GroundTruthCorpus, cfg: GateConfig
) -> list[Finding]:
    """Ground-truth filenames named without their extension, or as a family glob.

    A shipped adapter wrote ``PoroElastic_Terzaghi_*`` and
    ``PoroElastic_Mandel_*``: no extension, so an extension-anchored rule sees
    nothing, but the stem names the exact deck family. Matching is on
    variant-stripped stems (``Foo_base``/``Foo_benchmark``/``Foo_smoke`` reduce
    to one key) plus a difflib ratio for the near misses, prefiltered on a
    shared 5-character prefix so cost stays linear in candidate tokens.

    An exact stem hit blocks; a fuzzy hit warns, because at ratio ~0.9 the
    match can be a genuine physics word rather than a filename.
    """
    if not corpus.filename_stems:
        return []
    buckets: dict[str, list[str]] = {}
    for stem in corpus.filename_stems:
        buckets.setdefault(stem[:5], []).append(stem)

    findings: list[Finding] = []
    reported: set[str] = set()
    for token, idx in sorted(_identifier_tokens(text).items(), key=lambda kv: kv[1]):
        if len(token) < MIN_STEM_LEN:
            continue
        stem = _strip_variants(token)
        if len(stem) < MIN_STEM_LEN or stem in GENERIC_STEMS or stem in reported:
            continue
        for candidate_stem in buckets.get(stem[:5], ()):
            if stem == candidate_stem:
                reported.add(stem)
                findings.append(
                    Finding(
                        "near_miss_filename",
                        "error",
                        f"token {token!r} is the ground-truth deck stem "
                        f"{candidate_stem!r} with the extension omitted",
                        _loc(path, _line_at(text, idx)),
                    )
                )
                break
            ratio = difflib.SequenceMatcher(None, stem, candidate_stem).ratio()
            if ratio >= cfg.near_miss_ratio:
                reported.add(stem)
                findings.append(
                    Finding(
                        "near_miss_filename",
                        "warn",
                        f"token {token!r} is a near miss (ratio {ratio:.2f}) for "
                        f"ground-truth deck stem {candidate_stem!r}",
                        _loc(path, _line_at(text, idx)),
                    )
                )
                break
    return _cap(findings, cfg, "near_miss_filename", path)


def rule_structural_fingerprint(
    path: str, text: str, corpus: GroundTruthCorpus, cfg: GateConfig
) -> list[Finding]:
    """Reproduction of a deck's *element sequence* without copying its text.

    An adapter can hand over a deck's skeleton -- which blocks in which order,
    with which nesting -- while sharing no n-gram with it, and that is enough to
    convert authoring into transcription. Fingerprints are built only from
    elements that are *not* present in most decks, because every deck of a given
    simulator opens with the same schema-mandated ordering and counting that
    would flag any adapter that explains the file format.
    """
    if not corpus.deck_fingerprints:
        return []
    cand = corpus.fingerprint(text)
    if not cand:
        return []
    findings: list[Finding] = []
    for key, ref in corpus.deck_fingerprints.items():
        shared = cand & ref
        if len(shared) < cfg.fingerprint_warn:
            continue
        example = " > ".join(sorted(shared)[0])
        findings.append(
            Finding(
                "structural_fingerprint",
                "error" if len(shared) >= cfg.fingerprint_error else "warn",
                f"reproduces {len(shared)} distinct element sub-sequence(s) of "
                f"ground-truth deck {key} (e.g. {example})",
                _loc(path),
            )
        )
    return _cap(findings, cfg, "structural_fingerprint", path)


def rule_rare_token_overlap(
    path: str, text: str, corpus: GroundTruthCorpus, cfg: GateConfig
) -> list[Finding]:
    """IDF-weighted overlap: rare ground-truth identifiers, not common ones.

    Raw n-gram counting weights ``name`` and ``kgdedgebased`` equally, so a
    paraphrased leak -- the same rare identifiers, reordered into prose -- slips
    under a contiguity-based threshold. Document frequency is taken over the
    ground-truth decks themselves, which is the only "background" corpus
    available offline; a token in one deck out of fifty is the signal, a token
    in all fifty is vocabulary.
    """
    if corpus.n_decks < 2:
        return []
    max_df = max(1, round(cfg.rare_token_df_fraction * corpus.n_decks))
    cand = {t for t in word_tokens(text) if len(t) >= cfg.min_token_len}
    hits = [
        t for t in cand
        if 0 < corpus.token_df.get(t, 0) <= max_df and not t.isdigit()
    ]
    if len(hits) < cfg.rare_token_warn:
        return []
    weight = sum(corpus.idf(t) for t in hits)
    top = sorted(hits, key=corpus.idf, reverse=True)[:6]
    return [
        Finding(
            "rare_token_overlap",
            "error" if len(hits) >= cfg.rare_token_error else "warn",
            f"{len(hits)} rare ground-truth identifier(s) present "
            f"(idf weight {weight:.1f}; e.g. {', '.join(sorted(top))})",
            _loc(path),
        )
    ]


_TABLE_ROW_RE = re.compile(r"^\s*\|(?P<body>.*)\|\s*$")
_SEPARATOR_RE = re.compile(r"^[\s|:\-]+$")
_LIST_ROW_RE = re.compile(r"^\s*[-*+]\s+\**`?(?P<key>[A-Za-z][A-Za-z0-9_]*)`?\**\s*[:→-]+\s*(?P<rest>.+)$")
_TASK_SHAPED_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{7,}$")


def _is_task_shaped(cell: str, corpus: GroundTruthCorpus) -> bool:
    """Does this cell look like a task identifier?

    Either it *is* a known task id, or it is a long single-token CamelCase
    identifier -- the shape every task in this benchmark family has. The second
    branch is what makes the rule survive a renamed task set.
    """
    cell = cell.strip().strip("`*_ ")
    if not cell:
        return False
    if cell.lower() in {t.lower() for t in corpus.task_ids}:
        return True
    if not _TASK_SHAPED_RE.match(cell):
        return False
    humps = sum(1 for c in cell[1:] if c.isupper())
    return humps >= 2


def rule_lookup_tables(
    path: str, text: str, corpus: GroundTruthCorpus, cfg: GateConfig
) -> list[Finding]:
    """Tables and lists keyed by something task-shaped and valued by a file path.

    :func:`rule_task_ids` needs the corpus to know the task names. This rule
    needs nothing: it detects the *shape* of the quarantined artifact, so a
    table over renamed tasks, a held-out split the corpus was not built with,
    or a paraphrase of the same idea is still caught. Keys that map to deck
    filenames block; keys that map to some other path (source headers, docs)
    warn, because pointing at the source tree is a search shortcut rather than
    an answer key.
    """
    pattern = corpus.leak_pattern()
    findings: list[Finding] = []
    for block in _key_value_blocks(text):
        findings.extend(
            _judge_rows(block.rows, block.header, block.line, path, pattern, corpus, cfg)
        )
    return _cap(findings, cfg, "lookup_table", path)


@dataclass(frozen=True)
class _Block:
    """One contiguous key/value block: a markdown table or a definition list."""

    header: str
    line: int
    rows: tuple[tuple[str, str], ...]


def _key_value_blocks(text: str) -> list[_Block]:
    """Split ``text`` into markdown tables and definition-list runs.

    Both forms are treated identically because the leak is the mapping, not the
    markup: the quarantined artifact used a table, but a bullet list of
    ``- TaskName: path/deck.xml`` is the same answer key.
    """
    blocks: list[_Block] = []
    header = ""
    start = 1
    rows: list[tuple[str, str]] = []
    in_table = False

    def flush() -> None:
        nonlocal header, rows, in_table
        if rows:
            blocks.append(_Block(header, start, tuple(rows)))
        header, rows, in_table = "", [], False

    for line_no, raw in enumerate(text.splitlines(), start=1):
        m = _TABLE_ROW_RE.match(raw)
        if m:
            if not in_table:
                flush()
                in_table = True
                start = line_no
                header = " ".join(c.strip() for c in m.group("body").split("|"))
                continue
            if _SEPARATOR_RE.match(m.group("body")):
                continue
            cells = [c.strip() for c in m.group("body").split("|")]
            rows.append((cells[0], " ".join(cells[1:])))
            continue
        if in_table:
            flush()
        lm = _LIST_ROW_RE.match(raw)
        if lm:
            if not rows:
                start = line_no
            rows.append((lm.group("key"), lm.group("rest")))
            continue
        if rows:
            flush()
    flush()
    return blocks


def _judge_rows(
    rows: Sequence[tuple[str, str]],
    header: str,
    line: int,
    path: str,
    pattern: re.Pattern[str],
    corpus: GroundTruthCorpus,
    cfg: GateConfig,
) -> list[Finding]:
    """Score one table/list block for "task-shaped key -> artifact" rows."""
    with_deck = 0
    with_path = 0
    for key, value in rows:
        if not _is_task_shaped(key, corpus):
            continue
        if pattern.search(value):
            with_deck += 1
        elif "/" in value:
            with_path += 1
    lowered = header.lower()
    header_is_lookup = "task" in lowered and any(
        w in lowered for w in ("xml", "file", "path", "deck", "canonical", "input")
    )
    if header_is_lookup:
        return [
            Finding(
                "lookup_table",
                "error",
                f"table header {header.strip()!r} keys tasks to artifact files",
                _loc(path, line),
            )
        ]
    if with_deck >= cfg.lookup_table_rows:
        return [
            Finding(
                "lookup_table",
                "error",
                f"{with_deck} rows map a task-shaped key to a simulator artifact "
                "file: this is an answer key",
                _loc(path, line),
            )
        ]
    if with_path + with_deck >= cfg.lookup_table_rows:
        return [
            Finding(
                "lookup_table",
                "warn",
                f"{with_path + with_deck} rows map an identifier to a source path; "
                "a navigation shortcut, verify it is not task-keyed",
                _loc(path, line),
            )
        ]
    return []


_SHORTCUT_RE = re.compile(
    r"(skip (?:the )?(?:search|grep|glob|the search)"
    r"|do ?n[o']?t (?:grep|glob|search)"
    r"|already verified"
    r"|read the listed file"
    r"|canonical (?:xml|deck|input|file))",
    re.I,
)


def rule_lookup_language(
    path: str, text: str, corpus: GroundTruthCorpus, cfg: GateConfig
) -> list[Finding]:
    """Language that tells the agent to stop searching and read a known answer.

    On its own this is legitimate: efficiency is a hard constraint, so telling
    the agent not to waste greps is exactly what an adapter should do. It only
    becomes evidence when the same file also points at a specific artifact --
    which is why it is ``info`` alone and ``warn`` in company. Reported at all
    because it is the behavioural marker that makes a lookup-table finding
    immediately legible to whoever reads the report.
    """
    m = _SHORTCUT_RE.search(text)
    if not m:
        return []
    paired = corpus.leak_pattern().search(text) is not None
    return [
        Finding(
            "lookup_language",
            "warn" if paired else "info",
            f"search-suppressing instruction {m.group(0)!r}"
            + (" alongside a named simulator artifact" if paired else ""),
            _loc(path, _line_at(text, m.start())),
        )
    ]


Rule = Callable[[str, str, GroundTruthCorpus, GateConfig], list[Finding]]

#: Every rule, in report order. Name is the ``Finding.source`` prefix the rule
#: emits, and the key for :attr:`GateConfig.severity_overrides`.
ALL_RULES: tuple[tuple[str, Rule], ...] = (
    ("filename", rule_filenames),
    ("path_component", rule_path_components),
    ("task_id", rule_task_ids),
    ("blocklist", rule_blocklist),
    ("content_overlap", rule_content_overlap),
    ("numeric_leak", rule_numeric_leakage),
    ("near_miss_filename", rule_near_miss_filenames),
    ("structural_fingerprint", rule_structural_fingerprint),
    ("rare_token_overlap", rule_rare_token_overlap),
    ("lookup_table", rule_lookup_tables),
    ("lookup_language", rule_lookup_language),
)


# ---------------------------------------------------------------------------
# entry points
# ---------------------------------------------------------------------------


def check_texts(
    texts: Mapping[str, str],
    corpus: GroundTruthCorpus,
    *,
    config: GateConfig | None = None,
    rules: Sequence[tuple[str, Rule]] = ALL_RULES,
) -> HygieneReport:
    """Run every rule over ``texts`` (adapter-relative path -> content)."""
    cfg = config or GateConfig()
    report = HygieneReport(
        rules_run=tuple(name for name, _ in rules),
        corpus_summary=corpus.summary(),
    )
    for path in sorted(texts):
        text = texts[path]
        report.checked_paths.append(path)
        for _, rule in rules:
            report.findings.extend(rule(path, text, corpus, cfg))
    if cfg.severity_overrides:
        report.findings = [
            f if f.source not in cfg.severity_overrides
            else Finding(f.source, cfg.severity_overrides[f.source], f.message, f.location)
            for f in report.findings
        ]
    return report


def check_candidate(
    candidate: Any, corpus: GroundTruthCorpus, *, config: GateConfig | None = None
) -> HygieneReport:
    """Gate a :class:`~harness_evolve.core.candidate.Candidate` before any rollout.

    Duck-typed on ``.files`` rather than importing the class, so the gate stays
    usable on anything file-shaped (a materialized directory read into a dict, a
    proposer's draft edits) without a dependency edge into ``core``.
    """
    return check_texts(dict(candidate.files), corpus, config=config)
