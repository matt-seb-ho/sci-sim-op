"""Family-grouped train/dev/test splits, and the seal that keeps test hidden.

Why families and not tasks
--------------------------
The 46-task GEOS pool is not 46 independent tasks. It is ~5 physics families with
heavy structural sharing: ``AdvancedExampleDruckerPrager``,
``AdvancedExampleExtendedDruckerPrager`` and ``AdvancedExampleViscoDruckerPrager``
share constitutive blocks, mesh idioms and solver stanzas. Under a random
task-level split an adapter can learn the Drucker-Prager family from one member
and score on its siblings without generalising at all, and the split would report
that as held-out performance.

So a family lives entirely in one split. Absolute test scores are consequently
*lower* than an i.i.d. split would give; that is the point, and both should be
reported (see docs/RESEARCH_PROGRAM.md 4.2).

Why the seal is a mount and not a convention
--------------------------------------------
A capability granted at the mount level -- the geosx binary, added so
``--validate-input`` could run -- also handed the agent a full simulator and went
unnoticed for five weeks (docs/2026-09-02_QA_LOG.md Q8). Enforcement by
convention is what that failure looks like. :func:`sealed_ground_truth` therefore
builds a directory containing only the visible splits, so the container has no
path to test ground truth rather than merely no instruction to read it.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "Split", "family_of", "split_of", "assign", "sealed_ground_truth",
    "SealManifest", "FAMILY_KEYWORDS", "SPLIT_OF_FAMILY",
]

Split = str  # "TRAIN" | "DEV" | "TEST"

#: Matched in order; the first family whose keyword appears wins. ``wellbore``
#: is checked FIRST and is also the residual.
#:
#: First, because the wellbore geometry dominates a deck's structure: an
#: ``AdvancedExampleThermoPoroElasticWellbore`` shares its mesh, boundary and
#: solver stanzas with the other wellbores, not with ``ExampleMandel``. Matching
#: "poroelastic" inside it would put a wellbore in the poroelastic split and leak
#: the family across the boundary -- exactly the failure this module exists to
#: prevent. Caught by an assertion in the tests, not by inspection.
#:
#: Residual, because everything in this pool that matches nothing else is a
#: wellbore variant. Asserted in tests rather than assumed.
FAMILY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("wellbore", ("wellbore",)),
    ("fracture", ("kgd", "pennyfrac", "pkn", "sneddon", "tfrac", "proppant",
                  "singlefraccompression", "hydraulicfracture")),
    ("flow", ("buckleyleverett", "leakywell", "spe11b", "co2fieldcase",
              "deadoil", "hystinjection")),
    ("poroelastic", ("mandel", "thermoporoelastic", "poroelasticity",
                     "faultverification")),
    ("driver", ("triaxialdriver", "relaxationtest")),
)

#: TEST is the flow family: structurally the most distant from the wellbore bulk,
#: so it is the honest generalisation probe rather than the convenient one.
SPLIT_OF_FAMILY: dict[str, Split] = {
    "wellbore": "TRAIN",
    "driver": "TRAIN",
    "fracture": "DEV",
    "poroelastic": "DEV",
    "flow": "TEST",
}


def family_of(task: str) -> str:
    low = task.lower()
    for fam, keys in FAMILY_KEYWORDS:
        if any(k in low for k in keys):
            return fam
    return "wellbore"


def split_of(task: str) -> Split:
    return SPLIT_OF_FAMILY[family_of(task)]


def assign(tasks: list[str]) -> dict[Split, list[str]]:
    out: dict[Split, list[str]] = {"TRAIN": [], "DEV": [], "TEST": []}
    for t in sorted(tasks):
        out[split_of(t)].append(t)
    return out


@dataclass(frozen=True)
class SealManifest:
    """What was visible to a run, recorded so a mount change cannot go unnoticed."""

    visible: tuple[Split, ...]
    sealed: tuple[Split, ...]
    tree: str
    tree_sha256: str
    n_visible_tasks: int
    withheld_tasks: tuple[str, ...] = field(default=())

    def to_json(self) -> str:
        return json.dumps(self.__dict__, indent=1, default=list)


def _hash_tree(root: Path) -> str:
    """Stable hash of the *names* under root. Content is the ground truth we are
    trying not to leak, so it is deliberately not read here."""
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        h.update(str(p.relative_to(root)).encode())
    return h.hexdigest()[:16]


def sealed_ground_truth(
    ground_truth_dir: Path,
    dest: Path,
    visible: tuple[Split, ...] = ("TRAIN", "DEV"),
) -> SealManifest:
    """Materialise a ground-truth tree containing only ``visible`` splits.

    Entries are symlinked, not copied: the tree is read-only to the container and
    a 46-task copy is wasteful. The seal is that sealed-split directories are
    *absent*, so no path to them exists inside the container.
    """
    ground_truth_dir = Path(ground_truth_dir)
    if not ground_truth_dir.is_dir():
        raise FileNotFoundError(ground_truth_dir)
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    kept, withheld = [], []
    for entry in sorted(ground_truth_dir.iterdir()):
        if split_of(entry.name) in visible:
            os.symlink(entry, dest / entry.name)
            kept.append(entry.name)
        else:
            withheld.append(entry.name)

    return SealManifest(
        visible=tuple(visible),
        sealed=tuple(s for s in ("TRAIN", "DEV", "TEST") if s not in visible),
        tree=str(dest),
        tree_sha256=_hash_tree(dest),
        n_visible_tasks=len(kept),
        withheld_tasks=tuple(withheld),
    )
