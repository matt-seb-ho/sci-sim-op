"""Trajectory mining: raw agent logs -> structured, proposer-consumable features.

Ported and generalised from ``repo3/scripts/bottleneck/extract.py``. Two things
changed in the port, both forced by what the evidence layer is now for:

1. **Simulator-specific counters became configuration.** The original counted
   ``/geos_lib`` reads, ``.rst`` reads, ``xmllint`` invocations and ``geosx``
   runs by hardcoded string. Those are exactly the quantities that stop meaning
   anything on OpenFOAM or LAMMPS, so they are now :class:`MiningConfig`
   fields with generic names (reference-library prefixes, doc extensions,
   artifact extensions, validator commands).

2. **Observations became first class.** The original mined *actions* only --
   tool names, file paths, edit churn. It never looked at a single tool result,
   which is why the downstream proposer saw no errors and no validator output.
   Feedback events (errored tool results, stop-hook blocks, injected retry
   prompts) are now extracted with their position in the action stream, because
   position is what makes "did the agent act on this" answerable at all. That
   stream is the input to :mod:`harness_evolve.evidence.efc`.

Nothing here raises on bad input. A missing ``events.jsonl`` is the normal case
for a mock runner and for a rollout that died before the harness wrote
anything; degrading to a populated "no data" result keeps the corpus renderable
instead of taking the search loop down with it.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from harness_evolve.simulators.base import Diagnosis

__all__ = [
    "ExcerptBlock",
    "FeedbackEvent",
    "MiningConfig",
    "ToolCall",
    "TrajectoryFeatures",
    "TurnExcerpt",
    "diagnosis_from_tree",
    "extract_entities",
    "mine_trajectory",
    "per_section",
    "render_excerpt",
    "section_scores",
    "trajectory_excerpt",
    "worst_subtrees",
]


# --------------------------------------------------------------------------
# structural diagnosis: tree detail -> Diagnosis
# --------------------------------------------------------------------------


def _flatten(node: Any, path: str = "") -> list[dict[str, Any]]:
    """Yield ``{"path", "node"}`` for every node of a scoring tree.

    Tolerant of missing ``tag`` keys: the original indexed ``node['tag']``
    directly and died on any detail blob whose root came back partially
    populated, which is precisely when you most want a diagnosis.
    """
    if not isinstance(node, dict):
        return []
    here = f"{path}/{node.get('tag', '?')}"
    name = node.get("name") or ""
    if name:
        here = f"{here}[{name}]"
    out = [{"path": here, "node": node}]
    for child in node.get("children") or []:
        out.extend(_flatten(child, here))
    return out


def worst_subtrees(detail: Mapping[str, Any] | None, k: int = 8) -> list[dict[str, Any]]:
    """Top-``k`` subtrees by impact ``= (1 - score) * (n_gt_children + 1)``.

    Impact rather than score because a 0.0 on a one-child block is noise while
    a 0.6 on a forty-child block is the whole deficit. Leaves are skipped: a
    single wrong element is reported through the missing/extra element summary,
    which says more per character than a subtree row would.
    """
    if not detail:
        return []
    scored: list[dict[str, Any]] = []
    for entry in _flatten(detail):
        n = entry["node"]
        size = (n.get("n_gt_children") or 0) + 1
        if size <= 1:
            continue
        score = float(n.get("score", 1.0) or 0.0)
        impact = (1.0 - score) * size
        if impact <= 0:
            continue
        n_gt = int(n.get("n_gt_children") or 0)
        n_matched = int(n.get("n_matched") or 0)
        scored.append(
            {
                "path": entry["path"],
                "score": round(score, 4),
                "attr_score": round(float(n.get("attr_score", 1.0) or 0.0), 4),
                "n_gt_children": n_gt,
                "n_matched": n_matched,
                "n_extra": int(n.get("n_extra") or 0),
                "children_score": round(float(n.get("children_score", 1.0) or 0.0), 4),
                "impact": round(impact, 4),
                "missing_child_count": max(0, n_gt - n_matched),
            }
        )
    scored.sort(key=lambda x: x["impact"], reverse=True)
    return scored[:k]


def per_section(detail: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Per-top-level-section score plus its match counts."""
    out: dict[str, dict[str, Any]] = {}
    for child in (detail or {}).get("children") or []:
        if not isinstance(child, dict):
            continue
        out[str(child.get("tag", "?"))] = {
            "score": round(float(child.get("score", 1.0) or 0.0), 4),
            "n_gt_children": int(child.get("n_gt_children") or 0),
            "n_matched": int(child.get("n_matched") or 0),
            "n_extra": int(child.get("n_extra") or 0),
        }
    return out


def section_scores(detail: Mapping[str, Any] | None) -> dict[str, float]:
    """Section name -> score, the shape :class:`Diagnosis` stores."""
    return {k: float(v["score"]) for k, v in per_section(detail).items()}


def diagnosis_from_tree(
    detail: Mapping[str, Any] | None,
    *,
    gt_element_types: Sequence[str] | Mapping[str, Any] = (),
    gen_element_types: Sequence[str] | Mapping[str, Any] = (),
    category: str | None = None,
    k_subtrees: int = 8,
) -> Diagnosis:
    """Assemble a :class:`Diagnosis` from a tree-similarity detail blob.

    Offered here so any simulator whose scorer produces a recursive
    ``{tag, score, n_gt_children, n_matched, children}`` structure gets the
    mining for free rather than reimplementing it per plugin.

    ``Diagnosis.section_scores`` is typed ``dict[str, float]``, so the per
    section match counts have nowhere to live; they are folded into ``notes``
    for the weakest sections rather than dropped, since "0.4 because 2 of 9
    children matched" and "0.4 because attributes are wrong" call for different
    proposals.
    """
    sections = per_section(detail)
    gt = set(gt_element_types)
    gen = set(gen_element_types)
    notes: list[str] = []
    for name, stat in sorted(sections.items(), key=lambda kv: kv[1]["score"])[:3]:
        notes.append(
            f"{name}: {stat['n_matched']}/{stat['n_gt_children']} children matched, "
            f"{stat['n_extra']} extra"
        )
    return Diagnosis(
        section_scores={k: float(v["score"]) for k, v in sections.items()},
        worst_subtrees=worst_subtrees(detail, k=k_subtrees),
        missing_elements=sorted(gt - gen),
        extra_elements=sorted(gen - gt),
        n_extra=int((detail or {}).get("n_extra") or 0),
        category=category,
        notes=notes,
    )


# --------------------------------------------------------------------------
# entity extraction
# --------------------------------------------------------------------------

# A feedback message is *informative* when a reader could point at the thing it
# is complaining about. These patterns are the observable proxy for "names a
# locatable entity": quoted identifiers, markup tags, attribute keys, paths,
# XPath-ish locations, and multi-hump CamelCase (which in every simulator deck
# format we handle is how element and solver type names are spelled).
_ENTITY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"['\"`]([A-Za-z_][\w./:\-]{2,63})['\"`]"),
    re.compile(r"</?([A-Za-z_][\w.\-]{2,63})\s*/?>"),
    re.compile(r"\b([A-Za-z_]\w{2,63})\s*=\s*['\"]"),
    re.compile(r"\b((?:[\w\-]+/)*[\w\-]+\.[A-Za-z]{1,6})\b"),
    re.compile(r"((?:/[A-Za-z_][\w.\-]*){2,})"),
    re.compile(r"\b([A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+)\b"),
)

# Words that match the CamelCase pattern but locate nothing: they are how
# harnesses and runtimes label the *kind* of failure, not its subject.
_GENERIC_TOKENS = frozenset(
    {
        "stacktrace", "runtimeerror", "valueerror", "typeerror", "keyerror",
        "oserror", "filenotfound", "filenotfounderror", "timeouterror",
        "notimplemented", "notimplementederror", "assertionerror",
        "parseerror", "traceback", "exitcode", "returncode", "stdout", "stderr",
    }
)


def extract_entities(text: str, limit: int = 12) -> tuple[str, ...]:
    """Locatable entities named by a feedback message, normalised and deduped.

    Deliberately *not* a length or a keyword count. A 4 kB stack trace that
    never names the offending element is uninformative to an agent that has to
    decide what to edit next; a twelve-character "unknown attribute 'logLevl'"
    is maximally informative. Capped at ``limit`` so a validator dump that
    enumerates every valid attribute does not read as twenty separate hints.
    """
    if not text:
        return ()
    found: list[str] = []
    seen: set[str] = set()
    for pattern in _ENTITY_PATTERNS:
        for match in pattern.finditer(text):
            token = match.group(1).strip().strip(".,;:")
            key = token.lower()
            if len(key) < 3 or key in _GENERIC_TOKENS or key in seen:
                continue
            seen.add(key)
            found.append(token)
            if len(found) >= limit:
                return tuple(found)
    return tuple(found)


# --------------------------------------------------------------------------
# event-stream parsing
# --------------------------------------------------------------------------

# Stop-hook blocks reach the agent as an ordinary user turn, so the only thing
# separating them from a task prompt in the stream is the wording the hook
# emits. Matching on "blocked by ... hook" covers repo3's verify_outputs
# phrasing without hardcoding that hook's name.
_HOOK_MARKER_RE = re.compile(r"blocked by[^\n]{0,60}hook|stop[ _-]?hook|hook feedback", re.I)

_ARG_TARGET_KEYS = ("file_path", "path", "notebook_path", "pattern", "command", "url", "query")
_ARG_TEXT_KEYS = (
    "file_path", "path", "notebook_path", "pattern", "command", "url", "query",
    "old_string", "new_string", "content", "prompt", "description",
)
_MAX_SEARCHABLE = 4000


@dataclass(frozen=True)
class MiningConfig:
    """Which file-shape counters to compute, so the miner stays simulator-agnostic.

    Defaults are generic on purpose. A GEOS caller passes
    ``library_prefixes=("/geos_lib",)``, ``artifact_extensions=("xml",)``,
    ``validator_commands=("geosx", "xmllint")``; an OpenFOAM caller passes its
    own. Nothing downstream branches on simulator identity.
    """

    artifact_extensions: tuple[str, ...] = ("xml", "yaml", "yml", "json", "in", "foam")
    doc_extensions: tuple[str, ...] = ("rst", "md", "txt")
    library_prefixes: tuple[str, ...] = ()
    validator_commands: tuple[str, ...] = ()
    tail_turns: int = 10


@dataclass(frozen=True)
class ToolCall:
    """One tool invocation, positioned in the global step stream.

    ``index`` is what makes "the action after this feedback" a well-defined
    question; ``arg_digest`` is what makes "the same action again" answerable
    without keeping the full argument blob around.
    """

    index: int
    turn: int
    name: str
    target: str = ""
    tool_use_id: str = ""
    arg_digest: str = ""
    searchable: str = ""

    def mentions(self, entity: str) -> bool:
        """Whether this call touches ``entity`` by name or by path basename."""
        needle = entity.lower()
        if not needle:
            return False
        if needle in self.searchable:
            return True
        base = needle.rsplit("/", 1)[-1]
        return len(base) >= 3 and base in self.searchable


@dataclass(frozen=True)
class FeedbackEvent:
    """One thing the environment told the agent, positioned in the step stream.

    ``source`` distinguishes what produced it, because the four EFC properties
    behave very differently by source: a tool error is usually valid and rarely
    redundant, a stop-hook block is usually informative but arrives too late to
    be retained, an injected retry prompt is neither.
    """

    index: int
    turn: int
    source: str
    text: str
    entities: tuple[str, ...] = ()
    category: str = ""
    tool_name: str = ""

    @property
    def names_entity(self) -> bool:
        return bool(self.entities)

    def preview(self, n: int = 160) -> str:
        flat = " ".join(self.text.split())
        return flat[:n] + ("…" if len(flat) > n else "")


@dataclass
class TrajectoryFeatures:
    """Structured view of one rollout's event stream.

    ``available=False`` with a populated ``notes`` is the missing-data result:
    every numeric field is present and zero, so callers render and arithmetic
    over these without a special case.
    """

    available: bool = False
    source: str = ""
    n_turns: int = 0
    n_assistant_msgs: int = 0
    n_thinking_blocks: int = 0
    n_tool_uses: int = 0
    n_tool_results: int = 0
    n_tool_errors: int = 0
    tool_counts: dict[str, int] = field(default_factory=dict)
    tool_error_counts: dict[str, int] = field(default_factory=dict)
    files_read: list[str] = field(default_factory=list)
    n_unique_files_read: int = 0
    n_re_read_files: int = 0
    library_reads: int = 0
    doc_reads: int = 0
    n_artifact_writes: int = 0
    n_artifact_edits: int = 0
    most_edited: list[tuple[str, int]] = field(default_factory=list)
    validator_invocations: int = 0
    top_grep_queries: list[str] = field(default_factory=list)
    top_glob_patterns: list[str] = field(default_factory=list)
    n_grep: int = 0
    n_glob: int = 0
    n_hook_blocks: int = 0
    hook_reason_categories: dict[str, int] = field(default_factory=dict)
    max_hook_retries: int = 0
    wall_seconds: float = 0.0
    output_tokens: float = 0.0
    calls: list[ToolCall] = field(default_factory=list)
    feedback: list[FeedbackEvent] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def next_call_after(self, index: int) -> ToolCall | None:
        """First action taken after step ``index``, or None if the run ended."""
        for call in self.calls:
            if call.index > index:
                return call
        return None

    def prev_call_before(self, index: int) -> ToolCall | None:
        """Last action taken before step ``index``, or None if none preceded it."""
        prev: ToolCall | None = None
        for call in self.calls:
            if call.index >= index:
                break
            prev = call
        return prev

    def calls_after(self, index: int, window: int) -> list[ToolCall]:
        """Up to ``window`` actions taken after step ``index``."""
        out = [c for c in self.calls if c.index > index]
        return out[:window]

    def render(self, max_items: int = 6) -> str:
        """Compact proposer-facing summary of the mined features."""
        if not self.available:
            return "trajectory: unavailable (" + "; ".join(self.notes or ["no reason recorded"]) + ")"
        tools = ", ".join(
            f"{n}x{c}" for n, c in sorted(self.tool_counts.items(), key=lambda kv: -kv[1])[:max_items]
        )
        lines = [
            f"turns={self.n_turns} tool_calls={self.n_tool_uses} "
            f"tool_errors={self.n_tool_errors} thinking={self.n_thinking_blocks} "
            f"wall={self.wall_seconds:.0f}s",
            f"tools: {tools or '(none)'}",
            f"files: {self.n_unique_files_read} read ({self.n_re_read_files} re-read), "
            f"{self.library_reads} library, {self.doc_reads} doc; "
            f"artifact writes={self.n_artifact_writes} edits={self.n_artifact_edits}",
        ]
        if self.most_edited:
            lines.append(
                "most edited: "
                + ", ".join(f"{f} x{c}" for f, c in self.most_edited[:3])
            )
        if self.n_hook_blocks or self.hook_reason_categories:
            cats = ", ".join(f"{k}={v}" for k, v in sorted(self.hook_reason_categories.items()))
            lines.append(
                f"stop-hook: {self.n_hook_blocks} blocks, max_retries={self.max_hook_retries}"
                + (f" [{cats}]" if cats else "")
            )
        if self.top_grep_queries:
            lines.append("searches: " + ", ".join(self.top_grep_queries[:max_items]))
        if self.notes:
            lines.append("notes: " + "; ".join(self.notes[:3]))
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "source": self.source,
            "n_turns": self.n_turns,
            "n_tool_uses": self.n_tool_uses,
            "n_tool_errors": self.n_tool_errors,
            "tool_counts": dict(self.tool_counts),
            "tool_error_counts": dict(self.tool_error_counts),
            "n_unique_files_read": self.n_unique_files_read,
            "n_re_read_files": self.n_re_read_files,
            "n_artifact_writes": self.n_artifact_writes,
            "n_artifact_edits": self.n_artifact_edits,
            "n_hook_blocks": self.n_hook_blocks,
            "hook_reason_categories": dict(self.hook_reason_categories),
            "wall_seconds": self.wall_seconds,
            "n_feedback_events": len(self.feedback),
            "notes": list(self.notes),
        }


def _iter_events(path: Path) -> Iterator[dict[str, Any]]:
    """Yield JSON objects from a JSONL stream, skipping anything unparseable.

    A truncated final line is the normal shape of a killed rollout, and that is
    exactly the rollout whose trajectory you want to look at.
    """
    try:
        handle = path.open(encoding="utf-8", errors="replace")
    except OSError:
        return
    with handle as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                yield event


def _blocks(event: Mapping[str, Any]) -> list[Any]:
    message = event.get("message")
    if isinstance(message, Mapping):
        content = message.get("content")
    else:
        content = event.get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return list(content) if isinstance(content, list) else []


def _result_text(block: Mapping[str, Any]) -> str:
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, Mapping) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    return "" if content is None else str(content)


def _target_of(args: Mapping[str, Any]) -> str:
    for key in _ARG_TARGET_KEYS:
        value = args.get(key)
        if isinstance(value, str) and value:
            return value[:200]
    return ""


def _searchable_of(name: str, args: Mapping[str, Any]) -> str:
    parts = [name]
    for key in _ARG_TEXT_KEYS:
        value = args.get(key)
        if isinstance(value, str):
            parts.append(value)
    return " ".join(parts).lower()[:_MAX_SEARCHABLE]


def _digest(args: Any) -> str:
    try:
        blob = json.dumps(args, sort_keys=True, default=str)
    except (TypeError, ValueError):
        blob = repr(args)
    return hashlib.sha1(blob.encode("utf-8", "replace")).hexdigest()[:12]


def _parse_ts(event: Mapping[str, Any]) -> float | None:
    for key in ("timestamp", "ts", "ts_utc", "time"):
        raw = event.get(key)
        if isinstance(raw, (int, float)):
            return float(raw)
        if isinstance(raw, str):
            try:
                return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
            except ValueError:
                continue
    return None


def _read_hook_events(path: Path) -> tuple[int, dict[str, int], int]:
    """Blocks, reason-category histogram, and max retry depth from a hook log.

    The stop hook writes its own JSONL (``decision``/``reason_category``/
    ``retries_so_far``) independently of the agent transcript. It carries no
    step index, so it feeds the feature summary rather than the EFC stream --
    the same blocks appear positioned in ``events.jsonl`` as injected turns.
    """
    blocks = 0
    categories: Counter[str] = Counter()
    max_retries = 0
    for event in _iter_events(path):
        decision = str(event.get("decision") or "")
        category = str(event.get("reason_category") or "")
        if category:
            categories[category] += 1
        if decision == "block":
            blocks += 1
        try:
            max_retries = max(max_retries, int(event.get("retries_so_far") or 0))
        except (TypeError, ValueError):
            pass
    return blocks, dict(categories), max_retries


def mine_trajectory(
    events_path: str | Path | None,
    *,
    hook_events_path: str | Path | None = None,
    config: MiningConfig | None = None,
) -> TrajectoryFeatures:
    """Walk an ``events.jsonl`` stream into :class:`TrajectoryFeatures`.

    Never raises. A missing, unreadable, or empty stream returns
    ``available=False`` with the reason in ``notes``.
    """
    cfg = config or MiningConfig()
    feats = TrajectoryFeatures(source=str(events_path or ""))

    if hook_events_path is not None:
        hook_path = Path(hook_events_path)
        if hook_path.exists():
            blocks, categories, retries = _read_hook_events(hook_path)
            feats.n_hook_blocks = blocks
            feats.hook_reason_categories = categories
            feats.max_hook_retries = retries
        else:
            feats.notes.append(f"hook event log missing: {hook_path}")

    if events_path is None:
        feats.notes.append("no events path recorded for this rollout")
        return feats
    path = Path(events_path)
    if not path.exists():
        feats.notes.append(f"events file missing: {path}")
        return feats

    tools: Counter[str] = Counter()
    tool_errors: Counter[str] = Counter()
    read_targets: Counter[str] = Counter()
    edits: Counter[str] = Counter()
    grep_queries: Counter[str] = Counter()
    glob_patterns: Counter[str] = Counter()
    files_read: list[str] = []
    id_to_name: dict[str, str] = {}
    first_ts: float | None = None
    last_ts: float | None = None
    step = 0
    n_events = 0

    artifact_re = re.compile(
        r"\.(?:" + "|".join(re.escape(e) for e in cfg.artifact_extensions) + r")$", re.I
    ) if cfg.artifact_extensions else None
    doc_re = re.compile(
        r"\.(?:" + "|".join(re.escape(e) for e in cfg.doc_extensions) + r")$", re.I
    ) if cfg.doc_extensions else None

    for event in _iter_events(path):
        n_events += 1
        ts = _parse_ts(event)
        if ts is not None:
            first_ts = ts if first_ts is None else min(first_ts, ts)
            last_ts = ts if last_ts is None else max(last_ts, ts)
        etype = event.get("type")

        if etype == "result":
            duration = event.get("duration_ms")
            if isinstance(duration, (int, float)) and duration > 0:
                feats.wall_seconds = max(feats.wall_seconds, float(duration) / 1000.0)
            usage = event.get("usage")
            if isinstance(usage, Mapping):
                out = usage.get("output_tokens")
                if isinstance(out, (int, float)):
                    feats.output_tokens += float(out)
            continue

        if etype == "assistant":
            feats.n_turns += 1
            real = False
            usage = (event.get("message") or {}).get("usage") if isinstance(event.get("message"), Mapping) else None
            if isinstance(usage, Mapping) and isinstance(usage.get("output_tokens"), (int, float)):
                feats.output_tokens += float(usage["output_tokens"])
            for block in _blocks(event):
                if not isinstance(block, Mapping):
                    continue
                btype = block.get("type")
                if btype == "thinking":
                    feats.n_thinking_blocks += 1
                    real = True
                elif btype == "text":
                    real = True
                elif btype == "tool_use":
                    real = True
                    feats.n_tool_uses += 1
                    name = str(block.get("name") or "?")
                    tools[name] += 1
                    args = block.get("input")
                    args = args if isinstance(args, Mapping) else {}
                    use_id = str(block.get("id") or "")
                    if use_id:
                        id_to_name[use_id] = name
                    target = _target_of(args)
                    feats.calls.append(
                        ToolCall(
                            index=step,
                            turn=feats.n_turns,
                            name=name,
                            target=target,
                            tool_use_id=use_id,
                            arg_digest=_digest(args),
                            searchable=_searchable_of(name, args),
                        )
                    )
                    step += 1
                    _account_call(
                        name, args, target,
                        files_read, read_targets, edits, grep_queries, glob_patterns,
                        feats, cfg, artifact_re, doc_re,
                    )
            if real:
                feats.n_assistant_msgs += 1
            continue

        if etype in ("user", "human", None):
            feats.n_turns += 1
            for block in _blocks(event):
                if not isinstance(block, Mapping):
                    continue
                btype = block.get("type")
                if btype == "tool_result":
                    feats.n_tool_results += 1
                    text = _result_text(block)
                    name = id_to_name.get(str(block.get("tool_use_id") or ""), "?")
                    if _is_error_result(block, text):
                        feats.n_tool_errors += 1
                        tool_errors[name] += 1
                        feats.feedback.append(
                            FeedbackEvent(
                                index=step,
                                turn=feats.n_turns,
                                source="tool_error",
                                text=text,
                                entities=extract_entities(text),
                                category="tool_error",
                                tool_name=name,
                            )
                        )
                    step += 1
                elif btype == "text":
                    text = str(block.get("text") or "")
                    if not text.strip():
                        continue
                    is_hook = bool(_HOOK_MARKER_RE.search(text))
                    feats.feedback.append(
                        FeedbackEvent(
                            index=step,
                            turn=feats.n_turns,
                            source="hook" if is_hook else "injected",
                            text=text,
                            entities=extract_entities(text),
                            category="stop_hook_block" if is_hook else "injected_message",
                        )
                    )
                    step += 1

    if n_events == 0:
        feats.notes.append(f"events file empty or unparseable: {path}")
        return feats

    feats.available = True
    feats.tool_counts = dict(tools)
    feats.tool_error_counts = dict(tool_errors)
    feats.files_read = files_read
    feats.n_unique_files_read = len(read_targets)
    feats.n_re_read_files = sum(1 for _, c in read_targets.items() if c >= 2)
    feats.most_edited = edits.most_common(3)
    feats.top_grep_queries = [q for q, _ in grep_queries.most_common(8)]
    feats.top_glob_patterns = [q for q, _ in glob_patterns.most_common(8)]
    feats.n_grep = sum(grep_queries.values())
    feats.n_glob = sum(glob_patterns.values())
    if not feats.wall_seconds and first_ts is not None and last_ts is not None:
        feats.wall_seconds = max(0.0, last_ts - first_ts)
    if not feats.wall_seconds:
        feats.notes.append("no wall-clock signal in stream (no result event, no timestamps)")
    if not feats.feedback:
        feats.notes.append("no feedback events found: no tool errors, hook blocks, or injected turns")
    return feats


def _is_error_result(block: Mapping[str, Any], text: str) -> bool:
    """Whether a tool_result reports failure.

    ``is_error`` is authoritative when present. The text fallback exists because
    several tool wrappers return a well-formed result whose body is an error
    string; it is a heuristic and will miss failures phrased any other way.
    """
    if block.get("is_error"):
        return True
    stripped = text.strip().lower()
    return stripped.startswith("error") or stripped.startswith("<tool_use_error>")


def _account_call(
    name: str,
    args: Mapping[str, Any],
    target: str,
    files_read: list[str],
    read_targets: Counter[str],
    edits: Counter[str],
    grep_queries: Counter[str],
    glob_patterns: Counter[str],
    feats: TrajectoryFeatures,
    cfg: MiningConfig,
    artifact_re: re.Pattern[str] | None,
    doc_re: re.Pattern[str] | None,
) -> None:
    """Fold one tool call into the file-shape counters."""
    lowered = name.lower()
    if lowered in ("read", "notebookread") and target:
        files_read.append(target)
        read_targets[target] += 1
        if cfg.library_prefixes and target.startswith(tuple(cfg.library_prefixes)):
            feats.library_reads += 1
        if doc_re and doc_re.search(target):
            feats.doc_reads += 1
    elif lowered == "write" and target:
        if artifact_re and artifact_re.search(target):
            feats.n_artifact_writes += 1
    elif lowered in ("edit", "multiedit", "notebookedit") and target:
        edits[target] += 1
        if artifact_re and artifact_re.search(target):
            feats.n_artifact_edits += 1
    elif lowered == "grep":
        pattern = args.get("pattern")
        if isinstance(pattern, str):
            grep_queries[pattern] += 1
    elif lowered == "glob":
        pattern = args.get("pattern")
        if isinstance(pattern, str):
            glob_patterns[pattern] += 1
    elif lowered == "bash":
        command = args.get("command")
        if isinstance(command, str) and cfg.validator_commands:
            low = command.lower()
            if any(v.lower() in low for v in cfg.validator_commands):
                feats.validator_invocations += 1


# --------------------------------------------------------------------------
# tail excerpt
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ExcerptBlock:
    """One renderable piece of a turn: a thought, a message, a call, or a result."""

    kind: str
    tool: str = ""
    text: str = ""

    def render(self) -> str:
        if self.kind == "tool":
            return f"  -> {self.tool}({self.text})" if self.text else f"  -> {self.tool}"
        if self.kind == "error":
            return f"  !! {self.text}"
        if self.kind == "thinking":
            return f"  (thinking) {self.text}"
        return f"  {self.text}"


@dataclass(frozen=True)
class TurnExcerpt:
    """One turn of the tail excerpt."""

    role: str
    blocks: tuple[ExcerptBlock, ...] = ()

    def render(self) -> str:
        return "\n".join([f"[{self.role}]"] + [b.render() for b in self.blocks])


def trajectory_excerpt(
    events_path: str | Path | None,
    n_tail_turns: int = 10,
    *,
    text_chars: int = 300,
    arg_chars: int = 200,
) -> list[TurnExcerpt]:
    """Last ``n_tail_turns`` turns in compact form. Empty list when unavailable.

    Unlike the repo3 original this keeps *errored tool results and injected
    turns*, not assistant turns alone. The tail of a failed rollout is usually
    a hook block followed by the agent's response to it, and dropping the block
    left the reader looking at an answer with the question deleted.
    """
    if events_path is None:
        return []
    path = Path(events_path)
    if not path.exists():
        return []

    turns: list[TurnExcerpt] = []
    for event in _iter_events(path):
        etype = event.get("type")
        if etype not in ("assistant", "user", "human", None):
            continue
        role = "assistant" if etype == "assistant" else "environment"
        blocks: list[ExcerptBlock] = []
        for block in _blocks(event):
            if not isinstance(block, Mapping):
                continue
            btype = block.get("type")
            if btype == "text":
                text = " ".join(str(block.get("text") or "").split())[:text_chars]
                if text:
                    blocks.append(ExcerptBlock("error" if role == "environment" else "text", text=text))
            elif btype == "thinking":
                text = " ".join(str(block.get("thinking") or "").split())[:200]
                if text:
                    blocks.append(ExcerptBlock("thinking", text=text))
            elif btype == "tool_use":
                args = block.get("input")
                args = args if isinstance(args, Mapping) else {}
                blocks.append(
                    ExcerptBlock("tool", tool=str(block.get("name") or "?"), text=_target_of(args)[:arg_chars])
                )
            elif btype == "tool_result":
                text = _result_text(block)
                if _is_error_result(block, text):
                    blocks.append(
                        ExcerptBlock("error", text=" ".join(text.split())[:text_chars])
                    )
        if blocks:
            turns.append(TurnExcerpt(role, tuple(blocks)))
    return turns[-n_tail_turns:] if n_tail_turns > 0 else turns


def render_excerpt(turns: Sequence[TurnExcerpt]) -> str:
    """Render a tail excerpt, or say plainly that there is none."""
    if not turns:
        return "(no trajectory excerpt available)"
    return "\n".join(t.render() for t in turns)
