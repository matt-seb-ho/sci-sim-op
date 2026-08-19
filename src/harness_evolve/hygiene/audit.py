"""CLI: audit an on-disk adapter directory for ground-truth leakage.

Two jobs. The first is the retro-audit -- point it at a shipped adapter and get
the findings that should have blocked it -- which is how the two known
incidents were characterized in the first place, months after the artifacts
were in use. The second is the pre-flight check for anything materialized
outside the search loop, where :func:`~harness_evolve.hygiene.gate.check_candidate`
never ran.

Exits non-zero on a blocking finding, so it composes into CI and into a
launcher script without anyone having to read the output.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from harness_evolve.core.candidate import SCAFFOLDING_DIRS
from harness_evolve.hygiene.corpus import GroundTruthCorpus
from harness_evolve.hygiene.gate import GateConfig, HygieneReport, check_texts

#: Extensions read as adapter text. Everything an adapter ships is prose or
#: config; code components are check plugins, audited by their own tests.
DEFAULT_TEXT_EXTENSIONS: tuple[str, ...] = (
    ".md", ".markdown", ".txt", ".yaml", ".yml", ".toml", ".json",
)


def read_adapter_dir(
    adapter_dir: Path,
    *,
    extensions: Sequence[str] = DEFAULT_TEXT_EXTENSIONS,
    skip_dirs: Sequence[str] = SCAFFOLDING_DIRS,
) -> dict[str, str]:
    """Adapter-relative path -> text, for every auditable file.

    Scaffolding directories are skipped because they are resolved from the live
    plugin at materialization time and are not candidate-owned; auditing them
    would report the same findings for every candidate in a lineage.
    """
    adapter_dir = Path(adapter_dir)
    exts = {e.lower() for e in extensions}
    skip = tuple(skip_dirs)
    out: dict[str, str] = {}
    for f in sorted(adapter_dir.rglob("*")):
        if not f.is_file() or f.suffix.lower() not in exts:
            continue
        rel = f.relative_to(adapter_dir).as_posix()
        if any(rel == d or rel.startswith(d + "/") for d in skip):
            continue
        try:
            out[rel] = f.read_text(errors="replace")
        except OSError:
            continue
    return out


def audit_dir(
    adapter_dir: Path,
    corpus: GroundTruthCorpus,
    *,
    config: GateConfig | None = None,
    extensions: Sequence[str] = DEFAULT_TEXT_EXTENSIONS,
) -> HygieneReport:
    """Run the full rule set over an on-disk adapter directory."""
    return check_texts(
        read_adapter_dir(adapter_dir, extensions=extensions), corpus, config=config
    )


def _resolve_simulator(name: str | None):
    """Look up a simulator spec by name, or ``None`` if it is unavailable.

    Degrades rather than dies: without a spec the corpus falls back to default
    leaky extensions and on-disk basenames, which still runs every rule. A hard
    failure here would push people toward skipping the audit entirely.
    """
    if not name:
        return None
    try:
        from harness_evolve.simulators.base import SimulatorRegistry

        return SimulatorRegistry.get(name)
    except Exception as exc:  # noqa: BLE001 - any import/registry problem degrades
        print(f"warning: simulator {name!r} unavailable ({exc})", file=sys.stderr)
        return None


def build_corpus(args: argparse.Namespace) -> GroundTruthCorpus:
    """Build the corpus from whichever ground-truth source was supplied."""
    if args.ground_truth_dir:
        return GroundTruthCorpus.from_ground_truth_dir(
            args.ground_truth_dir,
            simulator=_resolve_simulator(args.simulator),
            tasks=args.tasks or None,
        )
    return GroundTruthCorpus.from_blocklist_json(args.blocklist_json)


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns 2 on usage error, 1 on a blocking finding, else 0."""
    ap = argparse.ArgumentParser(
        prog="harness-evolve-hygiene",
        description="Audit an adapter directory for ground-truth leakage.",
    )
    ap.add_argument("--adapter-dir", required=True, type=Path)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument(
        "--ground-truth-dir", type=Path, help="tree laid out as <dir>/<task_id>/..."
    )
    src.add_argument(
        "--blocklist-json",
        type=Path,
        help="precomputed blocklist; use when no ground-truth volume is mounted",
    )
    ap.add_argument("--simulator", help="registered simulator name, for the leak surface")
    ap.add_argument("--tasks", nargs="*", help="restrict the corpus to these task ids")
    ap.add_argument("--out", type=Path, help="write the JSON report here")
    ap.add_argument(
        "--fail-on",
        choices=("error", "warn"),
        default="error",
        help="lowest severity that exits non-zero (default: error)",
    )
    args = ap.parse_args(argv)

    if not args.adapter_dir.is_dir():
        print(f"error: adapter dir not found: {args.adapter_dir}", file=sys.stderr)
        return 2
    source = args.ground_truth_dir or args.blocklist_json
    if not Path(source).exists():
        print(f"error: ground-truth source not found: {source}", file=sys.stderr)
        return 2

    corpus = build_corpus(args)
    if corpus.is_empty:
        # A pass against an empty corpus proves nothing, and reporting it as a
        # pass is how a gate becomes decorative.
        print("error: corpus is empty; nothing could have been detected", file=sys.stderr)
        return 2

    report = audit_dir(args.adapter_dir, corpus)
    print(report.render())
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report.to_dict(), indent=2))
        print(f"wrote {args.out}")

    if report.blocked:
        return 1
    if args.fail_on == "warn" and report.warnings:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via main()
    raise SystemExit(main())
