"""Loading expert demonstrations, and keeping them from leaking the answer.

**Why demonstrations at all.** arXiv:2605.24539 reports that self-rollout
harness evolution works when episodes are short and failures are attributable,
and *fails* under sparse, high-variance reward where they are not -- there,
search is misled by sparse feedback and candidate-selection noise, while
demonstration-bootstrapped evolution under the same budget produces more
effective and auditable edits. Our regime is further into that failure case than
theirs: an in-distribution split already at a quality ceiling, an effect
concentrated in two tasks out of ten, and a couple of dozen rollouts to spend.

**Why we can do it.** Most of this literature has no expert traces to fall back
on. We do: domain experts authored decks under observation, with their browsing
recorded, and every benchmark task has a hand-validated reference deck. That is
an unusual asset for a harness-evolution setting and it is the main reason to
think this search can work where reward-only search would not.

**Why this module is mostly about hygiene.** A demonstration is, by
construction, a record of an expert solving the exact task we score. It is the
single most concentrated source of ground-truth leakage in the system -- more so
than trajectories, because it *worked*. An expert's browser history names the
sibling deck they used as a structural template; their notes name the values
they looked up. So demonstrations are sanitized on load, through the same gate
adapters face, and a demonstration that cannot be sanitized is dropped rather
than trimmed. Nothing here is allowed to reach a proposer unfiltered.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from harness_evolve.proposers.base import Demonstration

#: Participant identifiers are replaced on load. The people who sat the study
#: are not part of the method, and their names have no business travelling into
#: a model prompt or a committed artifact.
_ANON = "Expert"


@dataclass
class SanitizationReport:
    """What was removed from a demonstration, and whether it survived."""

    kept: bool
    removed_filenames: list[str] = field(default_factory=list)
    removed_numerics: list[str] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kept": self.kept,
            "removed_filenames": self.removed_filenames,
            "removed_numerics": self.removed_numerics,
            "reason": self.reason,
        }


#: Deliberately broader than any single simulator's leak pattern: a
#: demonstration is sanitized before we necessarily know which simulator's gate
#: applies, so it errs toward stripping.
_ARTIFACT_RE = re.compile(
    r"\b[A-Za-z0-9_][A-Za-z0-9_.\-]*\.(?:xml|geos|msh|vtk|vtu|rst|foam|in|lmp|yaml|yml)\b"
)
_URL_PATH_RE = re.compile(r"https?://\S+")


def sanitize(
    demo: Demonstration,
    *,
    task_ids: Iterable[str] = (),
    numeric_blocklist: Iterable[str] = (),
    drop_if_task_named: bool = True,
) -> tuple[Demonstration, SanitizationReport]:
    """Strip answer-shaped content from a demonstration.

    What survives is the *strategy*: which documentation areas the expert
    consulted, in what order, what they reported finding hard. What does not
    survive is anything that identifies a specific reference artifact or a
    specific value -- those are the answer, and a proposer that sees them will
    write them into an always-on adapter.
    """
    report = SanitizationReport(kept=True)
    fields = {
        "summary": demo.summary,
        "artifact_excerpt": demo.artifact_excerpt,
        "notes": demo.notes,
    }
    cleaned: dict[str, str] = {}

    for name, text in fields.items():
        if not text:
            cleaned[name] = text
            continue
        found = _ARTIFACT_RE.findall(text)
        report.removed_filenames += found
        text = _ARTIFACT_RE.sub("<reference artifact>", text)
        text = _URL_PATH_RE.sub(lambda m: _strip_url(m.group(0)), text)
        for num in numeric_blocklist:
            if num and num in text:
                report.removed_numerics.append(num)
                text = text.replace(num, "<value>")
        cleaned[name] = text

    sources = []
    for s in demo.sources_consulted:
        s = _ARTIFACT_RE.sub("<reference artifact>", s)
        sources.append(_strip_url(s) if s.startswith("http") else s)

    # A demonstration naming a benchmark task is describing that task's answer.
    # Its own task id is fine -- it is the label, not the content.
    others = [t for t in task_ids if t != demo.task and _names(t, cleaned, sources)]
    if others and drop_if_task_named:
        return demo, SanitizationReport(
            kept=False,
            reason=f"names other benchmark task(s): {', '.join(sorted(others)[:3])}",
        )

    return (
        replace(
            demo,
            summary=cleaned["summary"],
            artifact_excerpt=cleaned["artifact_excerpt"],
            notes=cleaned["notes"],
            sources_consulted=tuple(sources),
            provenance=demo.provenance or "sanitized on load",
        ),
        report,
    )


def _names(task: str, fields: dict[str, str], sources: Sequence[str]) -> bool:
    pattern = re.compile(rf"\b{re.escape(task)}\b")
    return any(pattern.search(v) for v in fields.values() if v) or any(
        pattern.search(s) for s in sources
    )


def _strip_url(url: str) -> str:
    """Keep the documentation *area*, drop the specific page.

    "the expert read the events/outputs documentation" is a transferable
    strategy; the exact anchor they landed on is closer to a lookup key.
    """
    m = re.match(r"https?://([^/]+)/(.*)", url)
    if not m:
        return "<link>"
    host, path = m.group(1), m.group(2)
    parts = [p for p in path.split("/") if p and not p.endswith((".html", ".xml"))]
    area = "/".join(parts[-2:]) if parts else ""
    return f"{host}:{area}" if area else host


def anonymize(name: str, index: int) -> str:
    return f"{_ANON} {index + 1}"


# ---------------------------------------------------------------------------
# loaders
# ---------------------------------------------------------------------------


def load_jsonl(
    path: Path,
    *,
    task_ids: Iterable[str] = (),
    numeric_blocklist: Iterable[str] = (),
) -> tuple[list[Demonstration], list[SanitizationReport]]:
    """Load demonstrations from a JSONL file, sanitizing each.

    Expected fields per line: ``task``, ``summary``, optionally
    ``artifact_excerpt``, ``sources_consulted``, ``notes``, ``provenance``.
    """
    demos: list[Demonstration] = []
    reports: list[SanitizationReport] = []
    for i, line in enumerate(Path(path).read_text().splitlines()):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            reports.append(SanitizationReport(kept=False, reason=f"line {i}: bad JSON"))
            continue
        demo = Demonstration(
            task=str(d.get("task", "")),
            summary=str(d.get("summary", "")),
            artifact_excerpt=str(d.get("artifact_excerpt", "")),
            sources_consulted=tuple(d.get("sources_consulted") or ()),
            notes=str(d.get("notes", "")),
            provenance=str(d.get("provenance", "")),
        )
        clean, rep = sanitize(
            demo, task_ids=task_ids, numeric_blocklist=numeric_blocklist
        )
        reports.append(rep)
        if rep.kept:
            demos.append(clean)
    return demos, reports


def from_browser_history(
    visits: Sequence[str],
    *,
    task: str,
    participant_index: int = 0,
    notes: str = "",
) -> Demonstration:
    """Build a demonstration from a list of visited URLs.

    Collapses a visit list into documentation *areas* with counts, because that
    is the part that generalises. The observed strategy in our own study was
    prose-driven: experts read the simulator's narrative documentation to
    assemble a deck from concept descriptions, where the agent instead
    analogises from concrete example files in the source tree. That difference
    is precisely the kind of thing a proposer can act on, and it survives
    sanitization intact.
    """
    areas: dict[str, int] = {}
    for url in visits:
        area = _strip_url(url)
        areas[area] = areas.get(area, 0) + 1
    ranked = sorted(areas.items(), key=lambda kv: -kv[1])
    summary = (
        f"{anonymize('', participant_index)} authored this deck by reading "
        f"narrative documentation rather than by analogy from example files: "
        f"{len(visits)} navigations across {len(areas)} documentation areas."
    )
    return Demonstration(
        task=task,
        summary=summary,
        sources_consulted=tuple(f"{a} (x{n})" for a, n in ranked[:10]),
        notes=notes,
        provenance="browser history, expert authoring session",
    )


def render_all(demos: Sequence[Demonstration], max_chars: int = 4000) -> str:
    """Render a demonstration set for a proposer prompt, under a budget."""
    if not demos:
        return "(no expert demonstrations available)"
    out: list[str] = []
    budget = max_chars
    for d in demos:
        block = d.render(max_chars=min(budget, 1200))
        if len(block) > budget:
            break
        out.append(block)
        budget -= len(block)
    return "\n\n".join(out)
