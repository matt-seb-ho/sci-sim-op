"""What a candidate adapter must not reveal, indexed once per search run.

The corpus is the expensive half of the gate and the candidate-independent
half, so it is built once and reused for every candidate: n-gram sets, element
sequences, document frequencies and canonicalized numerics are all precomputed
here. That is what lets the gate stay inside the "free gates" band of the loop
-- it has to be cheap enough to run before any rollout is spent, or people will
move it downstream of the rollout and it will stop being a gate.

Two construction paths exist because the ground-truth tree is not always
mountable. :meth:`GroundTruthCorpus.from_ground_truth_dir` is the real one;
:meth:`GroundTruthCorpus.from_blocklist_json` reads a precomputed blocklist
(the shape emitted by the runner's contamination module) so an audit can run on
a machine with no data volume; and direct construction from parts is what tests
use.

Blocked basenames come from the simulator's own
:meth:`~harness_evolve.simulators.base.SimulatorSpec.contamination_policy`
whenever a spec is supplied, so the runtime gate (what is hidden from the agent)
and the hygiene gate (what may not appear in an adapter) cannot drift apart.
The predecessor system had them as two independent lists and the drift is
exactly how ``.geos`` dependency filenames reached a shipped adapter.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Sequence

if TYPE_CHECKING:  # pragma: no cover - typing only
    from harness_evolve.simulators.base import SimulatorSpec

#: Extensions whose *basenames* must never appear in an adapter, used when no
#: simulator spec is available. ``geos`` is the one the predecessor gate missed:
#: its regex was ``.xml``-only, so ground-truth dependency filenames
#: (``tables/time.geos``) passed through into the shipped adapter across three
#: files.
DEFAULT_LEAKY_EXTENSIONS: tuple[str, ...] = (
    "xml", "geos", "msh", "vtk", "vtu", "rst", "yaml", "yml", "hdf5", "csv",
)

#: Variant suffixes stripped when reducing a ground-truth basename to a stem.
#: ``Foo_base.xml``, ``Foo_benchmark.xml`` and ``Foo_smoke.xml`` share nearly
#: all their content, so naming any one of them leaks the family. Ordered
#: longest-first so compound suffixes strip in one pass.
VARIANT_SUFFIXES: tuple[str, ...] = (
    "_base_iterative", "_base_direct", "_iterative_base", "_direct_base",
    "_benchmark_base", "_benchmark_fim", "_smoke_base", "_smoke_fim",
    "_smoke_sequential", "_base_hybrid", "_verification", "_iterative",
    "_benchmark", "_sequential", "_direct", "_smoke", "_hybrid", "_base",
    "_fim",
)

#: Stems too generic to attribute to a particular ground truth. A candidate
#: saying "input" must not be treated as naming ``input.xml``.
GENERIC_STEMS: frozenset[str] = frozenset(
    {"base", "benchmark", "input", "inputs", "problem", "model", "smoke",
     "case", "example", "test", "main", "run", "setup", "config"}
)

#: Shortest stem worth matching on. Below this, collisions with ordinary prose
#: dominate and the near-miss rule becomes noise.
MIN_STEM_LEN = 8

#: Shortest ground-truth directory name worth flagging. Short components
#: (``src``, ``xml``, ``2d``) appear in unrelated prose.
MIN_PATH_PART_LEN = 5

#: Default n-gram order for content overlap. Eight word-tokens is long enough
#: that shared boilerplate ("run the following command to") does not trip it,
#: short enough to survive light paraphrase of a copied deck fragment.
DEFAULT_NGRAM_N = 8

#: An element appearing in at least this fraction of ground-truth decks is
#: schema boilerplate, not task-specific structure. Every GEOS deck opens
#: Problem/Solvers/Mesh/Events/..., so counting that ordering as a structural
#: match would flag every adapter that describes the file format at all.
COMMON_ELEMENT_FRACTION = 0.6

#: Structural fingerprint length, in *distinctive* (non-boilerplate) elements.
FINGERPRINT_K = 5

_NUM_RE = re.compile(
    r"""(?<![A-Za-z0-9_.])
        [-+]?
        (?:\d+\.?\d*|\.\d+)
        (?:\s*(?:[eEdD]\s*[-+]?\d+|
                \\times\s*10\s*\^?\s*\{?\s*[-+]?\d+\s*\}?|
                x\s*10\s*\^\s*[-+]?\d+))?
    """,
    re.VERBOSE,
)

_SUPERSCRIPTS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺", "0123456789-+")

#: Numbers this common carry no information about any particular ground truth.
#: Suppressing them is what keeps the numeric rule from firing on every
#: document that contains a numbered list.
TRIVIAL_NUMERICS: frozenset[str] = frozenset(
    {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "100", "1000",
     "0.5", "0.1", "0.01", "-1", "0.0", "1.0", "2.0", "3.0", "0.25", "0.75",
     "1e-06", "1e-08"}
)

_ELEMENT_RE = re.compile(r"<([A-Za-z_][A-Za-z0-9_.\-]*)")
_WORD_RE = re.compile(r"[a-z0-9_]+")


# ---------------------------------------------------------------------------
# text canonicalization
# ---------------------------------------------------------------------------


def canonicalize_number(raw: str) -> str | None:
    """Canonicalize one numeric token, or ``None`` if it does not parse.

    ``1.0e-4``, ``1E-4``, ``1.0d-4``, ``$1.0\\times10^{-4}$`` and ``1.0x10^-4``
    all reduce to the same string. Prose adapters write ground-truth values in
    whatever notation the trajectory used, so a comparison that is not
    notation-blind sees almost none of them.
    """
    s = unicodedata.normalize("NFKC", raw).translate(_SUPERSCRIPTS)
    s = s.strip().strip("$").strip()
    s = re.sub(r"\\times\s*10\s*\^?\s*\{?\s*([-+]?\d+)\s*\}?", r"e\1", s)
    s = re.sub(r"[xX]\s*10\s*\^\s*\{?\s*([-+]?\d+)\s*\}?", r"e\1", s)
    s = re.sub(r"[DdE]", "e", s)
    s = re.sub(r"\s+", "", s)
    try:
        val = float(s)
    except ValueError:
        return None
    if val == 0:
        return "0"
    return f"{val:.6g}"


def canonical_numerics(text: str) -> set[str]:
    """Every canonicalized, non-trivial numeric literal in ``text``.

    Bare integers up to three digits are dropped wholesale: section numbers,
    step counts and mesh sizes are indistinguishable from them, and a rule that
    fires on ``100`` is a rule people route around.
    """
    text = unicodedata.normalize("NFKC", text).translate(_SUPERSCRIPTS)
    out: set[str] = set()
    for m in _NUM_RE.finditer(text):
        raw = m.group(0)
        if raw.strip() in TRIVIAL_NUMERICS:
            continue
        canon = canonicalize_number(raw)
        if canon is None or canon in TRIVIAL_NUMERICS:
            continue
        if re.fullmatch(r"-?\d{1,3}", canon):
            continue
        out.add(canon)
    return out


def word_tokens(text: str) -> list[str]:
    """Lowercased word tokens, NFKC-normalized so unicode look-alikes collapse."""
    return _WORD_RE.findall(unicodedata.normalize("NFKC", text).lower())


def ngram_set(tokens: Sequence[str], n: int) -> frozenset[tuple[str, ...]]:
    """Distinct ``n``-grams of ``tokens``."""
    if len(tokens) < n:
        return frozenset()
    return frozenset(tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1))


def element_sequence(text: str) -> tuple[str, ...]:
    """Ordered element names appearing in ``text``.

    Deliberately regex-based rather than an XML parse: the input is prose that
    *mentions* markup, so it is never well-formed, and the sequence is all the
    structural fingerprint needs.
    """
    return tuple(m.group(1) for m in _ELEMENT_RE.finditer(text))


def stem_keys(filename: str) -> set[str]:
    """Variant-stripped stems for a filename, for near-miss matching.

    ``PoroElastic_Mandel_base.xml`` yields ``poroelastic_mandel_base`` and
    ``poroelastic_mandel``, so an adapter that writes ``PoroElastic_Mandel_*``
    with no extension -- which the extension-based rule cannot see -- still
    matches. Stems shorter than :data:`MIN_STEM_LEN` or in
    :data:`GENERIC_STEMS` are dropped.
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
    return {k for k in keys if len(k) >= MIN_STEM_LEN and k not in GENERIC_STEMS}


# ---------------------------------------------------------------------------
# corpus
# ---------------------------------------------------------------------------


@dataclass
class GroundTruthCorpus:
    """Everything a candidate must not reveal, plus the indexes to detect it.

    Primary fields are supplied by a builder or directly by a caller; derived
    fields are computed by :meth:`finalize`, which ``__post_init__`` calls. A
    caller that mutates a primary field afterwards must call :meth:`finalize`
    again.
    """

    #: Lowercased basenames of files hidden from the agent (the runtime gate's
    #: own blocklist, including variant siblings).
    blocked_basenames: set[str] = field(default_factory=set)
    #: Lowercased ground-truth directory components (``poromechanics``). These
    #: survive a basename-only redaction and still name the physics family.
    blocked_path_parts: set[str] = field(default_factory=set)
    #: Evaluation task identifiers. Any table keyed by these is a lookup table.
    task_ids: set[str] = field(default_factory=set)
    #: Ground-truth deck text, keyed by a human-readable reference.
    deck_texts: dict[str, str] = field(default_factory=dict)
    #: Canonicalized numeric literals. Populated from ``deck_texts`` when empty.
    numeric_literals: set[str] = field(default_factory=set)
    #: Extensions treated as simulator artifacts, from the simulator spec.
    leaky_extensions: tuple[str, ...] = DEFAULT_LEAKY_EXTENSIONS
    #: N-gram order; a corpus property because the reference index is built here.
    ngram_n: int = DEFAULT_NGRAM_N

    # -- derived ---------------------------------------------------------
    filename_stems: set[str] = field(init=False, default_factory=set)
    deck_ngrams: dict[str, frozenset[tuple[str, ...]]] = field(
        init=False, default_factory=dict
    )
    deck_fingerprints: dict[str, frozenset[tuple[str, ...]]] = field(
        init=False, default_factory=dict
    )
    common_elements: frozenset[str] = field(init=False, default=frozenset())
    token_df: dict[str, int] = field(init=False, default_factory=dict)
    n_decks: int = field(init=False, default=0)

    def __post_init__(self) -> None:
        self.finalize()

    # -- indexing --------------------------------------------------------
    def finalize(self) -> "GroundTruthCorpus":
        """(Re)build every derived index from the primary fields."""
        self.blocked_basenames = {b.lower() for b in self.blocked_basenames if b}
        self.blocked_path_parts = {
            p.lower() for p in self.blocked_path_parts
            if p and len(p) >= MIN_PATH_PART_LEN
        }
        self.filename_stems = set()
        for name in self.blocked_basenames:
            self.filename_stems |= stem_keys(name)

        self.n_decks = len(self.deck_texts)
        self.deck_ngrams = {}
        self.token_df = {}
        element_df: dict[str, int] = {}
        sequences: dict[str, tuple[str, ...]] = {}
        for key, text in self.deck_texts.items():
            toks = word_tokens(text)
            self.deck_ngrams[key] = ngram_set(toks, self.ngram_n)
            for tok in set(toks):
                self.token_df[tok] = self.token_df.get(tok, 0) + 1
            seq = element_sequence(text)
            sequences[key] = seq
            for el in set(seq):
                element_df[el] = element_df.get(el, 0) + 1

        threshold = max(2, math.ceil(COMMON_ELEMENT_FRACTION * self.n_decks))
        self.common_elements = frozenset(
            el for el, df in element_df.items() if df >= threshold
        )
        self.deck_fingerprints = {
            key: self._fingerprint(seq) for key, seq in sequences.items()
        }

        if not self.numeric_literals and self.deck_texts:
            for text in self.deck_texts.values():
                self.numeric_literals |= canonical_numerics(text)
        return self

    def _fingerprint(self, seq: Sequence[str]) -> frozenset[tuple[str, ...]]:
        distinctive = [el for el in seq if el not in self.common_elements]
        return ngram_set(distinctive, FINGERPRINT_K)

    def fingerprint(self, text: str) -> frozenset[tuple[str, ...]]:
        """Structural fingerprint of arbitrary text, comparable to a deck's."""
        return self._fingerprint(element_sequence(text))

    # -- queries ---------------------------------------------------------
    def idf(self, token: str) -> float:
        """Inverse document frequency of ``token`` across ground-truth decks.

        A rare identifier shared with ground truth is far more damning than a
        common one: every deck contains ``name`` and ``value``, but only one
        contains ``kgdedgebased``. Raw n-gram counts weight those equally,
        which is why overlap alone under-reports paraphrased leaks.
        """
        if not self.n_decks:
            return 0.0
        df = self.token_df.get(token, 0)
        if df == 0:
            return 0.0
        return math.log(self.n_decks / df) + 1.0

    def leak_pattern(self) -> re.Pattern[str]:
        """Regex matching any simulator-artifact filename, over every leaky extension."""
        exts = "|".join(re.escape(e) for e in self.leaky_extensions)
        return re.compile(
            rf"\b([A-Za-z0-9_][A-Za-z0-9_.\-]*\.(?:{exts}))\b", re.IGNORECASE
        )

    @property
    def is_empty(self) -> bool:
        """True when nothing was loaded -- a gate run against this proves little."""
        return not (
            self.blocked_basenames
            or self.task_ids
            or self.deck_texts
            or self.blocked_path_parts
        )

    def summary(self) -> dict[str, int]:
        """Counts per index, for logging what a gate run actually had to work with."""
        return {
            "blocked_basenames": len(self.blocked_basenames),
            "blocked_path_parts": len(self.blocked_path_parts),
            "task_ids": len(self.task_ids),
            "decks": len(self.deck_texts),
            "filename_stems": len(self.filename_stems),
            "numeric_literals": len(self.numeric_literals),
        }

    # -- builders --------------------------------------------------------
    @classmethod
    def from_ground_truth_dir(
        cls,
        gt_dir: Path,
        *,
        simulator: "SimulatorSpec | None" = None,
        tasks: Sequence[str] | None = None,
        ngram_n: int = DEFAULT_NGRAM_N,
        deck_extensions: Sequence[str] | None = None,
    ) -> "GroundTruthCorpus":
        """Build from a ground-truth tree laid out as ``<gt_dir>/<task_id>/...``.

        When ``simulator`` is given its contamination policy supplies the
        blocked basenames, so the hygiene gate blocks exactly what the runtime
        gate hides. Without a spec the corpus falls back to the files actually
        on disk, which misses variant siblings.
        """
        gt_dir = Path(gt_dir)
        leaky = tuple(simulator.leaky_extensions) if simulator else DEFAULT_LEAKY_EXTENSIONS
        deck_exts = tuple(
            e.lower().lstrip(".")
            for e in (deck_extensions if deck_extensions is not None else leaky)
        )
        corpus = cls(leaky_extensions=leaky, ngram_n=ngram_n)

        if tasks is not None:
            task_dirs = [gt_dir / t for t in tasks]
        elif gt_dir.is_dir():
            task_dirs = sorted(p for p in gt_dir.iterdir() if p.is_dir())
        else:
            task_dirs = []

        for td in task_dirs:
            if not td.is_dir():
                continue
            corpus.task_ids.add(td.name)
            if simulator is not None:
                policy = simulator.contamination_policy(td.name, gt_dir)
                corpus.blocked_basenames |= {b.lower() for b in policy.blocked_basenames}
                for p in policy.blocked_paths:
                    corpus.blocked_basenames.add(Path(p).name.lower())
                    corpus.blocked_path_parts |= {
                        part.lower() for part in Path(p).parts[:-1]
                    }
            for f in sorted(td.rglob("*")):
                if not f.is_file():
                    continue
                corpus.blocked_basenames.add(f.name.lower())
                corpus.blocked_path_parts |= {
                    part.lower() for part in f.relative_to(gt_dir).parts[:-1]
                }
                if f.suffix.lower().lstrip(".") in deck_exts:
                    try:
                        corpus.deck_texts[f.relative_to(gt_dir).as_posix()] = (
                            f.read_text(errors="replace")
                        )
                    except OSError:
                        continue
        return corpus.finalize()

    @classmethod
    def from_blocklist_json(
        cls,
        path: Path,
        *,
        include_train: bool = True,
        leaky_extensions: Sequence[str] | None = None,
        ngram_n: int = DEFAULT_NGRAM_N,
    ) -> "GroundTruthCorpus":
        """Build from a precomputed blocklist emitted by the contamination module.

        Recognized keys: ``union_xml`` / ``per_task_xml`` /
        ``train_per_task_xml`` (basenames per task) and ``union_rst_relpaths``
        (source-relative paths). This path exists so an adapter can be audited
        on a machine with no ground-truth volume mounted -- which is the normal
        case for a retro-audit, and the case in which the predecessor's leaks
        went unnoticed for three versions.

        Content, numeric and structural rules are inert against a corpus built
        this way: it carries names, not deck text.
        """
        data = json.loads(Path(path).read_text())
        corpus = cls(
            leaky_extensions=tuple(leaky_extensions or DEFAULT_LEAKY_EXTENSIONS),
            ngram_n=ngram_n,
        )
        corpus.blocked_basenames |= {str(x).lower() for x in data.get("union_xml", [])}
        for key in ("per_task_xml", "train_per_task_xml"):
            if key == "train_per_task_xml" and not include_train:
                continue
            table = data.get(key) or {}
            if not isinstance(table, dict):
                continue
            for task, names in table.items():
                corpus.task_ids.add(str(task))
                corpus.blocked_basenames |= {str(n).lower() for n in names or ()}
        for rel in data.get("union_rst_relpaths", []) or ():
            p = Path(str(rel))
            corpus.blocked_basenames.add(p.name.lower())
            corpus.blocked_path_parts |= {part.lower() for part in p.parts[:-1]}
        return corpus.finalize()

    def add_decks(self, decks: dict[str, str]) -> "GroundTruthCorpus":
        """Fold in ground-truth deck text and rebuild the content indexes."""
        self.deck_texts.update(decks)
        return self.finalize()

    def extend_from_policies(
        self, policies: Iterable[Any], tasks: Iterable[str] = ()
    ) -> "GroundTruthCorpus":
        """Fold in extra :class:`ContaminationPolicy` objects and task ids."""
        for policy in policies:
            self.blocked_basenames |= {b.lower() for b in policy.blocked_basenames}
            for p in policy.blocked_paths:
                self.blocked_basenames.add(Path(p).name.lower())
                self.blocked_path_parts |= {part.lower() for part in Path(p).parts[:-1]}
        self.task_ids |= {str(t) for t in tasks}
        return self.finalize()
