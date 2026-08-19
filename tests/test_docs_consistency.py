"""Guards against documentation drifting away from the code.

Nine passes of changes left the README claiming a stale test count, the package
maps missing four modules, and the architecture document omitting the repair-
directive mechanism from its own package map — the thing that document exists to
describe. None of it was visible from inside any single change.

These checks are deliberately narrow. They verify claims that are *mechanically*
checkable — a module exists, a link resolves, a subcommand is real — and say
nothing about whether the prose is any good. A doc test that tried to police
meaning would fail constantly and get deleted; one that catches a dead link and a
missing module is cheap enough to survive.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
README = REPO_ROOT / "README.md"
ARCHITECTURE = REPO_ROOT / "docs" / "ARCHITECTURE.md"
PACKAGE = REPO_ROOT / "src" / "harness_evolve"


def package_dirs() -> set[str]:
    return {
        p.name for p in PACKAGE.iterdir()
        if p.is_dir() and not p.name.startswith(("_", "."))
    }


@pytest.mark.parametrize("doc", [README, ARCHITECTURE], ids=["README", "ARCHITECTURE"])
def test_package_map_lists_every_module_directory(doc: Path):
    """A package map that silently omits a module is worse than none: a reader
    concludes the thing does not exist."""
    text = doc.read_text()
    missing = sorted(d for d in package_dirs() if f"{d}/" not in text)
    assert not missing, f"{doc.name} does not mention: {missing}"


@pytest.mark.parametrize("doc", [README, ARCHITECTURE], ids=["README", "ARCHITECTURE"])
def test_every_internal_link_resolves(doc: Path):
    text = doc.read_text()
    targets = set(re.findall(r"\]\((docs/[A-Za-z0-9_.\-]+\.md|worklogs/)\)", text))
    dead = sorted(t for t in targets if not (REPO_ROOT / t).exists())
    assert not dead, f"{doc.name} links to nonexistent: {dead}"


def test_every_experiment_writeup_is_indexed():
    """An experiment nobody can find is an experiment nobody reads."""
    written = {p.name for p in (REPO_ROOT / "docs").glob("EXPERIMENT_*.md")}
    indexed = README.read_text()
    missing = sorted(name for name in written if name not in indexed)
    assert not missing, f"README does not link: {missing}"


def test_advertised_cli_subcommands_exist():
    out = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "evolve.py"), "--help"],
        capture_output=True, text=True, cwd=REPO_ROOT, timeout=60,
    ).stdout
    real = set(re.search(r"\{([a-z,]+)\}", out).group(1).split(","))
    advertised = set(re.findall(r"scripts/evolve\.py (\w+)", README.read_text()))
    assert advertised, "the README should show how to run something"
    assert advertised <= real, f"README advertises missing subcommands: {advertised - real}"


def test_no_hardcoded_test_count_in_the_readme():
    """A count in prose is stale the moment a test is added. The README should
    print the command instead of a number that quietly rots."""
    matches = re.findall(r"(\d{3,})\s+tests\b", README.read_text())
    assert not matches, (
        f"README hardcodes a test count {matches}; state the command instead"
    )


def test_hygiene_rule_count_claim_matches_the_registry():
    """A number that *is* worth stating, because it is a claim about coverage."""
    from harness_evolve.hygiene.gate import ALL_RULES

    claimed = re.search(r"(\d+) rules", README.read_text())
    assert claimed, "the README should say how many hygiene rules there are"
    assert int(claimed.group(1)) == len(ALL_RULES)
